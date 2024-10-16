from CortexCube import CortexCube, CortexSearchTool, CortexAnalystTool, PythonTool
import pytest
import asyncio


@pytest.mark.parametrize(
    "question, answer",
    [
        pytest.param(
            "How many customers did Snowflake have as of January 31, 2021?",
            "As of January 31, 2021, we had 4,139 total customers",
            id="customer_count",
        ),
        pytest.param(
            "How much did product revenue increase for the fiscal year ended January 31, 2021?",
            "Product revenue increased $301.6 million",
            id="product_revenue",
        ),
    ],
)
def test_search_tool(session, question, answer):
    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowpark_connection": session,
    }
    annual_reports = CortexSearchTool(**search_config)
    response = asyncio.run(annual_reports(question))

    assert answer in response[0].get("CHUNK")
