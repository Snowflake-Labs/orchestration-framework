import os

import pytest
from snowflake.snowpark import Session

from CortexCube.tools.utils import generate_demo_services


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


@pytest.fixture(scope="session")
def session():
    conf = TestConf()
    generate_demo_services(conf.session)
    yield conf.session
