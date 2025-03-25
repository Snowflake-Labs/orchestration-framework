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
from agent_gateway.gateway.gateway import Agent
from agent_gateway.tools.utils import _should_instrument

__all__ = ["Agent", "TruAgent"]


def __getattr__(name):
    if name == "TruAgent":
        if not _should_instrument():
            raise ImportError(
                "TruAgent requires trulens and trulens_connectors_snowflake. "
                "Install with: pip install trulens>=1.4.5 trulens-connectors-snowflake"
            )
        from agent_gateway.gateway.gateway import TruAgent

        return TruAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
