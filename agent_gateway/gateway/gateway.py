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
from __future__ import annotations

import ast
import asyncio
import json
import re
import threading
from collections.abc import Sequence
from typing import Any, Dict, List, Mapping, Optional, Union, cast, ClassVar

from snowflake.connector.connection import SnowflakeConnection
from snowflake.snowpark import Session

from agent_gateway.gateway.constants import FUSION_REPLAN
from agent_gateway.gateway.planner import Planner
from agent_gateway.gateway.task_processor import Task, TaskProcessor
from agent_gateway.tools.base import StructuredTool, Tool
from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.snowflake_prompts import OUTPUT_PROMPT
from agent_gateway.tools.snowflake_prompts import (
    PLANNER_PROMPT as SNOWFLAKE_PLANNER_PROMPT,
)
from agent_gateway.tools.utils import (
    CortexEndpointBuilder,
    _determine_runtime,
    post_cortex_request,
    set_tag,
    _should_instrument,
)

from agent_gateway.tools.snowflake_tools import (
    CortexAnalystTool,
    PythonTool,
    CortexSearchTool,
)

if _should_instrument():
    from trulens.apps.app import TruApp
    from trulens.apps.app import instrument
    from trulens.core import TruSession


class AgentGatewayError(Exception):
    def __init__(self, message):
        self.message = message
        gateway_logger.log("ERROR", self.message)
        super().__init__(self.message)


class CortexCompleteAgent:
    """Self defined agent for Cortex gateway."""

    def __init__(self, session, llm) -> None:
        self.llm = llm
        self.session = session

    async def arun(self, prompt: str) -> str:
        """Run the LLM."""
        headers, url, data = self._prepare_llm_request(prompt=prompt)

        try:
            response_text = await post_cortex_request(
                url=url, headers=headers, data=data
            )

        except Exception as e:
            raise AgentGatewayError(
                message=f"Failed Cortex LLM Request. See details:{str(e)}"
            ) from e

        try:
            if _determine_runtime():
                response_text = json.loads(response_text).get("content")

            snowflake_response = self._parse_snowflake_response(response_text)

            return snowflake_response
        except Exception:
            raise AgentGatewayError(
                message=f"Failed Cortex LLM Request. Unable to parse response. See details:{response_text}"
            )

    def _prepare_llm_request(self, prompt):
        eb = CortexEndpointBuilder(self.session)
        url = eb.get_complete_endpoint()
        headers = eb.get_complete_headers()
        data = {"model": self.llm, "messages": [{"content": prompt}]}

        return headers, url, data

    def _parse_snowflake_response(self, data_str):
        try:
            json_list = []

            if _determine_runtime():
                json_list = [i["data"] for i in json.loads(data_str)]

            else:
                json_objects = data_str.split("\ndata: ")

                # Iterate over each object
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

            return completion
        except KeyError as e:
            raise AgentGatewayError(
                message=f"Missing Cortex LLM response components. {str(e)}"
            )


class SummarizationAgent(Tool):
    def __init__(self, session, agent_llm):
        tool_name = "summarize"
        tool_description = "Concisely summarizes cortex search output"
        summarizer = CortexCompleteAgent(session=session, llm=agent_llm)
        super().__init__(
            name=tool_name, func=summarizer.arun, description=tool_description
        )


class Agent:
    """Cortex Gateway Multi Agent Class"""

    input_key: str = "input"
    output_key: str = "output"
    fuse: ClassVar[Any]
    acall: ClassVar[Any]
    handle_exception: ClassVar[Any]
    run_async: ClassVar[Any]
    search_tool: Optional[CortexSearchTool] = None

    def __init__(
        self,
        snowflake_connection: Union[Session, SnowflakeConnection],
        tools: list[
            Union[Tool, StructuredTool, CortexAnalystTool, CortexSearchTool, PythonTool]
        ],
        max_retries: int = 2,
        planner_llm: str = "mistral-large2",
        agent_llm: str = "mistral-large2",
        memory: bool = True,
        planner_example_prompt: str = SNOWFLAKE_PLANNER_PROMPT,
        planner_example_prompt_replan: Optional[str] = None,
        fusion_prompt: str = OUTPUT_PROMPT,
        **kwargs,
    ) -> None:
        """Parameters

        ----------

        Args:
            snowflake_connection: authenticated Snowflake connection object
            tools: List of tools to use.
            max_retries: Maximum number of replans to do. Defaults to 2.
            planner_llm: Name of Snowflake Cortex LLM to use for planning.
            agent_llm: Name of Snowflake Cortex LLM to use for planning.
            memory: Boolean to turn on memory mechanism or not. Defaults to True.
            planner_example_prompt: Example prompt for planning. Defaults to SNOWFLAKE_PLANNER_PROMPT.
            planner_example_prompt_replan: Example prompt for replanning.
                Assign this if you want to use different example prompt for replanning.
                If not assigned, default to `planner_example_prompt`.
            planner_stop: Stop tokens for planning.
            fusion_prompt: Prompt to use for fusion.
        """

        def _unused_tool():
            pass

        set_tag(
            connection=snowflake_connection,
        )

        if _should_instrument():
            self._search_tool_placeholder = CortexSearchTool(
                service_name="",
                service_topic="",
                data_description="",
                retrieval_columns="",
                snowflake_connection=snowflake_connection,
            )
            self._analyst_tool_placeholder = CortexAnalystTool(
                semantic_model="",
                stage="",
                service_topic="",
                data_description="",
                snowflake_connection=snowflake_connection,
            )
            self._python_tool_placeholder = PythonTool(
                python_func=_unused_tool, tool_description="", output_description=""
            )

            self._planner_placheholder = Planner(
                session="",
                llm="",
                example_prompt="",
                example_prompt_replan="",
                tools=[self._analyst_tool_placeholder],
            ).plan(inputs={}, is_replan=False)

            instrument.method(CortexSearchTool, "asearch")
            instrument.method(CortexAnalystTool, "query")
            instrument.method(CortexAnalystTool, "_process_analyst_message")
            instrument.method(Planner, "plan")

        summarizer = SummarizationAgent(
            session=snowflake_connection, agent_llm=agent_llm
        )
        tools_with_summarizer = tools + [summarizer]

        self.planner = Planner(
            session=snowflake_connection,
            llm=planner_llm,
            example_prompt=planner_example_prompt,
            example_prompt_replan=planner_example_prompt_replan,
            tools=tools_with_summarizer,
        )

        self.agent = CortexCompleteAgent(session=snowflake_connection, llm=agent_llm)
        self.fusion_prompt = fusion_prompt
        self.fusion_prompt_final = fusion_prompt
        self.planner_stream = False
        self.max_retries = max_retries

        # basic memory
        self.memory = memory
        if self.memory:
            self.memory_context = []

        # callbacks
        self.planner_callback = None
        self.executor_callback = None
        gateway_logger.log("INFO", "Cortex gateway successfully initialized")

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    def _parse_fusion_output(self, raw_answer: str) -> str:
        """We expect the fusion output format to be:
        ```
        Thought: xxx
        Action: Finish/Replan(yyy)
        ```
        Returns:
            thought (xxx)
            answer (yyy)
            is_replan (True/False)
        """
        # Extracting the Thought
        thought_pattern = r"Thought: (.*?)\n\n"
        thought_match = re.search(thought_pattern, raw_answer)
        thought = thought_match.group(1) if thought_match else None

        # Extracting the Answer
        is_replan = FUSION_REPLAN in raw_answer

        if is_replan:
            answer = self._extract_replan_message(raw_answer)
        else:
            answer = self._extract_answer(raw_answer)

        if answer is None:
            raise AgentGatewayError(
                message=f"Unable to parse final answer. Raw answer is:{raw_answer}"
            )

        return thought, answer, is_replan

    @staticmethod
    def _extract_answer(raw_answer):
        start_marker = "Action: Finish"
        end_marker = "<END_OF_RESPONSE>"

        # if end market not in response, inject it
        if end_marker not in raw_answer:
            raw_answer += end_marker

        # Match both parenthesized and non-parenthesized versions
        pattern = re.compile(
            rf"{re.escape(start_marker)}[(\s]*(.*?)(?:\s*\))?\s*{re.escape(end_marker)}",
            re.DOTALL,
        )

        match = pattern.search(raw_answer)
        return match.group(1).strip() if match else None

    def _extract_replan_message(self, raw_answer):
        replan_start = "Action: Replan("
        replan_index = raw_answer.find(replan_start)
        if replan_index != -1:
            replan_index += len(replan_start)
            return raw_answer[replan_index : raw_answer.rfind(")")].strip()
        return (
            "We couldn't find the information you're looking for. You can try "
            "rephrasing your request or validate that the provided tools contain "
            "sufficient information."
        )

    def _generate_context_for_replanner(
        self, tasks: Mapping[int, Task], fusion_thought: str
    ) -> str:
        """Formatted like this:
        ```
        1. action 1
        Observation: xxx
        2. action 2
        Observation: yyy
        ...
        Thought: fusion_thought
        ```
        """
        previous_plan_and_observations = "\n".join(
            [
                task.get_thought_action_observation(
                    include_action=True, include_action_idx=True
                )
                for task in tasks.values()
                if not task.is_fuse
            ]
        )
        fusion_thought = f"Thought: {fusion_thought}"
        context = "\n\n".join([previous_plan_and_observations, fusion_thought])
        return context

    def _format_contexts(self, contexts: Sequence[str]) -> str:
        """Contexts is a list of context
        each context is formatted as the description of _generate_context_for_replanner
        """
        formatted_contexts = ""
        for context in contexts:
            formatted_contexts += f"Previous Plan:\n\n{context}\n\n"
        formatted_contexts += "Current Plan:\n\n"
        return formatted_contexts

    async def fuse(
        self, input_query: str, agent_scratchpad: str, is_final: bool
    ) -> str:
        if is_final:
            fusion_prompt = self.fusion_prompt_final
        else:
            fusion_prompt = self.fusion_prompt
        prompt = (
            f"{fusion_prompt}\n"  # Instructions and examples
            f"Question: {input_query}\n\n"  # User input query
            f"{agent_scratchpad}\n"  # T-A-O
            # "---\n"
        )

        response = await self.agent.arun(prompt)
        raw_answer = cast(str, response)
        gateway_logger.log("DEBUG", "Question: \n", input_query, block=True)
        gateway_logger.log("DEBUG", "Raw Answer: \n", raw_answer, block=True)
        thought, answer, is_replan = self._parse_fusion_output(raw_answer)
        sources = self._extract_sources(agent_scratchpad)
        if is_final:
            # If final, we don't need to replan
            is_replan = False
        return thought, answer, sources, is_replan

    def _extract_sources(self, text):
        try:
            raw_matches = self._parse_sources(text)

            if not raw_matches:
                return None

            seen = set()
            unique_matches = []

            def make_hashable(obj):
                """Recursively convert lists/dictionaries to hashable types."""
                if isinstance(obj, list):
                    return tuple(make_hashable(item) for item in obj)
                elif isinstance(obj, dict):
                    return tuple(
                        (key, make_hashable(value)) for key, value in obj.items()
                    )
                return obj

            for record in raw_matches:
                # Convert the entire record to a hashable type
                record_tuple = make_hashable(record)
                if record_tuple not in seen:
                    unique_matches.append(record)
                    seen.add(record_tuple)

            sources = []
            for record in unique_matches:
                source_entry = {
                    "tool_type": record.get("tool_type"),
                    "tool_name": record.get("tool_name"),
                    "metadata": record.get("metadata", {}),
                }
                sources.append(source_entry)

        except (ValueError, SyntaxError) as e:
            raise e

        return sources if sources else None

    def _parse_sources(self, text):
        pattern = r"'sources':\s*(\{(?:[^{}]|(?:\{[^{}]*\}))*\})"
        matches = re.findall(pattern, text, re.DOTALL)

        if not matches:
            return None

        sources_list = []

        for match in matches:
            try:
                sources_dict = ast.literal_eval(match)

                metadata = sources_dict.get("metadata", [])
                if not isinstance(metadata, list):
                    metadata = [metadata]

                source_entry = {
                    "tool_type": sources_dict.get("tool_type"),
                    "tool_name": sources_dict.get("tool_name"),
                    "metadata": metadata,
                }

                # Avoid duplicates
                if source_entry not in sources_list:
                    sources_list.append(source_entry)

            except (ValueError, SyntaxError):
                continue

        return sources_list if sources_list else None

    def _call(self, inputs):
        return self.__call__(inputs)

    def __call__(self, input: str) -> Any:
        """Calls Cortex gateway multi-agent system.

        Params:
            input (str): user's natural language request
        """
        result = []
        error = []

        thread = threading.Thread(target=self.run_async, args=(input, result, error))
        thread.start()
        thread.join()

        if error:
            gateway_logger.log("DEBUG", f"ERROR NoneType: {error}")
            gateway_logger.log("DEBUG", f"ERROR RESULT: {result}")
            raise AgentGatewayError(message=str(error[0]))

        if not result:
            raise AgentGatewayError("Unable to retrieve response. Result is empty.")

        return result[0]

    def handle_exception(self, loop, context):
        loop.default_exception_handler(context)
        loop.stop()

    def run_async(self, input, result, error):
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(self.handle_exception)
        asyncio.set_event_loop(loop)
        try:
            task = loop.run_until_complete(self.acall(input))
            result.append(task)
        except asyncio.CancelledError:
            error.append(AgentGatewayError("Task was cancelled"))
        except RuntimeError as e:
            error.append(AgentGatewayError(f"RuntimeError: {str(e)}"))
        except Exception as e:
            error.append(AgentGatewayError(f"Gateway Execution Error: {str(e)}"))

        finally:
            try:
                # Cancel any pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Wait for all tasks to be cancelled
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            finally:
                loop.close()

    async def acall(
        self,
        input: str,
    ) -> Dict[str, Any]:
        sources = []
        contexts = []
        fusion_thought = ""
        agent_scratchpad = ""

        if self.memory:
            input_with_mem = f"My previous question/answer was: {self.memory_context}\n. If needed, use that context and this {input} to answer my question. Otherwise just give me an answer to: {input} "
            inputs = {"input": input_with_mem}
        else:
            inputs = {"input": input}

        for i in range(self.max_retries):
            is_first_iter = i == 0
            is_final_iter = i == self.max_retries - 1

            task_processor = TaskProcessor()
            if self.planner_stream:
                task_queue = asyncio.Queue()
                asyncio.create_task(
                    self.planner.aplan(
                        inputs=inputs,
                        task_queue=task_queue,
                        is_replan=not is_first_iter,
                        callbacks=(
                            [self.planner_callback] if self.planner_callback else None
                        ),
                    )
                )
                await task_processor.aschedule(
                    task_queue=task_queue, func=lambda x: None
                )
            else:
                tasks = await self.planner.plan(
                    inputs=inputs,
                    is_replan=not is_first_iter,
                )

                task_processor.set_tasks(tasks)
                await task_processor.schedule()
            tasks = task_processor.tasks

            # collect thought-action-observation
            agent_scratchpad += "\n\n"
            agent_scratchpad += "".join(
                [
                    task.get_thought_action_observation(
                        include_action=True, include_thought=True
                    )
                    for task in tasks.values()
                    if not task.is_fuse
                ]
            )

            agent_scratchpad = agent_scratchpad.strip()

            fusion_thought, answer, sources, is_replan = await self.fuse(
                input,
                agent_scratchpad=agent_scratchpad,
                is_final=is_final_iter,
            )
            if not is_replan:
                break
            else:
                gateway_logger.log("INFO", "Replanning....")

            # Collect contexts for the subsequent replanner
            context = self._generate_context_for_replanner(
                tasks=tasks, fusion_thought=fusion_thought
            )
            contexts.append(context)
            formatted_contexts = self._format_contexts(contexts)
            inputs["context"] = formatted_contexts

        max_memory = 3  # TODO consider exposing this to users
        if self.memory:
            if len(self.memory_context) <= max_memory:
                self.memory_context.append({"Question:": input, "Answer": answer})

        if is_replan and is_final_iter:
            return {
                "output": f"{answer} \n Unable to respond to your request with the available information in the system.  Consider rephrasing your request or providing additional tools.",
                "sources": None,
            }
        else:
            return {"output": answer, "sources": sources}


if _should_instrument():

    class TruAgent:
        def __init__(
            self, app_name, app_version, trulens_snowflake_connection, **kwargs
        ):
            self.agent = Agent(**kwargs)

            instrument.method(Agent, "__call__")
            instrument.method(Agent, "acall")
            instrument.method(Agent, "fuse")

            self.tru_session = TruSession(connector=trulens_snowflake_connection)

            self.tru_agent = TruApp(
                self.agent,
                app_name=app_name,
                app_version=app_version,
            )

        def __call__(self, input):
            with self.tru_agent:
                return self.agent(input)

        async def acall(self, input):
            with self.tru_agent:
                return await self.agent.acall(input)
