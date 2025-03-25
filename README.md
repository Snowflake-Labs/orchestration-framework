# Agentic Orchestration Framework

The Agent Gateway is an agentic orchestration framework that offers native support for
Snowflake tools.

Instead of requiring users or developers to choose between RAG with Cortex Search or
Text2SQL with Cortex Analyst, the Agent Gateway orchestrates the request to the
appropriate tool.

The Agent Gateway can be configured to work with 4 types of tools:
- **Cortex Search Tool**: For unstructured data analysis, which requires a standard RAG
access pattern.
- **Cortex Analyst Tool**: For structured data analysis, which requires a
Text2SQL access pattern.
- **Python Tool**: For custom operations (i.e. sending API requests to
3rd party services), which requires calling arbitrary Python.
- **SQL Tool**: For supporting custom SQL pipelines built by users.

The Agent Gateway supports multi-step and multi-tool workflows. Users have the
flexibility to create multiple Cortex Search and Cortex Analyst tools for use with the
Agent Gateway. For a walkthrough of how to configure and run a system with all 3 types
of tools, see the [Quickstart](Quickstart.ipynb) notebook.

# Getting Started

## Installation

In a new virtual environment with Python 3.10 or 3.11, install the latest version of this
framework.

```sh
pip install orchestration-framework
```

**Note For Mac Users**: Mac users have reported SSL Certificate issues when using the
Cortex REST API. This is related to python virtual environments not having access to
local certificates. One potential solution to avoid SSL Certificate issues is to use
Finder to locate the "Install Certificates.command" file in your relevant Python
directory and run that file before initializing the agent. See [this thread](https://github.com/python/cpython/issues/87570#issuecomment-1093904961) for more info.

## Tool Requirements

Agents require the underlying Cortex Search, Cortex Analyst, SQL or Python tools to
be configured by the user.

To follow the Quickstart notebook in this repo, you can generate the Cortex Search and
Cortex Analyst demo services as follows:

```python
from agent_gateway.tools.utils import generate_demo_services
from snowflake.snowpark import Session

session = Session.builder.create()
generate_demo_services(session)
```

## Snowflake Tool Configuration

Tools must be configured with relevant metadata for the Agent Gateway to route requests to the
appropriate service.

**NOTE:** For best results, use specific and mutually exclusive language in your
metadata descriptions to make it easy for the agent to delegate work to the right
tools.

##### Cortex Search Tool Configuration

```python
from agent_gateway.tools import CortexSearchTool, CortexAnalystTool, PythonTool, SQLTool

# Cortex Search Service Config
search_config = {
    "service_name": "SEC_SEARCH_SERVICE",
    "service_topic": "Snowflake's business,product offerings,and performance",
    "data_description": "Snowflake annual reports",
    "retrieval_columns": ["CHUNK"],
    "snowflake_connection": session,
}

annual_reports = CortexSearchTool(**search_config)
```

##### Cortex Analyst Tool Configuration

```python
# Cortex Analyst Config
analyst_config = {
    "semantic_model": "sp500_semantic_model.yaml",
    "stage": "ANALYST",
    "service_topic": "S&P500 company and stock metrics",
    "data_description": "a table with stock and financial metrics about S&P500 companies ",
    "snowflake_connection": session,
}

sp500 = CortexAnalystTool(**analyst_config)
```
##### Python Tool Configuration

```python
def get_html(url):
        response = requests.get(url)
        return response.text

python_scraper_config = {
    "tool_description": "reads the html from a given URL or website",
    "output_description": "html of a webpage",
    "python_func": get_html
    }

web_crawler = PythonTool(**python_scraper_config)
```

##### SQL Tool Configuration

```python
sql_query = '''SELECT * FROM MY_EVENTS_TABLE '''
sql_tool_config = {
    "name": "custom_metrics_pipeline",
    "tool_description": "analyzes custom user metrics",
    "output_description": "key user metrics",
    "sql": sql_query,
    "connection":session
    }

custom_metrics = SQLTool(**sql_tool_config)
```

## Agent Configuration + Usage

````python
from agent_gateway import Agent

# Config + Initialize Agent
snowflake_tools = [annual_reports, sp500, web_crawler]
snowflake_agent = Agent(snowflake_connection=session, tools=snowflake_tools)

# Structured Data Question (Text2SQL)
answer = snowflake_agent("What is market cap of company X?")
print(answer)

# Unstructured Data Question (RAG)
answer = snowflake_agent("What are the strategic plans for company X")
print(answer)

# Web Search Question (Python Tool)
answer = snowflake_agent(
    "Summarize this article: http://localhost:8080/dummyproductannouncements/interview.html"
)
print(answer)
````

# FAQs

#### Where does the Agent Gateway run?

- This library is optimized for client-side orchestration. If you prefer a managed service that does the orchestration inside of Snowflake, we recommend using the Snowflake Cortex Agent API.

#### Can I use the Agent Gateway within SPCS or a Snowflake Notebook?

- Yes, the Agent Gateway can run in SPCS and Snowflake notebooks. To install the library directly from GitHub or Pypi, you must enable a network rule
with an external access integration. Here is an example configuration:

```sql
CREATE NETWORK RULE agent_network_rule
MODE = EGRESS
TYPE = HOST_PORT
VALUE_LIST = ('github.com');

CREATE EXTERNAL ACCESS INTEGRATION agent_network_int
ALLOWED_NETWORK_RULES = (agent_network_rule)
ENABLED = true;
```

#### Does the Agent Gateway work with a Streamlit UI?

- Yes, see the [demo app](https://github.com/Snowflake-Labs/orchestration-framework/blob/main/demo_app/demo_app.py) for an example Streamlit app that uses the Agent Gateway for orchestration across Cortex Search, Cortex Analyst, and Python tools. You can run the app on Streamlit in Snowflake or in SPCS.

#### How does authentication work?

- The Agent Gateway and its tools take an authenticated snowpark connection. Just create your session
object with your standard [connection parameters](https://docs.snowflake.com/en/developer-guide/snowpark/reference/python/latest/snowpark/api/snowflake.snowpark.Session).

#### If I have multiple Cortex Search Services, can I use multiple Cortex Search tools with this framework?

- Yes, you can connect multiple tools of the same type to the Agent Gateway.
```python
search_one = CortexSearchTool(**search_one_config)
search_two = CortexSearchTool(**search_two_config)
snowflake_agent = Agent(snowflake_connection=session, tools=[search_one, search_two])
```

#### If my Snowflake tools live in different accounts / schemas, can I still use the Agent Gateway?

- Yes. The Cortex Analyst and Cortex Search tools take in a snowpark session as an
input. This allows users to use different sessions / accounts in the same gateway agent.

#### How can I see which tools are being used by the Agent Gateway?

- The Agent Gateway logger is set to INFO level by default. This allows users to view
which tools are being used to answer the user's question. For more detailed logging and
visibility into intermediary results of the tool calls, set the LOGGING_LEVEL=DEBUG.

#### I'm not getting any results when I submit a request. How do I debug this?

- Tools are implemented asynchronously. To validate your configuration, you can run each tool in isolation as follows:
```python
import asyncio
asyncio.run(my_cortex_search_tool("This is a sample cortex search question"))
```
- For more detailed logging and traces of the agent's execution, consider using the native Trulens integration.
You can `pip install orchestration-framework[trulens]` and use the TruAgent class as outlined in the quickstart.


#### How does it work?

- This framework supports multi-hop, multi-tool workflows with parallel function calling. It utilizes a dedicated planner LLM to decompose the user's request and generate an execution plan. From there it creates a graph of tasks that will invoke the tool calls asynchronously and in parallel if possible. While the orchestration is done on the client-side, Snowflake compute is leveraged for plan generation and tooling execution.
- We leverage the LLM Compiler architecture from Berkeley AI Research Lab. Kim, S., Moon, S., Tabrizi, R., Lee, N., Mahoney, M. W., Keutzer, K., and Gholami, A. An LLM Compiler for Parallel Function Calling, 2024.

# Bug Reports, Feedback, or Other Questions

- You can add issues to the GitHub or email Alejandro Herrera (alejandro.herrera@snowflake.com)
