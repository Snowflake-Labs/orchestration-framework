"""Cortex Cube Planner"""

import asyncio
import json
import re
from typing import Any, Optional, Sequence, Union
from uuid import UUID

# from litellm import acompletion
import aiohttp
from langchain.callbacks.base import AsyncCallbackHandler

from CortexCube.cube.constants import END_OF_PLAN
from CortexCube.cube.output_parser import (
    ACTION_PATTERN,
    THOUGHT_PATTERN,
    CubePlanParser,
    instantiate_task,
)
from CortexCube.cube.task_fetching_unit import Task
from CortexCube.executors.schema import Plan
from CortexCube.tools.base import StructuredTool, Tool
from CortexCube.tools.logger import cube_logger
import logging

JOIN_DESCRIPTION = (
    "join():\n"
    " - Collects and combines results from prior actions.\n"
    " - A LLM agent is called upon invoking join to either finalize the user query or wait until the plans are executed.\n"
    " - join should always be the last action in the plan, and will be called in two scenarios:\n"
    "   (a) if the answer can be determined by gathering the outputs from tasks to generate the final response.\n"
    "   (b) if the answer cannot be determined in the planning phase before you execute the plans. "
)


def generate_cube_prompt(
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
        prefix += f"{i+1}. {tool.description}\n"

    # Join operation
    prefix += f"{i+2}. {JOIN_DESCRIPTION}\n\n"

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
        f" - Always call join as the last action in the plan. Say '{END_OF_PLAN}' after you call join\n"
        " - Ensure the plan maximizes parallelizability.\n"
        " - Only use the provided action types. If a query cannot be addressed using these, invoke the join action for the next steps.\n"
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


class CubeCallback(AsyncCallbackHandler):
    _queue: asyncio.Queue[Optional[Task]]
    _parser: StreamingGraphParser
    _tools: Sequence[Union[Tool, StructuredTool]]

    def __init__(
        self,
        queue: asyncio.Queue[Optional[str]],
        tools: Sequence[Union[Tool, StructuredTool]],
    ):
        self._queue = queue
        self._parser = StreamingGraphParser(tools=tools)

    async def on_llm_start(self, serialized, prompts, **kwargs: Any) -> Any:
        """Run when LLM starts running."""

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        parsed_data = self._parser.ingest_token(token)
        if parsed_data:
            await self._queue.put(parsed_data)
            if parsed_data.is_join:
                await self._queue.put(None)

    async def on_llm_end(
        self,
        response,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        parsed_data = self._parser.finalize()
        if parsed_data:
            await self._queue.put(parsed_data)
        await self._queue.put(None)


class Planner:
    def __init__(
        self,
        session: object,
        llm: str,  # point to dspy
        example_prompt: str,
        example_prompt_replan: str,
        tools: Sequence[Union[Tool, StructuredTool]],
        stop: Optional[list[str]],
    ):
        self.llm = llm
        self.session = session
        self.system_prompt = generate_cube_prompt(
            tools=tools,
            example_prompt=example_prompt,
            is_replan=False,
        )
        self.system_prompt_replan = generate_cube_prompt(
            tools=tools,
            example_prompt=example_prompt_replan,
            is_replan=True,
        )
        self.tools = tools
        self.output_parser = CubePlanParser(tools=tools)
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

        message = system_prompt + "\n\n" + human_prompt
        headers, url, data = self._prepare_llm_request(prompt=message)

        async with aiohttp.ClientSession(
            headers=headers,
        ) as session:
            async with session.post(url=url, json=data) as response:
                response_text = await response.text()
                snowflake_response = self._parse_snowflake_response(response_text)
                return snowflake_response

    def _prepare_llm_request(self, prompt):
        headers = {
            "Accept": "text/stream",
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{self.session.connection.rest.token}"',
        }

        url = f"""https://{self.session.get_current_account().replace('"',"")}.snowflakecomputing.com/api/v2/cortex/inference:complete"""
        data = {"model": self.llm, "messages": [{"content": prompt}]}

        return headers, url, data

    def _parse_snowflake_response(self, data_str):
        json_objects = data_str.split("\ndata: ")
        json_list = []

        # Iterate over each JSON object
        for obj in json_objects:
            obj = obj.strip()
            if obj:
                # Remove the 'data: ' prefix if it exists
                if obj.startswith("data: "):
                    obj = obj[6:]
                # Load the JSON object into a Python dictionary
                json_dict = json.loads(str(obj))
                # Append the JSON dictionary to the list
                json_list.append(json_dict)

        completion = ""
        choices = {}
        for chunk in json_list:
            choices = chunk["choices"][0]

            if "content" in choices["delta"].keys():
                completion += choices["delta"]["content"]

        cube_logger.log(logging.DEBUG, f"Planner response:{completion}")
        return completion

    async def plan(self, inputs: dict, is_replan: bool, **kwargs: Any):
        llm_response = await self.run_llm(
            inputs=inputs,
            is_replan=is_replan,
        )
        llm_response = llm_response + "\n"
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
