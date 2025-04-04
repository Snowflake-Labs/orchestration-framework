from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import os

from agent_gateway import Agent
from agent_gateway.tools.snowflake_tools import (
    CortexSearchTool,
)  # PythonTool,CortexAnalystTool,
from snowflake.snowpark import Session


# Models for request/response
class QueryRequest(BaseModel):
    query: str
    memory: bool = True


class QueryResponse(BaseModel):
    output: str
    sources: Optional[Any] = None


# Global agent instance
agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the agent before the application starts
    global agent
    try:
        # Initialize Snowflake connection
        connection = Session.builder.configs(
            {
                "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
                "user": os.environ.get("SNOWFLAKE_USER"),
                "password": os.environ.get("SNOWFLAKE_PASSWORD"),
                "role": os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
                "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"),
                "database": os.environ.get("SNOWFLAKE_DATABASE"),
                "schema": os.environ.get("SNOWFLAKE_SCHEMA"),
            }
        ).create()

        # Define your tools
        tools = [
            # Add your tools here, for example:
            CortexSearchTool(
                service_name="your_service",
                service_topic="your_topic",
                data_description="your_description",
                retrieval_columns="your_columns",
                snowflake_connection=connection,
            ),
        ]

        # Initialize the agent once
        agent = Agent(snowflake_connection=connection, tools=tools, memory=False)
        print("Agent initialized successfully")
    except Exception as e:
        print(f"Failed to initialize agent: {str(e)}")

    yield  # Application runs here

    # Shutdown: Clean up resources when the application is shutting down
    print("Shutting down agent and cleaning up resources")


# Pass the lifespan function to FastAPI
app = FastAPI(title="Agent Gateway API", lifespan=lifespan)


@app.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    global agent
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = await agent.acall(request.query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")


@app.get("/health")
async def health_check():
    global agent
    return {
        "status": "healthy" if agent is not None else "agent not initialized",
        "version": "1.0.0",
    }
