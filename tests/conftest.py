import os
from dotenv import load_dotenv
from snowflake.snowpark import Session
from collections import deque
from pathlib import Path

import pytest


class TestConf:
    def __init__(self):
        self.session = self.connect()

    def connect(self):
        connection_params = {
            k.replace("SNOWFLAKE_", "").lower(): v
            for k, v in os.environ.items()
            if k.startswith("SNOWFLAKE_") and v.lower() not in ["database", "schema"]
        }
        return Session.builder.configs(connection_params).getOrCreate()

    def setup_objects(self):
        scripts = sorted(list(Path("tests/scripts").glob("*.sql")))
        print(len(scripts))
        con = self.session.connection
        for script in scripts:
            with open(script, "r") as f:
                deque(con.execute_stream(f), maxlen=0)
        self.session.use_schema("CUBE_TESTING.PUBLIC")


@pytest.fixture(scope="session")
def session():
    conf = TestConf()
    conf.setup_objects()
    yield conf.session
