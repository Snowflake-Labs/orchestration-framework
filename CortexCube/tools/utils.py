from snowflake.snowpark import Session
from snowflake.connector.connection import SnowflakeConnection
from typing import Union
from urllib.parse import urlunparse


class CortexEndpointBuilder:
    def __init__(self, connection: Union[Session, SnowflakeConnection]):
        self.connection = connection
        self._set_connection()
        self.BASE_URL = self._set_base_url()

    def _set_connection(self):
        if isinstance(self.connection, Session):
            con = getattr(self.connection, "connection")
        else:
            con = self.connection
        self.connection = con

    def _set_base_url(self):
        scheme = "https"
        con = self.connection
        if hasattr(con, "scheme"):
            scheme = con.scheme
        host = con.host
        host = host.replace("_", "-")
        host = host.lower()
        url = urlunparse((scheme, host, "", "", "", ""))
        return url

    def get_complete_endpoint(self):
        URL_SUFFIX = "/api/v2/cortex/inference:complete"
        return f"{self.BASE_URL}{URL_SUFFIX}"

    def get_analyst_endpoint(self):
        URL_SUFFIX = "/api/v2/cortex/analyst/message"
        return f"{self.BASE_URL}{URL_SUFFIX}"

    def get_search_endpoint(self, database, schema, service_name):
        URL_SUFFIX = f"/api/v2/databases/{database}/schemas/{schema}/cortex-search-services/{service_name}:query"
        URL_SUFFIX = URL_SUFFIX.lower()
        return f"{self.BASE_URL}{URL_SUFFIX}"


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
