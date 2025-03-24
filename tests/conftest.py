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

import os

import pytest
from dotenv import load_dotenv
from snowflake.snowpark import Session

from agent_gateway.tools.utils import generate_demo_services


class TestConf:
    def __init__(self):
        self.session = self.connect()

    def connect(self):
        load_dotenv()
        connection_params = {
            k.replace("SNOWFLAKE_", "").lower(): v
            for k, v in os.environ.items()
            if k.startswith("SNOWFLAKE_") and v.lower() not in ["database", "schema"]
        }
        return Session.builder.configs(connection_params).getOrCreate()


@pytest.fixture(scope="session")
def session():
    conf = TestConf()
    generate_demo_services(conf.session)
    conf.session.use_schema("CUBE_TESTING.PUBLIC")
    yield conf.session
