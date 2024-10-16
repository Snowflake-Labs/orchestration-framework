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


@pytest.mark.parametrize(
    "question, answer",
    [
        pytest.param(
            "What is the market cap of Apple, Inc?",
            "{'MARKETCAP': [3019131060224]}",
            id="apple_market_cap",
        ),
        pytest.param(
            "What is the market cap of Tesla?",
            "{'MARKETCAP': [566019162112]}",
            id="tesla_market_cap",
        ),
    ],
)
def test_analyst_tool(session, question, answer):
    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "SEMANTICS",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowpark_connection": session,
    }
    sp500 = CortexAnalystTool(**analyst_config)
    response = asyncio.run(sp500(question))

    assert response == answer


def test_cube_agent(session):
    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowpark_connection": session,
    }
    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "SEMANTICS",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowpark_connection": session,
    }
    annual_reports = CortexSearchTool(**search_config)
    sp500 = CortexAnalystTool(**analyst_config)
    agent = CortexCube(snowpark_session=session, tools=[annual_reports, sp500])
    response = agent("What is the market cap of Apple?")
    assert "$3,019,131,060,224" in response
