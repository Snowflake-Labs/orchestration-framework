import io
from collections import deque
from textwrap import dedent
from typing import TypedDict, Union
from urllib.parse import urlunparse

import pkg_resources
from snowflake.connector.connection import SnowflakeConnection
from snowflake.snowpark import Session


class Headers(TypedDict):
    Accept: str
    Content_Type: str
    Authorization: str


class CortexEndpointBuilder:
    def __init__(self, connection: Union[Session, SnowflakeConnection]):
        self.connection = connection
        self._set_connection()
        self.BASE_URL = self._set_base_url()
        self.BASE_HEADERS = {
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{self.connection.rest.token}"',
        }

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

    def get_complete_headers(self) -> Headers:
        return self.BASE_HEADERS | {"Accept": "application/json"}

    def get_analyst_headers(self) -> Headers:
        return self.BASE_HEADERS

    def get_search_headers(self) -> Headers:
        return self.BASE_HEADERS | {"Accept": "application/json"}


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


def generate_demo_services(session: Session):
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
