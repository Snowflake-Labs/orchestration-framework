from urllib.parse import urlparse

import pytest

from CortexCube.tools.utils import CortexEndpointBuilder


class MockConnection:
    def __init__(self, host, token, scheme="https"):
        self.host = host
        self.rest = self.Rest(token)
        self.scheme = scheme

    class Rest:
        def __init__(self, token):
            self.token = token


@pytest.fixture
def session():
    return MockConnection(host="example_host", token="dummy_token")


def test_complete_url(session):
    eb = CortexEndpointBuilder(session)
    url = eb.get_complete_endpoint()
    assert url.startswith("https://")
    assert url.endswith("/api/v2/cortex/inference:complete")
    assert "_" not in urlparse(url).hostname


def test_search_url(session):
    eb = CortexEndpointBuilder(session)
    url = eb.get_search_endpoint(
        database="TEST_DB", schema="TEST_SCHEMA", service_name="TEST_SERVICE"
    )
    assert url.startswith("https://")
    assert url.endswith(
        "/api/v2/databases/test_db/schemas/test_schema/cortex-search-services/test_service:query"
    )
    assert "_" not in urlparse(url).hostname


def test_analyst_url(session):
    eb = CortexEndpointBuilder(session)
    url = eb.get_analyst_endpoint()
    assert url.startswith("https://")
    assert url.endswith("/api/v2/cortex/analyst/message")
    assert "_" not in urlparse(url).hostname


def test_complete_headers(session):
    eb = CortexEndpointBuilder(session)
    headers = eb.get_complete_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == 'Snowflake Token="dummy_token"'
    assert headers["Accept"] == "application/json"


def test_analyst_headers(session):
    eb = CortexEndpointBuilder(session)
    headers = eb.get_analyst_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == 'Snowflake Token="dummy_token"'


def test_search_headers(session):
    eb = CortexEndpointBuilder(session)
    headers = eb.get_search_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == 'Snowflake Token="dummy_token"'
    assert headers["Accept"] == "application/json"
