from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any, Dict, List, Type, Union, ClassVar
import pandas as pd

from pydantic import BaseModel, create_model
from snowflake.connector.connection import SnowflakeConnection
from snowflake.connector import DictCursor
from snowflake.snowpark import Session

from agent_gateway.tools.logger import gateway_logger
from agent_gateway.tools.tools import Tool
from agent_gateway.tools.utils import (
    CortexEndpointBuilder,
    _get_connection,
    post_cortex_request,
    _determine_runtime,
)

from functools import partial
from inspect import signature


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
    asearch: ClassVar[Any]

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

        def search_call(query: str):
            return self.asearch(query)

        super().__init__(name=tool_name, description=tool_description, func=search_call)
        self.connection = _get_connection(snowflake_connection)
        self.k = k
        self.retrieval_columns = retrieval_columns
        self.service_name = service_name
        gateway_logger.log("INFO", "Cortex Search Tool successfully initialized")

    def __call__(self, question) -> Any:
        return self.asearch(question)

    async def asearch(self, query: str) -> Dict[str, Any]:
        gateway_logger.log("DEBUG", f"Cortex Search Query: {query}")
        headers, url, data = self._prepare_request(query=query)
        response_text = await post_cortex_request(url=url, headers=headers, data=data)

        response_json = json.loads(response_text)

        try:
            if _determine_runtime():
                search_response = json.loads(response_json["content"])["results"]
            else:
                search_response = response_json["results"]
        except KeyError:
            raise SnowflakeError(
                message=f"unable to parse Cortex Search response {response_json.get('message', 'Unknown error')}"
            )

        search_col = self._get_search_column(self.service_name)
        citations = self._get_citations(search_response, search_col)

        gateway_logger.log("DEBUG", f"Cortex Search Response: {search_response}")

        return {
            "output": search_response,
            "sources": {
                "tool_type": "cortex_search",
                "tool_name": self.name,
                "metadata": citations,
            },
        }

    def _prepare_request(self, query: str) -> tuple:
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
    ) -> List[str]:
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
    asearch: ClassVar[Any]
    _process_analyst_message: ClassVar[Any]

    def __init__(
        self,
        semantic_model: str,
        stage: str,
        service_topic: str,
        data_description: str,
        snowflake_connection: Union[Session, SnowflakeConnection],
        max_results: int = None,
    ):
        """Initialize CortexAnalystTool with parameters."""
        tname = semantic_model.replace(".yaml", "") + "_" + "cortexanalyst"
        tool_description = self._prepare_analyst_description(
            name=tname,
            service_topic=service_topic,
            data_source_description=data_description,
        )

        def analyst_call(query: str):
            return self.query(query)

        super().__init__(name=tname, func=analyst_call, description=tool_description)
        self.connection = _get_connection(snowflake_connection)
        self.FILE = semantic_model
        self.STAGE = stage
        self.max_results = max_results

        gateway_logger.log("INFO", "Cortex Analyst Tool successfully initialized")

    def __call__(self, prompt: str) -> Any:
        if self.max_results is not None:
            prompt = (
                prompt
                + f" Only return up to {self.max_results} relevant records in the final results. "
            )
        return self.query(query=prompt)

    async def query(self, query):
        gateway_logger.log("DEBUG", f"Cortex Analyst Prompt:{query}")
        url, headers, data = self._prepare_analyst_request(prompt=query)

        response_text = await post_cortex_request(url=url, headers=headers, data=data)
        json_response = json.loads(response_text)

        gateway_logger.log("DEBUG", f"Cortex Analyst Raw Response: {json_response}")

        try:
            if _determine_runtime() and isinstance(json_response["content"], str):
                json_response["content"] = json.loads(json_response["content"])
                query_response = self._process_analyst_message(
                    json_response["content"]["message"]["content"]
                )
            else:
                x = json_response["message"]["content"]
                query_response = self._process_analyst_message(x)

            return query_response

        except KeyError:
            raise SnowflakeError(message=json_response.get("message", "Unknown error"))

    def _prepare_analyst_request(self, prompt: str) -> tuple:
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

    def _process_analyst_message(self, response) -> Dict[str, Any]:
        if isinstance(response, list) and len(response) > 0:
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
        self.args_schema = self._create_args_schema(python_func)
        super().__init__(
            name=python_func.__name__,
            func=self.python_callable,
            description=self.desc,
            args_schema=self.args_schema,
        )
        gateway_logger.log("INFO", "Python Tool successfully initialized")

    def __call__(self, *args, **kwargs):
        return self.python_callable(*args, **kwargs)

    def asyncify(self, sync_func):
        async def async_func(*args, **kwargs):
            loop = asyncio.get_running_loop()
            _func = partial(sync_func, *args, **kwargs)
            result = await loop.run_in_executor(None, _func)
            return {
                "output": result,
                "sources": {
                    "tool_type": "custom_tool",
                    "tool_name": sync_func.__name__,
                    "metadata": [{"python_tool": f"{sync_func.__name__} tool"}],
                },
            }

        return async_func

    def _generate_description(
        self, python_func: callable, tool_description: str, output_description: str
    ) -> str:
        full_sig = self._process_full_signature(python_func=python_func)
        return f"""{full_sig}:\n - {tool_description}\n - {output_description}"""

    def _process_full_signature(self, python_func: callable) -> str:
        name = python_func.__name__
        signature = str(inspect.signature(python_func))
        return name + signature

    def _create_args_schema(self, func) -> Type[BaseModel]:
        """Generate a Pydantic schema from the function's signature."""
        params = signature(func).parameters
        fields = {
            name: (param.annotation if param.annotation != param.empty else Any, ...)
            for name, param in params.items()
        }
        return create_model(f"{func.__name__}ArgsSchema", **fields)


class SQLTool(Tool):
    def __init__(
        self,
        name: str,
        sql_query: str,
        connection: Union[Session, SnowflakeConnection],
        tool_description: str,
        output_description: str,
    ) -> None:
        self.connection = _get_connection(connection)
        self.sql_query = sql_query
        self.name = name
        self.desc = self._generate_description(
            tool_description=tool_description,
            output_description=output_description,
        )
        super().__init__(name=self.name, func=self.query, description=self.desc)
        gateway_logger.log("INFO", "SQL Tool successfully initialized")

    def __call__(self, *args):
        return self.query(*args)

    async def query(self, *args):
        return await self._run_query()

    async def _run_query(self):
        gateway_logger.log("DEBUG", f"Running SQL Query: {self.sql_query}")
        table = self.connection.cursor().execute(self.sql_query).fetch_pandas_all()
        gateway_logger.log("DEBUG", f"SQL Tool Response: {table}")
        return {
            "output": table,
            "sources": {
                "tool_type": "SQL",
                "tool_name": self.name,
                "metadata": [{"sql_tool": f"{self.name} tool"}],
            },
        }

    def _generate_description(
        self,
        tool_description: str,
        output_description: str,
    ) -> str:
        return (
            f"""{self.name}() -> str:\n"""
            f""" - Runs a SQL pipeline against source data to {tool_description}\n"""
            f""" - Returns {output_description}\n"""
        )


# Check if we're in a Jupyter environment
def is_jupyter():
    try:
        shell = get_ipython().__class__.__name__
        if shell == "ZMQInteractiveShell":  # Jupyter notebook or qtconsole
            return True
        elif shell == "TerminalInteractiveShell":  # Terminal IPython
            return False
        else:
            return False
    except NameError:  # Standard Python interpreter
        return False


# Apply nest_asyncio if in Jupyter environment
if is_jupyter():
    try:
        import nest_asyncio

        nest_asyncio.apply()
        gateway_logger.log("DEBUG", "nest_asyncio applied for Jupyter compatibility")
    except ImportError:
        print("Please install nest_asyncio: pip install nest_asyncio")


def is_fastmcp_available():
    import importlib.util

    return importlib.util.find_spec("fastmcp") is not None


class MCPTool:
    def __new__(cls, server_path: str):
        """Create and return a list of compatible tools give MCP server url or server.py path"""

        if not is_fastmcp_available():
            raise ModuleNotFoundError(
                "Ensure fastmcp is installed in this environment. Use pip install orchestration-framework[fastmcp]."
            )

        from fastmcp import Client
        from fastmcp import FastMCP as FastMCPTool
        import mcp.types

        cls.mcptypes = mcp.types
        cls.Client = Client
        cls.FastMCPTool = FastMCPTool

        instance = super().__new__(cls)
        instance.server_path = server_path
        tools = instance.generate_tools_from_mcp()
        gateway_logger.log("INFO", "MCP Tool successfully initialized")
        return tools

    def generate_tools_from_mcp(self):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            mcps = loop.run_until_complete(self._get_mcp_tools(self.server_path))
            tools = [self._convert_from_mcp_tool(mcp) for mcp in mcps]
            return tools
        except Exception as e:
            gateway_logger.log("ERROR", f"Error generating MCP tools: {str(e)}")
            raise

    def _convert_from_mcp_tool(self, tool):
        args_schema = tool.inputSchema.get("properties")
        args_reqs = tool.inputSchema.get("required")

        if args_reqs is not None:
            input_schema = {}
            for arg in args_reqs:
                type = args_schema.get(arg).get("type")
                input_schema[arg] = type

            mcp_tool_signature = f"{tool.name}({input_schema})"
        else:
            mcp_tool_signature = f"{tool.name}()"

        mcp_desc = self._generate_mcp_tool_description(
            tool_name=tool.name,
            tool_description=tool.description,
            tool_signature=mcp_tool_signature,
        )

        async def mcp_request(*args, **kwargs):
            async with self.Client(self.server_path) as client:
                result = await client.call_tool(tool.name, *args, **kwargs)
                return {
                    "output": result[0].text,
                    "sources": {
                        "tool_type": "MCP",
                        "tool_name": tool.name,
                        "metadata": [{"mcp_tool": f"{tool.name} tool"}],
                    },
                }

        return Tool(
            name=tool.name,
            func=mcp_request,
            description=mcp_desc,
            args=tool.inputSchema,
        )

    def _convert_from_mcp_resource(self, resource):
        mcp_desc = self._generate_mcp_tool_description(
            tool_name=resource.name,
            tool_description=f"retrieves {resource.name} resources",
            tool_signature=f"{resource.name}()",
        )

        async def mcp_resource_request():
            """Args:
            uri (AnyUrl | str): The URI of the resource to read. Can be a string or an AnyUrl object.

            Returns:
                list[mcp.types.TextResourceContents | mcp.types.BlobResourceContents]: A list of content
                    objects, typically containing either text or binary data.
            Raises:
                RuntimeError: If called while the client is not connected."""
            async with self.Client(self.server_path) as client:
                rsrc = await client.read_resource(resource.uri)
                return {
                    "output": rsrc,
                    "sources": {
                        "tool_type": "MCP",
                        "tool_name": resource.name,
                        "metadata": [{"mcp_tool": f"{resource.name} tool"}],
                    },
                }

        return Tool(name=resource.name, func=mcp_resource_request, description=mcp_desc)

    async def _get_mcp_tools(self, path):
        """Async function to get MCP tools."""
        async with self.Client(path) as client:
            tools = await client.list_tools()
            return tools

    async def _get_mcp_resources(self, path):
        """Async function to get MCP tools."""
        async with self.Client(path) as client:
            resources = await client.list_resources()
            return resources

    async def _get_mcp_resources(self, path):
        """Async function to get MCP tools."""
        async with self.Client(path) as client:
            resources = await client.list_resources()
            return resources

    def _generate_mcp_tool_description(
        self, tool_name: str, tool_description: str, tool_signature: str
    ) -> str:
        return (
            f"""{tool_signature} -> str:\n"""
            f""" - Runs the {tool_name} function to {tool_description}\n"""
            f""" - Returns result from running {tool_name}\n"""
        )
