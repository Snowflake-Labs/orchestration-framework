# Cortex Cube - A Multi Agent Framework For Snowflake 

Cortex Cube is a multi-agent framework that offers native support for Snowflake tools. Instead of requiring users or developers to choose between RAG with Cortex Search or Text2SQL with Cortex Analyst, let the Cube route the work to the appropriate tool based on the user's request.

CortexCube can be configured to work with 3 types of tools:
- Cortex Search Tool: For unstructured data analysis, which requires a standard RAG access pattern.
- Cortex Analyst Tool: For supporting structured data analysis, which requires a Text2SQL access pattern.
- Python Tool: For supporting custom user operations (using 3rd Party API's), which requires calling arbitray python.

This notebook walks through how to configure and run a system with all 3 types of tools. The demo is designed to illustrate how the agent can answer questions that require a divserse combination of tools (RAG,Text2SQL, Python, or a combination).

## Requirements

Note that Cortex Cube does not configure the underlying Cortex Search or Cortex Analyst services for the user. Those services must be configured before initializing Cortex Cube.

>**Authentication for Mac Users**

> Mac users have reported SSL Certificate authentication issues for Snowflake's Cortex REST API, which impacts Cortex Cube. We've found that
python enviornments on Mac don't always have access to the requisite certificates to succesfully hit the REST endpoints.
To resolve this, cd into your Python directory and run ./Install\ Certificates.command. Alternatively, using  Finder lookup the "Install  
Certificates.command" and double click to run the file in your relevant Python directory. (If multiple results show up on Finder, make sure 
to run the one in the appropriate path for your application).]



## Tool Configuration

See CubeQuickstart.ipynb for a complete walkthrough of configuration and usage.

```python

search_config = {
    "service_name":"SEC_SEARCH_SERVICE",
    "service_topic":"Snowflake's business,product offerings,and performance",
    "data_description": "Snowflake annual reports",
    "retrieval_columns":["CHUNK"],
    "snowpark_connection": snowpark
}

analyst_config = {
    "semantic_model":"sp500_semantic_model.yaml",
    "stage":"SEMANTICS",
    "service_topic":"S&P500 company and stock metrics",
    "data_description": "a table with stock and financial metrics about S&P500 companies ",
    "snowpark_connection": snowpark
}

annual_reports = CortexSearchTool(config = search_config,k=5)
sp500 = CortexAnalystTool(config = analyst_config)
snowflake_tools = [annual_reports,sp500]
```

## Cortex Cube - Configuration + Usage
````python

# Config + Initialize Cortex Cube
analyst = CortexCube(tools=snowflake_tools)

# Run Cortex Cube
answer = await analyst.acall("What is the average price for toothbrushes?")
print(answer['output])

````
