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
import re
from collections.abc import Sequence
from typing import Any, Tuple, Union

from agent_gateway.gateway.task_processor import Task
from agent_gateway.tools.base import StructuredTool, Tool
from agent_gateway.tools.logger import gateway_logger

THOUGHT_PATTERN = r"Thought: ([^\n]*)"
ACTION_PATTERN = r"\n*(\d+)\. (\w+)\((.*?)\)(\s*#\w+\n)?"
ID_PATTERN = r"\$\{?(\d+)\}?"


class AgentGatewayError(Exception):
    def __init__(self, message):
        self.message = message
        gateway_logger.log("ERROR", self.message)
        super().__init__(self.message)


def default_dependency_rule(idx, args: str):
    matches = re.findall(ID_PATTERN, args)
    numbers = [int(match) for match in matches]
    return idx in numbers


class GatewayPlanParser:
    """Planning output parser."""

    def __init__(self, tools: Sequence[Union[Tool, StructuredTool]], **kwargs):
        super().__init__(**kwargs)
        self.tools = tools

    def parse(self, text: str) -> list[str]:
        pattern = rf"(?:{THOUGHT_PATTERN}\n)?{ACTION_PATTERN}"
        matches = re.findall(pattern, text, re.DOTALL)
        final_matches = _update_task_list_with_summarization(matches)

        graph_dict = {}

        for match in final_matches:
            # idx = 1, function = "search", args = "Ronaldo number of kids"
            # thought will be the preceding thought, if any, otherwise an empty string
            thought, idx, tool_name, args, _ = match

            task = instantiate_task(
                tools=self.tools,
                idx=idx,
                tool_name=tool_name,
                args=args,
                thought=thought,
            )

            graph_dict[idx] = task
            if task.is_fuse:
                break

        return graph_dict


### Helper functions
def _initialize_task_list(matches):
    new_matches = []
    new_match_idx = []
    current_index = 1
    index_mapping = {}

    for i, task in enumerate(matches):
        index_mapping[task[1]] = str(current_index)
        updated_task = (task[0], str(current_index), task[2], task[3])
        new_matches.append(updated_task)
        next_task_contains_ref = (
            _check_ref(matches[i + 1][3]) if i + 1 < len(matches) else False
        )

        if "cortexsearch" in task[2] and next_task_contains_ref:
            new_step = _create_summarization_step(task[3], current_index)
            new_matches.append(new_step)
            new_match_idx.append(new_step[1])
            current_index += 1
            index_mapping[task[1]] = str(current_index)

        current_index += 1

    return new_matches, index_mapping, new_match_idx


def _check_ref(string):
    try:
        pattern = r"\$\d+"
        match = re.search(pattern, string)
        return bool(match)
    except Exception:
        return False


def _create_summarization_step(context, index):
    summarization_prompt = f"Concisely give me {context} ONLY using the following context: ${index}. DO NOT include any other rationale."
    return (
        "I need to concisely summarize the cortex search output",
        str(index + 1),
        "summarize",
        summarization_prompt,
        "",
    )


def _update_task_references(task, index_mapping, new_match_ids):
    if task[1] in new_match_ids:
        return task
    else:
        updated_string = task[3]
        updated_string = re.sub(
            r"\$(\d+)",
            lambda m: f"${index_mapping.get(m.group(1), m.group(1))}",
            updated_string,
        )
        return (task[0], task[1], task[2], updated_string, "")


def _update_task_list_with_summarization(matches):
    new_matches, index_mapping, new_match_ids = _initialize_task_list(matches)
    updated_final_matches = [
        _update_task_references(task, index_mapping, new_match_ids)
        for task in new_matches
    ]
    return updated_final_matches


def _parse_llm_compiler_action_args(args: str) -> Union[Tuple[Any, ...], Tuple[str]]:
    """Parse arguments from a string."""
    args = args.strip()

    # Remove leading/trailing quotes if present
    if (args.startswith('"') and args.endswith('"')) or (
        args.startswith("'") and args.endswith("'")
    ):
        args = args[1:-1]

    if "\n" in args:
        args = f'"""{args}"""'

    if args == "":
        return ()

    try:
        parsed_args = ast.literal_eval(args)
        if not isinstance(parsed_args, (list, tuple)):
            return (parsed_args,)
        return tuple(parsed_args)
    except (ValueError, SyntaxError):
        # If literal_eval fails, return the original string as a single-element tuple
        return (args,)


def _find_tool(
    tool_name: str, tools: Sequence[Union[Tool, StructuredTool]]
) -> Union[Tool, StructuredTool]:
    """Find a tool by name.

    Args:
        tool_name: Name of the tool to find.

    Returns:
        Tool or StructuredTool.

    """
    for tool in tools:
        if tool.name == tool_name:
            return tool
    raise AgentGatewayError(message=f"Tool {tool_name} not found.")


def _get_dependencies_from_graph(
    idx: int, tool_name: str, args: Sequence[Any]
) -> dict[str, list[str]]:
    """Get dependencies from a graph."""
    int_idx = int(idx)  # parse it so we can do numeric range
    if tool_name == "fuse":
        # depends on all previous step IDs
        dependencies = list(range(1, int_idx))
    else:
        dependencies = [
            i for i in range(1, int_idx) if default_dependency_rule(i, str(args))
        ]

    # Convert each numeric dependency to a string
    return [str(d) for d in dependencies]


def instantiate_task(
    tools: Sequence[Union[Tool, StructuredTool]],
    idx: str,
    tool_name: str,
    args: str,
    thought: str,
) -> Task:
    dependencies = _get_dependencies_from_graph(idx, tool_name, args)
    args = _parse_llm_compiler_action_args(args)
    if tool_name == "fuse":
        # fuse does not have a tool
        tool_func = lambda x: None  # noqa: E731
        stringify_rule = None
    else:
        tool = _find_tool(tool_name, tools)
        tool_func = tool.func
        stringify_rule = tool.stringify_rule
    return Task(
        idx=idx,
        name=tool_name,
        tool=tool_func,
        args=args,
        dependencies=dependencies,
        stringify_rule=stringify_rule,
        thought=thought,
        is_fuse=tool_name == "fuse",
    )
