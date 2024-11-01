import ast
import re
from typing import Any, Sequence, Tuple, Union

from langchain.schema import OutputParserException

from CortexCube.cube.task_processor import Task
from CortexCube.tools.base import StructuredTool, Tool

THOUGHT_PATTERN = r"Thought: ([^\n]*)"
# ACTION_PATTERN = r"\n*(\d+)\. (\w+)\((.*)\)(\s*#\w+\n)?"
ACTION_PATTERN = r"\n*(\d+)\. (\w+)\((.*?)\)(\s*#\w+\n)?"
# $1 or ${1} -> 1
ID_PATTERN = r"\$\{?(\d+)\}?"

END_OF_PLAN = "<END_OF_PLAN>"


def default_dependency_rule(idx, args: str):
    matches = re.findall(ID_PATTERN, args)
    numbers = [int(match) for match in matches]
    return idx in numbers


class CubePlanParser:
    """Planning output parser."""

    def __init__(self, tools: Sequence[Union[Tool, StructuredTool]], **kwargs):
        super().__init__(**kwargs)
        self.tools = tools

    def parse(self, text: str) -> list[str]:
        # 1. search("Ronaldo number of kids") -> 1, "search", '"Ronaldo number of kids"'
        # pattern = r"(\d+)\. (\w+)\(([^)]+)\)"
        pattern = rf"(?:{THOUGHT_PATTERN}\n)?{ACTION_PATTERN}"
        # matches = re.findall(pattern, text)
        matches = re.findall(pattern, text, re.DOTALL)

        graph_dict = {}

        for match in matches:
            # idx = 1, function = "search", args = "Ronaldo number of kids"
            # thought will be the preceding thought, if any, otherwise an empty string
            thought, idx, tool_name, args, _ = match
            idx = int(idx)

            task = instantiate_task(
                tools=self.tools,
                idx=idx,
                tool_name=tool_name,
                args=args,
                thought=thought,
            )

            graph_dict[idx] = task
            if task.is_join:
                break

        return graph_dict


### Helper functions


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
    raise OutputParserException(f"Tool {tool_name} not found.")


def _get_dependencies_from_graph(
    idx: int, tool_name: str, args: Sequence[Any]
) -> dict[str, list[str]]:
    """Get dependencies from a graph."""
    if tool_name == "join":
        # depends on the previous step
        dependencies = list(range(1, idx))
    else:
        # define dependencies based on the dependency rule in tool_definitions.py
        dependencies = [i for i in range(1, idx) if default_dependency_rule(i, args)]

    return dependencies


def instantiate_task(
    tools: Sequence[Union[Tool, StructuredTool]],
    idx: int,
    tool_name: str,
    args: str,
    thought: str,
) -> Task:
    dependencies = _get_dependencies_from_graph(idx, tool_name, args)
    args = _parse_llm_compiler_action_args(args)
    if tool_name == "join":
        # join does not have a tool
        tool_func = lambda x: None
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
        is_join=tool_name == "join",
    )
