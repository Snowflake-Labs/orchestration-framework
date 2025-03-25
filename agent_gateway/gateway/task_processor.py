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

import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.snowflake_tools import SnowflakeError

SCHEDULING_INTERVAL = 0.01  # seconds


class AgentGatewayError(Exception):
    def __init__(self, message):
        self.message = message
        gateway_logger.log("ERROR", self.message)
        super().__init__(self.message)


def _default_stringify_rule_for_arguments(args):
    if len(args) == 1:
        return str(args[0])
    else:
        return str(tuple(args))


def _replace_arg_mask_with_real_value(
    args, dependencies: List[str], tasks: Dict[str, Task]
):
    """
    Recursively replace placeholders $1, $2, etc. with the 'observation' of
    the corresponding tasks in 'tasks', where tasks keys/dependencies are str.
    """
    if isinstance(args, (list, tuple)):
        return type(args)(
            _replace_arg_mask_with_real_value(item, dependencies, tasks)
            for item in args
        )
    elif isinstance(args, str):
        # Sort dependencies by integer value descending, so $12 is replaced before $1
        for dependency in sorted(dependencies, key=int, reverse=True):
            for arg_mask in [f"${{{dependency}}}", f"${dependency}"]:
                if arg_mask in args:
                    if tasks[dependency].observation is not None:
                        args = args.replace(
                            arg_mask, str(tasks[dependency].observation)
                        )
        return args
    else:
        return args


@dataclass
class Task:
    idx: str  # Now a string
    name: str
    tool: Callable
    args: Collection[Any]
    dependencies: Collection[str]  # list of string IDs
    stringify_rule: Optional[Callable] = None
    thought: Optional[str] = None
    observation: Optional[str] = None
    is_fuse: bool = False

    async def __call__(self) -> Any:
        gateway_logger.log("INFO", f"running {self.name} task")
        try:
            x = await self.tool(*self.args)
            gateway_logger.log("DEBUG", "task successfully completed")
            return x
        except SnowflakeError as e:
            return f"Unexpected error during Cortex Gateway Tool request: {str(e)}"
        except Exception as e:
            return f"Unexpected error during Cortex Gateway Tool request: {str(e)}"

    def get_thought_action_observation(
        self, include_action=True, include_thought=True, include_action_idx=False
    ) -> str:
        """
        e.g.
        Thought: ...
        1. search('some query')
        Observation: ...
        """
        thought_action_observation = ""
        if self.thought and include_thought:
            thought_action_observation = f"Thought: {self.thought}\n"

        if include_action:
            # If we want to show something like "1. search('some query')"
            idx_prefix = f"{self.idx}. " if include_action_idx else ""
            if self.stringify_rule:
                # If the user has specified a custom stringify rule
                thought_action_observation += (
                    f"{idx_prefix}{self.stringify_rule(self.args)}\n"
                )
            else:
                # Use the default rule
                thought_action_observation += (
                    f"{idx_prefix}{self.name}"
                    f"{_default_stringify_rule_for_arguments(self.args)}\n"
                )

        if self.observation is not None:
            thought_action_observation += f"Observation: {self.observation}\n"

        return thought_action_observation


class TaskProcessor:
    tasks: Dict[str, Task]
    tasks_done: Dict[str, asyncio.Event]
    remaining_tasks: set[str]

    def __init__(self):
        self.tasks = {}
        self.tasks_done = {}
        self.remaining_tasks = set()

    def set_tasks(self, tasks: dict[str, Task]):
        # tasks is already keyed by string
        self.tasks.update(tasks)
        self.tasks_done.update({task_idx: asyncio.Event() for task_idx in tasks})
        self.remaining_tasks.update(set(tasks.keys()))

    def _all_tasks_done(self):
        return all(self.tasks_done[d].is_set() for d in self.tasks_done)

    def _get_all_executable_tasks(self):
        return [
            task_name
            for task_name in self.remaining_tasks
            if all(
                self.tasks_done[dep].is_set()
                for dep in self.tasks[task_name].dependencies
            )
        ]

    def _preprocess_args(self, task: Task):
        # Replace placeholders in each arg with the actual observation from dependencies
        new_args = []
        for arg in task.args:
            arg = _replace_arg_mask_with_real_value(
                arg, list(task.dependencies), self.tasks
            )
            new_args.append(arg)
        task.args = new_args

    async def _run_task(self, task: Task):
        self._preprocess_args(task)
        if not task.is_fuse:
            try:
                observation = await task()
                task.observation = observation
            except SnowflakeError as e:
                return f"SnowflakeError in task: {str(e)}"
            except Exception as e:
                return f"Unexpected Error in task: {str(e)}"
        self.tasks_done[task.idx].set()

    async def schedule(self):
        """Run all tasks in self.tasks in parallel, respecting dependencies."""
        while not self._all_tasks_done():
            executable_tasks = self._get_all_executable_tasks()

            for task_name in executable_tasks:
                asyncio.create_task(self._run_task(self.tasks[task_name]))
                self.remaining_tasks.remove(task_name)

            await asyncio.sleep(SCHEDULING_INTERVAL)

    async def aschedule(self, task_queue: asyncio.Queue[Optional[Task]], func):
        """Asynchronously listen to task_queue and schedule tasks as they arrive."""
        no_more_tasks = False

        while True:
            if not no_more_tasks:
                task = await task_queue.get()
                if task is None:
                    no_more_tasks = True
                else:
                    self.set_tasks({task.idx: task})

            executable_tasks = self._get_all_executable_tasks()

            if executable_tasks:
                for task_name in executable_tasks:
                    asyncio.create_task(self._run_task(self.tasks[task_name]))
                    self.remaining_tasks.remove(task_name)
            elif no_more_tasks and self._all_tasks_done():
                break
            else:
                await asyncio.sleep(SCHEDULING_INTERVAL)
