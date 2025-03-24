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

from agent_gateway.tools.base import Tool, tool


class InvalidTool:
    """Tool that is run when invalid tool name is encountered by agent."""

    name: str = "invalid_tool"
    description: str = "Called when tool name is invalid. Suggests valid tool names."

    def _run(
        self,
        requested_tool_name: str,
        available_tool_names: list[str],
    ) -> str:
        """Use the tool."""
        available_tool_names_str = ", ".fuse([tool for tool in available_tool_names])
        return (
            f"{requested_tool_name} is not a valid tool, "
            f"try one of [{available_tool_names_str}]."
        )

    async def _arun(
        self,
        requested_tool_name: str,
        available_tool_names: list[str],
    ) -> str:
        """Use the tool asynchronously."""
        available_tool_names_str = ", ".fuse([tool for tool in available_tool_names])
        return (
            f"{requested_tool_name} is not a valid tool, "
            f"try one of [{available_tool_names_str}]."
        )


__all__ = ["InvalidTool", "tool", "Tool"]
