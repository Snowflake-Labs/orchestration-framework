# Copyright 2025 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Cortex gateway Planner"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any, Optional, Union

from snowflake.core import Root
from snowflake.core.cortex.inference_service import (
    CompleteRequest,
    CompleteRequestMessagesInner,
)

from agent_gateway.gateway.constants import END_OF_PLAN
from agent_gateway.gateway.output_parser import (
    ACTION_PATTERN,
    THOUGHT_PATTERN,
    GatewayPlanParser,
    instantiate_task,
)
from agent_gateway.gateway.task_processor import Task
from agent_gateway.tools.base import StructuredTool, Tool
from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.schema import Plan
from agent_gateway.tools.utils import parse_complete_reponse


class AgentGatewayError(Exception):
    def __init__(self, message):
        self.message = message
        gateway_logger.log("ERROR", message)
        super().__init__(self.message)


FUSE_DESCRIPTION = (
    "fuse():\n"
    " - Collects and combines results from prior actions.\n"
    " - A LLM agent is called upon invoking fuse to either finalize the user query or wait until the plans are executed.\n"
    " - fuse should always be the last action in the plan, and will be called in two scenarios:\n"
    "   (a) if the answer can be determined by gathering the outputs from tasks to generate the final response.\n"
    "   (b) if the answer cannot be determined in the planning phase before you execute the plans. "
)


def generate_gateway_prompt(
    tools: Sequence[Union[Tool, StructuredTool]],
    example_prompt=str,
    is_replan: bool = False,
):
    prefix = (
        "Given a user query, create a plan to solve it with the utmost parallelizability. "
        f"Each plan should comprise an action from the following {len(tools) + 1} types:\n"
    )

    # Tools
    for i, tool in enumerate(tools):
        prefix += f"{i + 1}. {tool.description}\n"

    # FUSE operation
    prefix += f"{i + 2}. {FUSE_DESCRIPTION}\n\n"

    # Guidelines
    prefix += (
        "Guidelines:\n"
        " - Each action described above contains input/output types and description.\n"
        "    - You must strictly adhere to the input and output types for each action.\n"
        "    - The action descriptions contain the guidelines. You MUST strictly follow those guidelines when you use the actions.\n"
        " - Each action in the plan should strictly be one of the above types. Follow the Python conventions for each action.\n"
        " - Each action MUST have a unique ID, which is strictly increasing.\n"
        " - Inputs for actions can either be constants or outputs from preceding actions. "
        "In the latter case, use the format $id to denote the ID of the previous action whose output will be the input.\n"
        f" - Always call fuse as the last action in the plan. Say '{END_OF_PLAN}' after you call fuse\n"
        " - Ensure the plan maximizes parallelizability.\n"
        " - Only use the provided action types. If a query cannot be addressed using these, invoke the fuse action for the next steps.\n"
        " - Never explain the plan with comments (e.g. #).\n"
        " - Never introduce new actions other than the ones provided.\n\n"
    )

    if is_replan:
        prefix += (
            ' - You are given "Previous Plan" which is the plan that the previous agent created along with the execution results '
            "(given as Observation) of each plan and a general thought (given as Thought) about the executed results."
            'You MUST use these information to create the next plan under "Current Plan".\n'
            ' - When starting the Current Plan, you should start with "Thought" that outlines the strategy for the next plan.\n'
            " - In the Current Plan, you should NEVER repeat the actions that are already executed in the Previous Plan.\n"
        )

    # Examples
    prefix += "Here are some examples:\n\n"
    prefix += example_prompt

    return prefix


class StreamingGraphParser:
    """Streaming version of the GraphParser."""

    buffer = ""
    thought = ""
    graph_dict = {}

    def __init__(self, tools: Sequence[Union[Tool, StructuredTool]]) -> None:
        self.tools = tools

    def _match_buffer_and_generate_task(self, suffix: str) -> Optional[Task]:
        """Runs every time "\n" is encountered in the input stream or at the end of the stream.
        Matches the buffer against the regex patterns and generates a task if a match is found.
        Match patterns include:
        1. Thought: <thought>
          - this case, the thought is stored in self.thought, and we reset the buffer.
          - the thought is then used as the thought for the next action.
        2. <idx>. <tool_name>(<args>)
          - this case, the tool is instantiated with the idx, tool_name, args, and thought.
          - the thought is reset.
          - the buffer is reset.
        """
        if match := re.match(THOUGHT_PATTERN, self.buffer):
            # Optionally, action can be preceded by a thought
            self.thought = match.group(1)
        elif match := re.match(ACTION_PATTERN, self.buffer):
            # if action is parsed, return the task, and clear the buffer
            idx, tool_name, args, _ = match.groups()
            idx = int(idx)
            task = instantiate_task(
                tools=self.tools,
                idx=idx,
                tool_name=tool_name,
                args=args,
                thought=self.thought,
            )
            self.thought = ""
            return task

        return None

    def ingest_token(self, token: str) -> Optional[Task]:
        # Append token to buffer
        if "\n" in token:
            prefix, suffix = token.split("\n", 1)
            prefix = prefix.strip()
            self.buffer += prefix + "\n"
            matched_item = self._match_buffer_and_generate_task(suffix)
            self.buffer = suffix
            return matched_item
        else:
            self.buffer += token

        return None

    def finalize(self):
        self.buffer = self.buffer + "\n"
        return self._match_buffer_and_generate_task("")


class Planner:
    def __init__(
        self,
        session: object,
        llm: str,
        example_prompt: str,
        example_prompt_replan: str,
        tools: Sequence[Union[Tool, StructuredTool]],
        stop: Optional[list[str]],
    ):
        self.llm = llm
        self.session = session
        self.tools = tools

        tools_without_summarizer = [i for i in self.tools if (i.name != "summarize")]

        self.system_prompt = generate_gateway_prompt(
            tools=tools_without_summarizer,
            example_prompt=example_prompt,
            is_replan=False,
        )
        self.system_prompt_replan = generate_gateway_prompt(
            tools=tools_without_summarizer,
            example_prompt=example_prompt_replan,
            is_replan=True,
        )
        self.output_parser = GatewayPlanParser(tools=tools)
        self.stop = stop

    async def run_llm(
        self,
        inputs: dict[str, Any],
        is_replan: bool = False,
    ) -> str:
        """Run the LLM."""
        if is_replan:
            system_prompt = self.system_prompt_replan
            assert "context" in inputs, "If replanning, context must be provided"
            human_prompt = f"Question: {inputs['input']}\n{inputs['context']}\n"
        else:
            system_prompt = self.system_prompt
            human_prompt = f"Question: {inputs['input']}"

        messages = [system_prompt + "\n\n" + human_prompt]
        messages = [
            (
                CompleteRequestMessagesInner(content=message)
                if isinstance(message, str)
                else message
            )
            for message in messages
        ]
        req = CompleteRequest(model=self.llm, messages=messages)
        res = (
            Root(self.session.connection)
            .cortex_inference_service.complete(req)
            .events()
        )
        return parse_complete_reponse(res)

    async def plan(self, inputs: dict, is_replan: bool, **kwargs: Any):
        llm_response = await self.run_llm(
            inputs=inputs,
            is_replan=is_replan,
        )
        llm_response = llm_response + "\n"
        gateway_logger.log("DEBUG", f"Agent Execution Plan:{llm_response}")
        plan_response = self.output_parser.parse(llm_response)
        return plan_response

    async def aplan(
        self,
        inputs: dict,
        task_queue: asyncio.Queue[Optional[str]],
        is_replan: bool,
        **kwargs: Any,
    ) -> Plan:
        """Given input, asynchronously decide what to do."""
        aplan_response = self.run_llm(inputs=inputs, is_replan=is_replan)
        await aplan_response
