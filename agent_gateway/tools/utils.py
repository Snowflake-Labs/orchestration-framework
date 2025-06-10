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
import io
import json
from collections import deque
from textwrap import dedent
from typing import TypedDict, Union
from urllib.parse import urlunparse
import importlib

import aiohttp
import pkg_resources
from snowflake.connector.connection import SnowflakeConnection
from snowflake.snowpark import Session


def _get_connection(
    connection: Union[Session, SnowflakeConnection],
) -> SnowflakeConnection:
    if isinstance(connection, Session):
        return getattr(connection, "connection")
    return connection


class Headers(TypedDict):
    Accept: str
    Content_Type: str
    Authorization: str


def _determine_runtime():
    try:
        from _stored_proc_restful import StoredProcRestful  # noqa: F401

        return True
    except ImportError:
        return False


def _should_instrument():
    required_packages = ["trulens", "trulens.connectors.snowflake"]
    return all(
        importlib.util.find_spec(package) is not None for package in required_packages
    )


class CortexEndpointBuilder:
    def __init__(self, connection: Union[Session, SnowflakeConnection]):
        self.connection = _get_connection(connection)
        self.BASE_URL = self._set_base_url()
        self.inside_snowflake = _determine_runtime()
        self.BASE_HEADERS = self._set_base_headers()

    def _set_base_url(self):
        con = self.connection
        scheme = con.scheme if hasattr(con, "scheme") else "https"
        host = con.host
        host = host.replace("_", "-")
        host = host.lower()
        url = urlunparse((scheme, host, "", "", "", ""))
        return url

    def _set_base_headers(self):
        if self.inside_snowflake:
            token = None
        else:
            token = self.connection.rest.token
        return {
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{token}"',
        }

    def get_complete_endpoint(self):
        URL_SUFFIX = "/api/v2/cortex/inference:complete"
        if self.inside_snowflake:
            return URL_SUFFIX
        return f"{self.BASE_URL}{URL_SUFFIX}"

    def get_analyst_endpoint(self):
        URL_SUFFIX = "/api/v2/cortex/analyst/message"
        if self.inside_snowflake:
            return URL_SUFFIX
        return f"{self.BASE_URL}{URL_SUFFIX}"

    def get_search_endpoint(self, database, schema, service_name):
        URL_SUFFIX = f"/api/v2/databases/{database}/schemas/{schema}/cortex-search-services/{service_name}:query"
        URL_SUFFIX = URL_SUFFIX.lower()
        if self.inside_snowflake:
            return URL_SUFFIX
        return f"{self.BASE_URL}{URL_SUFFIX}"

    def get_complete_headers(self) -> Headers:
        return self.BASE_HEADERS | {"Accept": "application/json"}

    def get_analyst_headers(self) -> Headers:
        return self.BASE_HEADERS

    def get_search_headers(self) -> Headers:
        return self.BASE_HEADERS | {"Accept": "application/json"}


async def post_cortex_request(url: str, headers: Headers, data: dict):
    """Submit cortex request depending on runtime"""

    if _determine_runtime():
        import _snowflake

        resp = _snowflake.send_snow_api_request(
            "POST",
            url,
            {},
            {},
            data,
            {},
            30000,
        )

        return json.dumps(resp)
    else:
        async with aiohttp.ClientSession(
            headers=headers,
        ) as session:
            async with session.post(url=url, json=data) as response:
                return await response.text()


def asyncify(self, sync_func):
    async def async_func(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, sync_func, *args, **kwargs)

    return async_func


def parse_log_message(log_message):
    # Split the log message to extract the relevant part
    parts = log_message.split(" - ")
    if len(parts) >= 4:
        task_info = parts[3]
        # Check if the log message contains 'running' and 'task'
        if "running" in task_info and "task" in task_info:
            start = task_info.find("running") + len("running")
            end = task_info.find("task")
            tool_name = task_info[start:end].strip().replace("_", " ").upper()

            # Determine tool type
            if "CORTEXANALYST" in tool_name:
                tool_type = "Cortex Analyst"
                tool_name = tool_name.replace("CORTEXANALYST", "")
            elif "CORTEXSEARCH" in tool_name:
                tool_type = "Cortex Search"
                tool_name = tool_name.replace("CORTEXSEARCH", "")
            else:
                tool_type = "Python"

            return f"Running {tool_name} {tool_type} Tool..."

        elif "Replanning" in task_info:
            return "Replanning..."


def generate_demo_services(session: Session) -> str:
    # Snowflake changes context after creation of a database or schema. This can cause
    # issues when creating objects in the newly created database or schema. To avoid this,
    # we store the initial context and reset it after creating the objects.
    initial_context = session.get_fully_qualified_current_schema()
    setup_objects = io.StringIO(
        dedent(
            """
        CREATE DATABASE IF NOT EXISTS CUBE_TESTING;
        CREATE WAREHOUSE IF NOT EXISTS CUBE_TESTING
            WAREHOUSE_SIZE = 'XSMALL'
            AUTO_SUSPEND = 60;
        CREATE STAGE IF NOT EXISTS CUBE_TESTING.PUBLIC.ANALYST;
        CREATE STAGE IF NOT EXISTS CUBE_TESTING.PUBLIC.DATA;
        CREATE TABLE IF NOT EXISTS CUBE_TESTING.PUBLIC.SEC_CHUNK_SEARCH (
            RELATIVE_PATH VARCHAR,
            CHUNK VARCHAR
        );
        CREATE TABLE IF NOT EXISTS CUBE_TESTING.PUBLIC.SP500 (
            EXCHANGE VARCHAR,
            SYMBOL VARCHAR,
            SHORTNAME VARCHAR,
            LONGNAME VARCHAR,
            SECTOR VARCHAR,
            INDUSTRY VARCHAR,
            CURRENTPRICE NUMBER(38,3),
            MARKETCAP NUMBER(38,0),
            EBITDA NUMBER(38,0),
            REVENUEGROWTH NUMBER(38,3),
            CITY VARCHAR,
            STATE VARCHAR,
            COUNTRY VARCHAR,
            FULLTIMEEMPLOYEES NUMBER(38,0),
            LONGBUSINESSSUMMARY VARCHAR,
            WEIGHT NUMBER(38,20)
        );
        """
        )
    )
    copy_into = io.StringIO(
        dedent(
            """
    COPY INTO CUBE_TESTING.PUBLIC.SEC_CHUNK_SEARCH
    FROM @CUBE_TESTING.PUBLIC.DATA/sec_chunk_search.parquet
    FILE_FORMAT = (TYPE = PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

    COPY INTO CUBE_TESTING.PUBLIC.SP500
    FROM @CUBE_TESTING.PUBLIC.DATA/sp500.parquet
    FILE_FORMAT = (TYPE = PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;
    """
        )
    )
    con = session.connection
    deque(con.execute_stream(setup_objects), maxlen=0)
    session.file.put_stream(
        pkg_resources.resource_stream(__name__, "data/sp500_semantic_model.yaml"),
        "CUBE_TESTING.PUBLIC.ANALYST/sp500_semantic_model.yaml",
        auto_compress=False,
        overwrite=True,
    )
    session.file.put_stream(
        pkg_resources.resource_stream(__name__, "data/sec_chunk_search.parquet"),
        "CUBE_TESTING.PUBLIC.DATA/sec_chunk_search.parquet",
    )
    session.file.put_stream(
        pkg_resources.resource_stream(__name__, "data/sp500.parquet"),
        "CUBE_TESTING.PUBLIC.DATA/sp500.parquet",
    )
    deque(con.execute_stream(copy_into), maxlen=0)
    con.cursor().execute(
        dedent(
            """
    CREATE CORTEX SEARCH SERVICE IF NOT EXISTS CUBE_TESTING.PUBLIC.SEC_SEARCH_SERVICE
    ON CHUNK
    attributes RELATIVE_PATH
    warehouse='CUBE_TESTING'
    target_lag='DOWNSTREAM'
    AS (
    SELECT
        RELATIVE_PATH,
        CHUNK
    FROM SEC_CHUNK_SEARCH
    );
    """
        )
    )
    session.use_schema(initial_context)
    return "Demo services created successfully."


def teardown_demo_services(session: Session) -> str:
    teardown_objects = io.StringIO(
        dedent(
            """
        DROP DATABASE IF EXISTS CUBE_TESTING;
        DROP WAREHOUSE IF EXISTS CUBE_TESTING;
        """
        )
    )
    con = session.connection
    deque(con.execute_stream(teardown_objects), maxlen=0)
    return "Demo objects have been dropped."


def get_tag() -> str:
    query_tag = {
        "origin": "sf_sit",
        "name": "orchestration-framework",
        "version": {"major": 1, "minor": 0},
    }
    return json.dumps(query_tag)


def _set_logging(connection: SnowflakeConnection):
    try:
        tag_fn_query = """CREATE OR REPLACE PROCEDURE set_query_tag(tag STRING)
        RETURNS STRING
        LANGUAGE SQL
        EXECUTE AS CALLER
        AS
        $$
        BEGIN
            EXECUTE IMMEDIATE 'ALTER SESSION SET QUERY_TAG = '''||tag||'''';
            SELECT 1;
            RETURN 'Gateway logger setup successfully';
        END;
        $$;"""
        connection.cursor().execute(tag_fn_query)
    except Exception:
        pass


def set_tag(connection):
    con = _get_connection(connection)
    set_query = f"CALL set_query_tag('{get_tag()}')"
    try:
        con.cursor().execute(set_query)
    except Exception:
        try:
            _set_logging(con)
            con.cursor().execute(set_query)
        except Exception:
            pass
