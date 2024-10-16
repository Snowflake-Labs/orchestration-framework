import os
from dotenv import load_dotenv
from snowflake.snowpark import Session

import pytest


@pytest.fixture(scope="session")
def session():
    load_dotenv(override=True)
    connection_params = {
        k.replace("SNOWFLAKE_", "").lower(): v
        for k, v in os.environ.items()
        if k.startswith("SNOWFLAKE_")
    }
    yield Session.builder.configs(connection_params).getOrCreate()
