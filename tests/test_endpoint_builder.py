from urllib.parse import urlparse

from CortexCube.tools.utils import CortexEndpointBuilder


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
