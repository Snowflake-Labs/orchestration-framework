# Copyright 2025 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import json
import re

import pytest

from agent_gateway import Agent
from agent_gateway.tools import CortexAnalystTool, CortexSearchTool, PythonTool, SQLTool
from tests.data.sql_response import SQL_RESPONSE


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
        "snowflake_connection": session,
    }
    annual_reports = CortexSearchTool(**search_config)
    response = [
        chunk.get("CHUNK")
        for chunk in asyncio.run(annual_reports(question)).get("output")
    ]
    print("Actual chunks:", response)
    assert any(re.search(re.escape(answer), chunk) for chunk in response)


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
        "stage": "ANALYST",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowflake_connection": session,
    }
    sp500 = CortexAnalystTool(**analyst_config)
    response = asyncio.run(sp500(question)).get("output")

    assert response == answer


def test_sql_tool(session):
    margin_query = """SELECT
        LONGNAME,
        MARKETCAP,
        CASE
            WHEN MARKETCAP > 0 THEN (EBITDA * 100.0) / MARKETCAP
            ELSE NULL
        END AS EBITDA_Margin_Percentage
    FROM CUBE_TESTING.PUBLIC.SP500
    LIMIT 3;"""

    sql_config = {
        "name": "margin_eval",
        "sql_query": margin_query,
        "connection": session,
        "tool_description": "calculate EBITDA Margin (%) of S&p500 companies",
        "output_description": "ebitda margin (%) metrics per company",
    }

    sql_tool = SQLTool(**sql_config)
    response = asyncio.run(sql_tool())

    assert SQL_RESPONSE == str(response)


@pytest.mark.parametrize(
    "question, answer",
    [
        pytest.param(
            "What are the top companies by market cap?",
            "{'SHORTNAME': ['Microsoft Corporation', 'Apple Inc.', 'NVIDIA Corporation', 'Alphabet Inc.', 'Amazon.com, Inc.'], 'MARKETCAP': [3150184448000, 3019131060224, 2973639376896, 2164350779392, 1917936336896]}",
            id="top_market_cap",
        ),
    ],
)
def test_analyst_w_max_results(session, question, answer):
    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "ANALYST",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowflake_connection": session,
        "max_results": 5,
    }
    sp500 = CortexAnalystTool(**analyst_config)
    response = asyncio.run(sp500(question)).get("output")

    assert response == answer


def test_python_tool():
    def get_news(_) -> dict:
        with open("tests/data/response.json") as f:
            d = json.load(f)
        return d

    python_config = {
        "tool_description": "searches for relevant news based on user query",
        "output_description": "relevant articles",
        "python_func": get_news,
    }
    news_search = PythonTool(**python_config)
    response = asyncio.run(news_search("When is Apple releasing a new chip?")).get(
        "output"
    )
    assert get_news(None) == response


@pytest.mark.parametrize(
    "question, answer_contains",
    [
        pytest.param(
            "What is the market cap of Apple?",
            "$3,019,131,060,224",
            id="market_cap",
        ),
        pytest.param(
            "When is Apple releasing a new chip?",
            "May 7",
            id="product_revenue",
        ),
    ],
)
def test_gateway_agent(session, question, answer_contains):
    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowflake_connection": session,
    }
    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "ANALYST",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowflake_connection": session,
    }

    def get_news(_) -> dict:
        with open("tests/data/response.json") as f:
            d = json.load(f)
        return d

    python_config = {
        "tool_description": "searches for relevant news based on user query",
        "output_description": "relevant articles",
        "python_func": get_news,
    }
    margin_query = """SELECT
        LONGNAME,
        SECTOR,
        INDUSTRY,
        CURRENTPRICE,
        MARKETCAP,
        EBITDA,
        CASE
            WHEN MARKETCAP > 0 THEN (EBITDA * 100.0) / MARKETCAP
            ELSE NULL
        END AS EBITDA_Margin_Percentage
    FROM CUBE_TESTING.PUBLIC.SP500;"""

    sql_config = {
        "name": "margin_eval",
        "sql_query": margin_query,
        "connection": session,
        "tool_description": "calculate EBITDA Margin (%) of S&p500 companies",
        "output_description": "ebitda margin (%) metrics per company",
    }

    annual_reports = CortexSearchTool(**search_config)
    sp500 = CortexAnalystTool(**analyst_config)
    news_search = PythonTool(**python_config)
    sql_tool = SQLTool(**sql_config)
    agent = Agent(
        snowflake_connection=session,
        tools=[annual_reports, sp500, news_search, sql_tool],
    )
    response = agent(question).get("output")
    assert answer_contains in response


@pytest.mark.parametrize(
    "question, answer_contains",
    [
        pytest.param(
            "What is the market cap of Apple?",
            "$3,019,131,060,224",
            id="market_cap",
        ),
        pytest.param(
            "When is Apple releasing a new chip?",
            "May 7",
            id="product_revenue",
        ),
        pytest.param(
            "What is the EBITDA margin of Microsoft?",
            " 4%",
            id="ebitda_margin",
        ),
    ],
)
def test_gateway_agent_without_memory(session, question, answer_contains):
    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowflake_connection": session,
    }
    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "ANALYST",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowflake_connection": session,
    }

    def get_news(_) -> dict:
        with open("tests/data/response.json") as f:
            d = json.load(f)
        return d

    python_config = {
        "tool_description": "searches for relevant news based on user query",
        "output_description": "relevant articles",
        "python_func": get_news,
    }

    margin_query = """SELECT
        LONGNAME,
        SECTOR,
        INDUSTRY,
        CURRENTPRICE,
        MARKETCAP,
        EBITDA,
        CASE
            WHEN MARKETCAP > 0 THEN (EBITDA * 100.0) / MARKETCAP
            ELSE NULL
        END AS EBITDA_Margin_Percentage
    FROM CUBE_TESTING.PUBLIC.SP500;"""

    sql_config = {
        "name": "margin_eval",
        "sql_query": margin_query,
        "connection": session,
        "tool_description": "calculate EBITDA Margin (%) of S&p500 companies",
        "output_description": "ebitda margin (%) metrics per company",
    }
    annual_reports = CortexSearchTool(**search_config)
    sp500 = CortexAnalystTool(**analyst_config)
    news_search = PythonTool(**python_config)
    sql_tool = SQLTool(**sql_config)
    agent = Agent(
        snowflake_connection=session,
        tools=[annual_reports, sp500, news_search, sql_tool],
        memory=False,
    )
    response = agent(question).get("output")
    assert answer_contains in response
