# Copyright 2024 Snowflake Inc.
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
from typing import Any, Type, Union

from pydantic import BaseModel
from snowflake.connector.connection import SnowflakeConnection
from snowflake.snowpark import Session
from snowflake.snowpark.functions import col

from agent_gateway.tools.tools import Tool
from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.utils import (
    CortexEndpointBuilder,
    _get_connection,
    post_cortex_request,
)


class SnowflakeError(Exception):
    def __init__(self, message):
        self.message = message
        gateway_logger.log("ERROR", message)
        super().__init__(self.message)


class CortexSearchTool(Tool):
    """Cortex Search tool for use with Snowflake Agent Gateway"""

    k: int = 5
    retrieval_columns: list = []
    service_name: str = ""
    connection: Union[Session, SnowflakeConnection] = None

    def __init__(
        self,
        service_name,
        service_topic,
        data_description,
        retrieval_columns,
        snowflake_connection,
        k=5,
    ):
        """Parameters

        ----------
        service_name (str): name of the Cortex Search Service to utilize
        service_topic (str): description of content indexed by Cortex Search.
        data_description (str): description of the source data that has been indexed.
        retrieval_columns (list): list of columns to include in Cortex Search results.
        snowflake_connection (object): snowpark connection object
        k: number of records to include in results
        """
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
        self.k = k
        self.retrieval_columns = retrieval_columns
        self.service_name = service_name
        gateway_logger.log("INFO", "Cortex Search Tool successfully initialized")

    def __call__(self, question) -> Any:
        return self.asearch(question)

    async def asearch(self, query):
        gateway_logger.log("DEBUG", f"Cortex Search Query:{query}")
        headers, url, data = self._prepare_request(query=query)
        response_text = await post_cortex_request(url=url, headers=headers, data=data)
        response_json = json.loads(response_text)
        gateway_logger.log("DEBUG", f"Cortex Search Response:{response_json}")
        try:
            return response_json["results"]
        except Exception:
            raise SnowflakeError(message=response_json["message"])

    def _prepare_request(self, query):
        eb = CortexEndpointBuilder(self.connection)
        headers = eb.get_search_headers()
        url = eb.get_search_endpoint(
            self.connection.database,
            self.connection.schema,
            self.service_name,
        )

        data = {
            "query": query,
            "columns": self.retrieval_columns,
            "limit": self.k,
        }

        return headers, url, data

    def _prepare_search_description(self, name, service_topic, data_source_description):
        base_description = f""""{name}(query: str) -> list:\n
                 - Executes a search for relevant information about {service_topic}.\n
                 - Returns a list of relevant passages from {data_source_description}.\n"""

        return base_description

    def _get_search_attributes(self, search_service_name):
        snowflake_connection = Session.builder.config("connection", self.connection)
        df = snowflake_connection.sql("SHOW CORTEX SEARCH SERVICES")
        raw_atts = (
            df.where(col('"name"') == search_service_name)
            .select('"attribute_columns"')
            .to_pandas()
            .loc[0]
            .values[0]
        )
        attribute_list = raw_atts.split(",")

        return attribute_list

    def _get_search_table(self, search_service_name):
        snowflake_connection = Session.builder.config("connection", self.connection)
        df = snowflake_connection.sql("SHOW CORTEX SEARCH SERVICES")
        table_def = (
            df.where(col('"name"') == search_service_name)
            .select('"definition"')
            .to_pandas()
            .loc[0]
            .values[0]
        )

        pattern = r"FROM\s+([\w\.]+)"
        if match := re.search(pattern, table_def):
            return match[1]
        else:
            print("No match found.")

        return table_def

    def _get_sample_values(
        self, snowflake_connection, cortex_search_service, max_samples=10
    ):
        sample_values = {}
        attributes = self._get_search_attributes(
            snowflake_connection=snowflake_connection,
            search_service_name=cortex_search_service,
        )
        table_name = self._get_search_table(
            snowflake_connection=snowflake_connection,
            search_service_name=cortex_search_service,
        )

        for attribute in attributes:
            query = f"""SELECT DISTINCT({attribute}) FROM {table_name} LIMIT {max_samples}"""
            sample_values[attribute] = list(
                snowflake_connection.sql(query).to_pandas()[attribute].values
            )

        return attributes, sample_values


def get_min_length(model: Type[BaseModel]):
    min_length = 0
    for key, field in model.model_fields.items():
        if issubclass(field.annotation, BaseModel):
            min_length += get_min_length(field.annotation)
        min_length += len(key)
    return min_length


class CortexAnalystTool(Tool):
    """""Cortex Analyst tool for use with Snowflake Agent Gateway""" ""

    STAGE: str = ""
    FILE: str = ""
    connection: Union[Session, SnowflakeConnection] = None

    def __init__(
        self,
        semantic_model,
        stage,
        service_topic,
        data_description,
        snowflake_connection,
    ):
        """Parameters

        ----------
        semantic_model (str): yaml file name containing semantic model for Cortex Analyst
        stage (str): name of stage containing semantic model yaml.
        service_topic (str): topic of the data in the tables (i.e S&P500 company financials).
        data_description (str): description of the source data that has been indexed (i.e a table with stock and financial metrics about S&P500 companies).
        snowflake_connection (object): snowpark connection object
        """
        tname = semantic_model.replace(".yaml", "") + "_" + "cortexanalyst"
        tool_description = self._prepare_analyst_description(
            name=tname,
            service_topic=service_topic,
            data_source_description=data_description,
        )

        super().__init__(name=tname, func=self.asearch, description=tool_description)
        self.connection = _get_connection(snowflake_connection)
        self.FILE = semantic_model
        self.STAGE = stage

        gateway_logger.log("INFO", "Cortex Analyst Tool successfully initialized")

    def __call__(self, prompt) -> Any:
        return self.asearch(query=prompt)

    async def asearch(self, query):
        gateway_logger.log("DEBUG", f"Cortex Analyst Prompt:{query}")

        url, headers, data = self._prepare_analyst_request(prompt=query)

        response_text = await post_cortex_request(url=url, headers=headers, data=data)
        json_response = json.loads(response_text)

        gateway_logger.log("DEBUG", f"Cortex Analyst Raw Response:{json_response}")

        try:
            query_response = self._process_analyst_message(
                json_response["message"]["content"]
            )
        except Exception:
            raise SnowflakeError(message=json_response["message"])

        return query_response

    def _prepare_analyst_request(self, prompt):
        data = {
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
            "semantic_model_file": f"@{self.connection.database}.{self.connection.schema}.{self.STAGE}/{self.FILE}",
        }

        eb = CortexEndpointBuilder(self.connection)
        headers = eb.get_analyst_headers()
        url = eb.get_analyst_endpoint()

        return url, headers, data

    def _process_analyst_message(self, response):
        if isinstance(response, list) and len(response) > 0:
            first_item = response[0]

            if "type" in first_item:
                if first_item["type"] == "text":
                    _ = None
                    for item in response:
                        _ = item
                        if item["type"] == "suggestions":
                            raise SnowflakeError(
                                message=f"Your request is unclear. Consider rephrasing your request to one of the following suggestions:{item['suggestions']}"
                            )
                        elif item["type"] == "sql":
                            sql_query = item["statement"]
                            table = (
                                self.connection.cursor()
                                .execute(sql_query)
                                .fetch_arrow_all()
                            )

                            if table is not None:
                                return str(table.to_pydict())
                            else:
                                raise SnowflakeError(
                                    message="No results found. Consider rephrasing your request"
                                )

                    raise SnowflakeError(
                        message=f"Unable to generate a valid SQL Query. {_['text']}"
                    )

        return SnowflakeError(message="Invalid Cortex Analyst Response")

    def _prepare_analyst_description(
        self, name, service_topic, data_source_description
    ):
        base_analyst_description = f"""{name}(prompt: str) -> str:\n
                  - takes a user's question about {service_topic} and queries {data_source_description}\n
                  - Returns the relevant metrics about {service_topic}\n"""

        return base_analyst_description


class PythonTool(Tool):
    def __init__(self, python_func, tool_description, output_description) -> None:
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
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, sync_func, *args, **kwargs)

        return async_func

    def _generate_description(self, python_func, tool_description, output_description):
        full_sig = self._process_full_signature(python_func=python_func)
        return f"""{full_sig}\n - {tool_description}\n - {output_description}"""

    def _process_full_signature(self, python_func):
        name = python_func.__name__
        signature = str(inspect.signature(python_func))
        return name + signature
