# Cortex Cube

Cortex Cube is a multi-agent framework that offers native support for Snowflake tools. Instead of requiring users or developers to choose between RAG with Cortex Search or Text2SQL with Cortex Analyst, let the Cube orchestrate the user requests to the appropriate tool.

CortexCube can be configured to work with 3 types of tools:
- **Cortex Search Tool**: For unstructured data analysis, which requires a standard RAG access pattern.
- **Cortex Analyst Tool**: For supporting structured data analysis, which requires a Text2SQL access pattern.
- **Python Tool**: For supporting custom user operations (i.e. sending API requests to third party services), which requires calling arbitrary python.

Users have the flexibility to create multiple Cortex Search and Cortex Analyst tools for use with Cortex Cube. For a walkthrough of how to configure and run a system with all 3 types of tools, see the quickstart notebook.

# Getting Started

## Installation
In a new virtual enviornment with Python 3.10 or 3.11, install the latest version of Cortex Cube.
```python
pip install cortex-cube@git+https://github.com/Snowflake-Labs/cortex-cube.git
```

**Note For Mac Users**: Mac users have reported SSL Certificate issues when using the Cortex REST API. This is related to python virtual enviornments not having access to local certificates. One potential solution to avoid SSL Certificate issues is to use Finder to locate the "Install Certificates.command" file in your relevant python directory and run that file before initializing Cortex Cube. See [this thread](https://github.com/python/cpython/issues/87570#issuecomment-1093904961) for more info.

## Tool Requirements
Cortex Cube requires the underlying Cortex Search, Cortex Analyst, or Python tools to be configured by the user.

To follow the Quickstart notebook in this repo, you can generate the Cortex Search and Cortex Analyst demo services as follows:
```python
from CortexCube.tools.utils import generate_demo_services
from snowflake.snowpark import Session

connection_parameters = {

    "account": os.getenv('SNOWFLAKE_ACCOUNT'),
    "user": os.getenv('SNOWFLAKE_USER'),
    "password": os.getenv('SNOWFLAKE_PASSWORD'),
    "role": os.getenv('SNOWFLAKE_ROLE'),
    "warehouse": os.getenv('SNOWFLAKE_WAREHOUSE'),
    "database": os.getenv('SNOWFLAKE_DATABASE'),
    "schema": os.getenv('SNOWFLAKE_SCHEMA')}

session = Session.builder.configs(connection_parameters).create()

generate_demo_services(session)
```


## Snowflake Tool Configuration
Tools must be configured with relevant metadata for the Cube to route requests to the appropriate service.

**NOTE:** For best results, use specific and mutually exclusive language in your metadata descriptions to make it easy for Cortex Cube to delegate work to the right tools.

##### Cortex Search Tool Configuration
```python
from CortexCube import CortexSearchTool,CortexAnalystTool,PythonTool

# Cortex Search Service Config
search_config = {
    "service_name":"SEC_SEARCH_SERVICE",
    "service_topic":"Snowflake's business,product offerings,and performance",
    "data_description": "Snowflake annual reports",
    "retrieval_columns":["CHUNK"],
    "snowflake_connection": session
}

annual_reports = CortexSearchTool(**search_config)
```
##### Cortex Analyst Tool Configuration
```python
# Cortex Analyst Config
analyst_config = {
    "semantic_model":"sp500_semantic_model.yaml",
    "stage":"ANALYST",
    "service_topic":"S&P500 company and stock metrics",
    "data_description": "a table with stock and financial metrics about S&P500 companies ",
    "snowflake_connection": session
}

sp500 = CortexAnalystTool(**analyst_config)
```
##### Python Tool Configuration
```python
python_config = {
    "tool_description": "searches for relevant news based on user query",
    "output_description": "relevant articles",
    "python_func": news_search,
}

news_search = PythonTool(**python_config)
```

## Cube Configuration + Usage
````python
from CortexCube import CortexCube

# Config + Initialize Cortex Cube
snowflake_tools = [annual_reports,sp500,news_search]
cube_agent = CortexCube(snowflake_connection=session,tools=snowflake_tools)

# Run Cortex Cube
answer = cube_agent("What is the average price for toothbrushes?")
print(answer)

# Async Execution of Cortex Cube
answer = await cube_agent.acall("What is the average price for toothbrushes?")
print(answer)
````

# FAQs

#### Where does Cortex Cube run?
- This initial version of Cortex Cube is a client-side library. Orchestration is done by Cortex Cube in your local enviornment while the compute is done inside of Snowflake.

#### Does Cortex Cube work with a Streamlit UI?
- Yes, see the cube_demo_app directory for an example Streamlit app that uses Cortex Cube for orchestration across Cortex Search, Cortex Analyst, and Python tools. Note, running Cortex Cube in SiS is not yet supported.

#### How does authentication work with Cortex Cube?
- Cortex Cube takes an authenticated snowpark connection. Just create your session object with your standard [connection parameters](https://docs.snowflake.com/en/developer-guide/snowpark/reference/python/latest/snowpark/api/snowflake.snowpark.Session)

#### If I have multiple Cortex Search Services, can I use multiple Cortex Search tools with Cortex Cube?
- Yes, Cortex Cube supports the use of multiple tools of the same type.
```python
search_one = CortexSearchTool(**search_one_config)
search_two = CortexSearchTool(**search_two_config)
cube = CortexCube(snowflake_connection=session,tools=[search_one,search_two]
```

#### If my snowflake tools live in different accounts / schemas, can I still use Cortex Cube?
- Yes. The Cortex Analyst and Cortex Search tools take in a snowpark session as an input. This allows users to use different sessions / accounts in the same Cortex Cube instance.

#### How can I see which tools are being used by Cortex Cube?
- The Cortex Cube logger is set to INFO level by default. This allows users to view which tools are being used to answer the user's question. For more detailed logging and visibility into intermediary results of the tool calls, set the LOGGING_LEVE=DEBUG.

#### I'm not getting any results when I submit a user request to the Cube. How do I debug this?
- If the end to end Cube run doesn't return any results, try running the tools separately to validate that they've been configured appropriately. Tools are implemented asynchronousy, so you can run your tools in isolation and validate the config as follows:
```python
tool_result = await my_cortex_search_tool("This is a sample cortex search question")
```

# Bug Reports, Feedback, or Other Questions
- You can add issues to the github or email Alejandro Herrera (alejandro.herrera@snowflake.com)
