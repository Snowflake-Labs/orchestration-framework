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
import inspect
import json
import re
from typing import Any, Dict, List, Type, Union

import pandas as pd
from pydantic import BaseModel
from snowflake.connector import DictCursor
from snowflake.connector.connection import SnowflakeConnection
from snowflake.snowpark import Session

from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.tools import Tool
from agent_gateway.tools.utils import (
    _get_connection,
    get_tag,
)

from xetroc import analyst, search


class SnowflakeError(Exception):
    def __init__(self, message: str):
        self.message = message
        gateway_logger.log("ERROR", message)
        super().__init__(self.message)


class CortexSearchTool(Tool):
    """Cortex Search tool for use with Snowflake Agent Gateway"""

    k: int = 5
    retrieval_columns: List[str] = []
    service_name: str = ""
    connection: Union[Session, SnowflakeConnection] = None

    def __init__(
        self,
        service_name: str,
        service_topic: str,
        data_description: str,
        retrieval_columns: List[str],
        snowflake_connection: Union[Session, SnowflakeConnection],
        k: int = 5,
    ):
        """Initialize CortexSearchTool with parameters."""
        tool_name = f"{service_name.lower()}_cortexsearch"
        tool_description = self._prepare_search_description(
            name=tool_name,
            service_topic=service_topic,
            data_source_description=data_description,
        )
        super().__init__(
            name=tool_name, description=tool_description, func=self.asearch
        )
        self.connection = _get_connection(snowflake_connection)
        self.connection.cursor().execute(
            f"alter session set query_tag='{get_tag('CortexSearchTool')}'"
        )
        self.k = k
        self.retrieval_columns = retrieval_columns
        self.service_name = service_name
        gateway_logger.log("INFO", "Cortex Search Tool successfully initialized")

    def __call__(self, question: str) -> Any:
        return self.asearch(question)

    async def asearch(self, query: str) -> Dict[str, Any]:
        gateway_logger.log("DEBUG", f"Cortex Search Query: {query}")

        search_response = search(
            con=self.connection,
            service_name=self.service_name,
            prompt=query,
            columns=self.retrieval_columns,
            limit=self.k,
        )

        search_col = self._get_search_column(self.service_name)
        citations = self._get_citations(search_response["results"], search_col)

        gateway_logger.log("DEBUG", f"Cortex Search Response: {search_response}")

        return {
            "output": search_response,
            "sources": {
                "tool_type": "cortex_search",
                "tool_name": self.name,
                "metadata": citations,
            },
        }

    def _get_citations(
        self, raw_response: List[Dict[str, Any]], search_column: List[str]
    ) -> List[Dict[str, Any]]:
        citation_elements = [
            {k: v for k, v in d.items() if k and k not in search_column}
            for d in raw_response
        ]

        if len(citation_elements[0].keys()) < 1:
            return [{"Search Tool": self.service_name}]

        seen = set()
        citations = []
        for c in citation_elements:
            identifier = tuple(sorted(c.items()))
            if identifier not in seen:
                seen.add(identifier)
                citations.append(c)

        return citations

    def _prepare_search_description(
        self, name: str, service_topic: str, data_source_description: str
    ) -> str:
        return (
            f""""{name}(query: str) -> list:\n"""
            f""" - Executes a search for relevant information about {service_topic}.\n"""
            f""" - Returns a list of relevant passages from {data_source_description}.\n"""
        )

    def _get_search_column(self, search_service_name: str) -> List[str]:
        column = self._get_search_service_attribute(
            search_service_name, "search_column"
        )
        if column is not None:
            return column
        else:
            raise SnowflakeError(
                message="unable to identify index column in Cortex Search"
            )

    def _get_search_service_attribute(
        self, search_service_name: str, attribute: str
    ) -> list[str]:
        df = (
            self.connection.cursor(cursor_class=DictCursor)
            .execute("SHOW CORTEX SEARCH SERVICES")
            .fetchall()
        )
        df = pd.DataFrame(df)

        if not df.empty:
            raw_atts = df.loc[df["name"] == search_service_name, attribute].iloc[0]
            return raw_atts.split(",")
        else:
            return None

    def _get_search_table(self, search_service_name: str) -> str:
        df = (
            self.connection.cursor(cursor_class=DictCursor)
            .execute("SHOW CORTEX SEARCH SERVICES")
            .fetch_pandas_all()
        )
        df = pd.DataFrame(df)
        table_def = df.loc[df["name"] == search_service_name, "definition"].iloc[0]
        pattern = r"FROM\s+([\w\.]+)"
        match = re.search(pattern, table_def)
        return match[1] if match else "No match found."


def get_min_length(model: Type[BaseModel]) -> int:
    min_length = 0
    for key, field in model.model_fields.items():
        if issubclass(field.annotation, BaseModel):
            min_length += get_min_length(field.annotation)
        min_length += len(key)
    return min_length


class CortexAnalystTool(Tool):
    """Cortex Analyst tool for use with Snowflake Agent Gateway"""

    STAGE: str = ""
    FILE: str = ""
    connection: Union[Session, SnowflakeConnection] = None

    def __init__(
        self,
        semantic_model: str,
        stage: str,
        service_topic: str,
        data_description: str,
        snowflake_connection: Union[Session, SnowflakeConnection],
    ):
        """Initialize CortexAnalystTool with parameters."""
        tname = semantic_model.replace(".yaml", "") + "_" + "cortexanalyst"
        tool_description = self._prepare_analyst_description(
            name=tname,
            service_topic=service_topic,
            data_source_description=data_description,
        )

        super().__init__(name=tname, func=self.asearch, description=tool_description)
        self.connection = _get_connection(snowflake_connection)
        self.connection.cursor().execute(
            f"alter session set query_tag='{get_tag('CortexAnalystTool')}'"
        )
        self.FILE = semantic_model
        self.STAGE = stage

        gateway_logger.log("INFO", "Cortex Analyst Tool successfully initialized")

    def __call__(self, prompt: str) -> Any:
        return self.asearch(query=prompt)

    async def asearch(self, query: str) -> Dict[str, Any]:
        gateway_logger.log("DEBUG", f"Cortex Analyst Prompt: {query}")
        semantic_model = f"@{self.connection.database}.{self.connection.schema}.{self.STAGE}/{self.FILE}"
        response = analyst(
            con=self.connection, semantic_model_file=semantic_model, prompt=query
        )

        try:
            content = json.loads(response["message"])
            analyst_response = self._process_analyst_message(content["content"])
            return analyst_response
        except KeyError:
            raise SnowflakeError(message=response.get("message", "Unknown error"))

    def _process_analyst_message(
        self, response: list[dict[str, Any]]
    ) -> Dict[str, Any]:
        if response and isinstance(response, list):
            gateway_logger.log("DEBUG", response)
            sql_exists = any(item.get("type") == "sql" for item in response)

            for item in response:
                if item["type"] == "sql":
                    sql_query = item["statement"]
                    table = (
                        self.connection.cursor().execute(sql_query).fetch_arrow_all()
                    )

                    if table:
                        tables = self._extract_tables(sql_query)
                        return {
                            "output": str(table.to_pydict()),
                            "sources": {
                                "tool_type": "cortex_analyst",
                                "tool_name": self.name,
                                "metadata": tables,
                            },
                        }
                elif sql_exists:
                    continue
                else:
                    try:
                        response = (
                            str(
                                response[0]["text"]
                                + " Consider rephrasing your request to one of the following:"
                                + str(item["suggestions"])
                            ),
                        )
                    except KeyError:
                        response = str(
                            response[0]["text"] + " Consider rephrasing your request"
                        )

                    return {
                        "output": response,
                        "sources": {
                            "tool_type": "cortex_analyst",
                            "tool_name": self.name,
                            "metadata": {"Table": None},
                        },
                    }

            raise SnowflakeError(
                message=f"Unable to parse Cortex Analyst response: {response[0]['text']}"
            )

        raise SnowflakeError(message="Invalid Cortex Analyst Response")

    def _prepare_analyst_description(
        self, name: str, service_topic: str, data_source_description: str
    ) -> str:
        return (
            f"""{name}(prompt: str) -> str:\n"""
            f""" - takes a user's question about {service_topic} and queries {data_source_description}\n"""
            f""" - Returns the relevant metrics about {service_topic}\n"""
        )

    def _extract_tables(self, sql: str) -> List[str]:
        cleaned_sql = re.sub(r"--.*", "", sql)  # Strip line comments
        cleaned_sql = re.sub(
            r"/\*.*?\*/", "", cleaned_sql, flags=re.DOTALL
        )  # Strip block comments

        cte_names = set()
        if re.search(r"^\s*WITH\s+", cleaned_sql, re.IGNORECASE | re.MULTILINE):
            cte_matches = re.findall(
                r"\b(\w+)\s+AS\s*\(", cleaned_sql, re.IGNORECASE | re.DOTALL
            )
            cte_names.update(cte_matches)

        from_tables = re.findall(r"\bFROM\s+([^\s\(\)\,]+)", cleaned_sql, re.IGNORECASE)
        tables = [{"Table": table} for table in from_tables if table not in cte_names]
        return tables


class PythonTool(Tool):
    def __init__(
        self, python_func: callable, tool_description: str, output_description: str
    ) -> None:
        self.python_callable = self.asyncify(python_func)
        self.desc = self._generate_description(
            python_func=python_func,
            tool_description=tool_description,
            output_description=output_description,
        )
        super().__init__(
            name=python_func.__name__, func=self.python_callable, description=self.desc
        )
        gateway_logger.log("INFO", "Python Tool successfully initialized")

    def __call__(self, *args):
        return self.python_callable(*args)

    def asyncify(self, sync_func):
        async def async_func(*args, **kwargs):
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, sync_func, *args, **kwargs)
            return {
                "output": result,
                "sources": {
                    "tool_type": "custom_tool",
                    "tool_name": sync_func.__name__,
                    "metadata": None,
                },
            }

        return async_func

    def _generate_description(
        self, python_func: callable, tool_description: str, output_description: str
    ) -> str:
        full_sig = self._process_full_signature(python_func=python_func)
        return f"""{full_sig}\n - {tool_description}\n - {output_description}"""

    def _process_full_signature(self, python_func: callable) -> str:
        name = python_func.__name__
        signature = str(inspect.signature(python_func))
        return name + signature
