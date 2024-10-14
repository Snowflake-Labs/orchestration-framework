import asyncio
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union, cast
import aiohttp
import json
import re

from CortexCube.chains.chain import Chain
from CortexCube.tools.snowflake_analyst_prompts import PLANNER_PROMPT as SNOWFLAKE_PLANNER_PROMPT,OUTPUT_PROMPT
from CortexCube.cube.constants import END_OF_PLAN
from CortexCube.cube.constants import JOINNER_REPLAN
from CortexCube.cube.planner import Planner
from CortexCube.cube.task_fetching_unit import Task, TaskFetchingUnit
from CortexCube.tools.base import StructuredTool, Tool

class CubeAgent:
    """Self defined agent for LLM Compiler."""

    def __init__(self, session,llm) -> None:
        self.llm = llm
        self.session = session
    
    async def arun(self, prompt: str) -> str:
        """Run the LLM."""
        headers,url,data =self._prepare_llm_request(prompt=prompt)

        async with aiohttp.ClientSession(headers=headers,) as session:
            async with session.post(url=url,json=data) as response:
                response_text = await response.text()
                snowflake_response = self._parse_snowflake_response(response_text)
                return snowflake_response

    def _prepare_llm_request(self,prompt):

        headers = {
        "Accept": "text/stream",
        "Content-Type": "application/json",
        "Authorization": f'Snowflake Token="{self.session.connection.rest.token}"'}

        url = f"""https://{self.session.get_current_account().replace('"',"")}.snowflakecomputing.com/api/v2/cortex/inference:complete"""
        data = {"model": self.llm, "messages": [{"content": prompt}]}

        return headers,url,data
    
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

        return completion


class CortexCube(Chain,extra="allow"):
    """Cortex Cube Multi Agent Class"""

    input_key: str = "input"
    output_key: str = "output"

    def __init__(
        self,
        snowpark_session:object,
        tools: list[Union[Tool, StructuredTool]],
        planner_llm: str = "mistral-large2", #replace basellm
        agent_llm: str = "mistral-large2", #replace basellm
        planner_example_prompt: str = SNOWFLAKE_PLANNER_PROMPT,
        planner_example_prompt_replan: Optional[str] = None,
        planner_stop: Optional[list[str]] = [END_OF_PLAN],
        joinner_prompt: str = OUTPUT_PROMPT,
        joinner_prompt_final: Optional[str] = None,
        max_replans: int = 2,
        planner_stream: bool = False,
        **kwargs,
    ) -> None:
        """Parameters

        ----------
        Args:
            snowpark_sesison: authenticated snowflake snowpark connection object
            tools: List of tools to use.
            max_replans: Maximum number of replans to do. Defaults to 2.

        Planner Args:
            planner_llm: Name of Snowflake Cortex LLM to use for planning.
            planner_example_prompt: Example prompt for planning. Defaults to SNOWFLAKE_PLANNER_PROMPT.
            planner_example_prompt_replan: Example prompt for replanning.
                Assign this if you want to use different example prompt for replanning.
                If not assigned, default to `planner_example_prompt`.
            planner_stop: Stop tokens for planning.
            planner_stream: Whether to stream the planning.

        Agent Args:
            agent_llm: Name of Snowflake Cortex LLM to use for planning.
            joinner_prompt: Prompt to use for joinner.
            joinner_prompt_final: Prompt to use for joinner at the final replanning iter.
                If not assigned, default to `joinner_prompt`.
        """        
        super().__init__(name="compiler",**kwargs)

        if not planner_example_prompt_replan:
            # log(
            #     "Replan example prompt not specified, using the same prompt as the planner."
            # )
            planner_example_prompt_replan = planner_example_prompt

        self.planner = Planner(
            session=snowpark_session,
            llm=planner_llm,
            example_prompt=planner_example_prompt,
            example_prompt_replan=planner_example_prompt_replan,
            tools=tools,
            stop=planner_stop,
        )

        self.agent = CubeAgent(session=snowpark_session,llm=agent_llm)
        self.joinner_prompt = joinner_prompt
        self.joinner_prompt_final = joinner_prompt_final or joinner_prompt
        self.planner_stream = planner_stream
        self.max_replans = max_replans

        # callbacks
        self.planner_callback = None
        self.executor_callback = None


    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]
       

    def _parse_joinner_output(self, raw_answer: str) -> str:
        """We expect the joinner output format to be:
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
        thought_pattern = r'Thought: (.*?)\n\n'
        thought_match = re.search(thought_pattern, raw_answer)
        thought = thought_match.group(1) if thought_match else None

        # Extracting the Answer
        answer = self._extract_answer(raw_answer)
        is_replan = True if JOINNER_REPLAN in answer else False

        return thought, answer, is_replan
        
    def _extract_answer(self,raw_answer):
        start_index = raw_answer.find('Action: Finish(')
        replan_index = raw_answer.find('Replan')
        if start_index != -1:
            start_index += len('Action: Finish(')
            parentheses_count = 1
            for i, char in enumerate(raw_answer[start_index:], start_index):
                if char == '(':
                    parentheses_count += 1
                elif char == ')':
                    parentheses_count -= 1
                    if parentheses_count == 0:
                        end_index = i
                        break
            else:
                # If no corresponding closing parenthesis is found
                return None
            answer = raw_answer[start_index:end_index]
            return answer
        else:
            if replan_index != 1:
                print("....replanning...")
                return "Replan required. Consider rephrasing your question."
            else:
                return None

    def _generate_context_for_replanner(
        self, tasks: Mapping[int, Task], joinner_thought: str
    ) -> str:
        """Formatted like this:
        ```
        1. action 1
        Observation: xxx
        2. action 2
        Observation: yyy
        ...
        Thought: joinner_thought
        ```
        """
        previous_plan_and_observations = "\n".join(
            [
                task.get_thought_action_observation(
                    include_action=True, include_action_idx=True
                )
                for task in tasks.values()
                if not task.is_join
            ]
        )
        joinner_thought = f"Thought: {joinner_thought}"
        context = "\n\n".join([previous_plan_and_observations, joinner_thought])
        return context

    def _format_contexts(self, contexts: Sequence[str]) -> str:
        """contexts is a list of context
        each context is formatted as the description of _generate_context_for_replanner
        """
        formatted_contexts = ""
        for context in contexts:
            formatted_contexts += f"Previous Plan:\n\n{context}\n\n"
        formatted_contexts += "Current Plan:\n\n"
        return formatted_contexts

    async def join(
        self, input_query: str, agent_scratchpad: str, is_final: bool
    ) -> str:
        if is_final:
            joinner_prompt = self.joinner_prompt_final
        else:
            joinner_prompt = self.joinner_prompt
        prompt = (
            f"{joinner_prompt}\n"  # Instructions and examples
            f"Question: {input_query}\n\n"  # User input query
            f"{agent_scratchpad}\n"  # T-A-O
            # "---\n"
        )
        #log("Joining prompt:\n", prompt, block=True)
        response = await self.agent.arun(prompt)
        raw_answer = cast(str, response)
        # log("Question: \n", input_query, block=True)
        # log("Raw Answer: \n", raw_answer, block=True)
        thought, answer, is_replan = self._parse_joinner_output(raw_answer)
        if is_final:
            # If final, we don't need to replan
            is_replan = False
        return thought, answer, is_replan

    # TO DO - make synch wrapper
    def _call(
        self,
        inputs: Dict[str, Any]):
        raise NotImplementedError("LLMCompiler is async only.")

    async def acall(
        self,
        input:str
        #inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        contexts = []
        joinner_thought = ""
        agent_scratchpad = ""
        inputs = {'input':input}
        for i in range(self.max_replans):
            is_first_iter = i == 0
            is_final_iter = i == self.max_replans - 1

            task_fetching_unit = TaskFetchingUnit()
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
                await task_fetching_unit.aschedule(
                    task_queue=task_queue, func=lambda x: None
                )
            else:
                tasks = await self.planner.plan(
                    inputs=inputs,
                    is_replan=not is_first_iter,
                    # callbacks=run_manager.get_child() if run_manager else None,
                    callbacks=(
                        [self.planner_callback] if self.planner_callback else None
                    ),
                )
                # log("Graph of tasks: ", tasks, block=True)
                # if self.benchmark:
                #     self.planner_callback.additional_fields["num_tasks"] = len(tasks)
                task_fetching_unit.set_tasks(tasks)
                await task_fetching_unit.schedule()
            tasks = task_fetching_unit.tasks

            # collect thought-action-observation
            agent_scratchpad += "\n\n"
            agent_scratchpad += "".join(
                [
                    task.get_thought_action_observation(
                        include_action=True, include_thought=True
                    )
                    for task in tasks.values()
                    if not task.is_join
                ]
            )
            agent_scratchpad = agent_scratchpad.strip()

            # log("Agent scratchpad:\n", agent_scratchpad, block=True)
            joinner_thought, answer, is_replan = await self.join(
                input,
                agent_scratchpad=agent_scratchpad,
                is_final=is_final_iter,
            )
            if not is_replan:
                # log("Break out of replan loop.")
                break

            # Collect contexts for the subsequent replanner
            context = self._generate_context_for_replanner(
                tasks=tasks, joinner_thought=joinner_thought
            )
            contexts.append(context)
            formatted_contexts = self._format_contexts(contexts)
            # log("Contexts:\n", formatted_contexts, block=True)
            inputs["context"] = formatted_contexts
        # if is_final_iter:
        #     log("Reached max replan limit.")
        return {self.output_key: answer}
    
