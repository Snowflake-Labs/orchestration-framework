import asyncio
import io
import json
import os
import queue
import re
import sys
import threading
import uuid
import warnings

import requests
import streamlit as st
from dotenv import load_dotenv
from snowflake.snowpark import Session
from streamlit.runtime.scriptrunner_utils.script_run_context import add_script_run_ctx

from CortexCube import CortexAnalystTool, CortexCube, CortexSearchTool, PythonTool
from CortexCube.tools.utils import parse_log_message

warnings.filterwarnings("ignore")
load_dotenv("../.env")
st.set_page_config(page_title="Snowflake Cortex Cube")

connection_parameters = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "user": os.getenv("SNOWFLAKE_USER"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "role": os.getenv("SNOWFLAKE_ROLE"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
    "database": os.getenv("SNOWFLAKE_DATABASE"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA"),
}


os.environ["NEWS_API_TOKEN"] = os.getenv("NEWS_API_TOKEN")
snowpark = Session.builder.configs(connection_parameters).create()


class NewsTool:
    def __init__(self, token, limit) -> None:
        self.api_token = token
        self.limit = limit

    def news_search(self, news_query: str) -> str:
        news_request = f"""https://api.thenewsapi.com/v1/news/all?api_token={self.api_token}&search={news_query}&language=en&limit={self.limit}"""
        response = requests.get(news_request)
        json_response = json.loads(response.content)["data"]

        return str(json_response)


python_config = {
    "tool_description": "searches for relevant news based on user query",
    "output_description": "relevant articles",
    "python_func": NewsTool(token=os.getenv("NEWS_API_TOKEN"), limit=3).news_search,
}

if "prompt_history" not in st.session_state:
    st.session_state["prompt_history"] = {}

if "snowpark" not in st.session_state or st.session_state.snowpark is None:
    st.session_state.snowpark = Session.builder.configs(connection_parameters).create()

    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowpark_connection": snowpark,
    }

    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "SEMANTICS",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowpark_connection": snowpark,
    }

    # Tools Config
    st.session_state.annual_reports = CortexSearchTool(**search_config)
    st.session_state.sp500 = CortexAnalystTool(**analyst_config)
    st.session_state.news_search = PythonTool(**python_config)
    st.session_state.snowflake_tools = [
        st.session_state.annual_reports,
        st.session_state.sp500,
        st.session_state.news_search,
    ]


if "analyst" not in st.session_state:
    st.session_state.analyst = CortexCube(
        snowpark_session=st.session_state.snowpark,
        tools=st.session_state.snowflake_tools,
    )


def create_prompt(prompt_key: str):
    if prompt_key in st.session_state:
        prompt_record = dict(prompt=st.session_state[prompt_key], response="waiting")
        st.session_state["prompt_history"][str(uuid.uuid4())] = prompt_record


source_list = []

import logging


class StreamlitLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.log_buffer = io.StringIO()
        self.ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def emit(self, record):
        msg = self.format(record)
        clean_msg = self.ansi_escape.sub("", msg)
        self.log_buffer.write(clean_msg + "\n")

    def get_logs(self):
        return self.log_buffer.getvalue()

    def clear_logs(self):
        self.log_area.empty()


def setup_logging():
    root_logger = logging.getLogger()
    handler = StreamlitLogHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    return handler


# Set up logging
if "logging_setup" not in st.session_state:
    st.session_state.logging_setup = setup_logging()


def run_acall(prompt, message_queue, analyst):
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the async call
    response = loop.run_until_complete(analyst.acall(prompt))
    loop.close()

    # Restore stdout
    sys.stdout = old_stdout

    # Capture and send logs to the message queue
    output = new_stdout.getvalue()
    lines = output.split("\n")
    for line in lines:
        if line and "Running" in line and "tool" in line:
            # Extract and send the tool selection string
            tool_selection_string = extract_tool_name(line)
            message_queue.put({"tool_selection": tool_selection_string})
        elif line:
            logging.info(line)  # Log other messages
            message_queue.put(line)

    # Ensure the final output is correctly added to the queue
    message_queue.put({"output": response["output"]})


def process_message(prompt_id: str):
    prompt = st.session_state["prompt_history"][prompt_id].get("prompt")
    message_queue = queue.Queue()
    analyst = st.session_state.analyst
    log_container = st.empty()
    log_handler = setup_logging()

    def run_analysis():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(analyst.acall(prompt))
        loop.close()
        message_queue.put({"output": response["output"]})

    thread = threading.Thread(target=run_analysis)
    thread.start()

    while True:
        try:
            response = message_queue.get(timeout=0.1)
            if isinstance(response, dict) and "output" in response:
                final_response = f"{response['output']}"
                st.session_state["prompt_history"][prompt_id]["response"] = (
                    final_response
                )
                log_container.code(parse_log_message(log_handler.get_logs()))
                log_container.empty()
                yield final_response
                break
            else:
                # Handle other logs
                pass
        except queue.Empty:
            log_output = parse_log_message(log_handler.get_logs())
            if log_output is not None:
                log_container.code(log_output)
            # with st.spinner("Awaiting Response..."):
            #     pass
    st.rerun()


def extract_tool_name(statement):
    start = statement.find("Running") + len("Running") + 1
    end = statement.find("tool")
    return statement[start:end].strip()


st.markdown(
    """
    <style>
        div[data-testid="stHeader"] > img, div[data-testid="stSidebarCollapsedControl"] > img {
            height: 2rem;
            width: auto;
        }
        div[data-testid="stHeader"], div[data-testid="stHeader"] > *,
        div[data-testid="stSidebarCollapsedControl"], div[data-testid="stSidebarCollapsedControl"] > * {
            display: flex;
            align-items: center;
        }
    </style>
""",
    unsafe_allow_html=True,
)

st.logo("SIT_logo_white.png")

st.markdown(
    "<h1>🧠 Snowflake Cortex<sup style='font-size:.8em;'>3</sup></h1>",
    unsafe_allow_html=True,
)
st.caption(
    "A Multi-Agent System with access to Cortex, Cortex Search, Cortex Analyst, and more."
)

for id in st.session_state.prompt_history:
    current_prompt = st.session_state.prompt_history.get(id)

    with st.chat_message("user"):
        st.write(current_prompt.get("prompt"))

    with st.chat_message("assistant"):
        if current_prompt.get("response") == "waiting":
            # Create containers for tool selection and response
            tool_info_container = st.empty()
            response_container = st.empty()

            # Start processing messages
            message_generator = process_message(prompt_id=id)

            # Use a spinner while processing
            with st.spinner("Awaiting Response..."):
                for response in message_generator:
                    if "Using" in response:
                        tool_info_container.markdown(f"**{response}**")
                    else:
                        # Clear tool info once final response is ready
                        tool_info_container.empty()
                        response_container.markdown(response)
        else:
            # Display the final response
            st.markdown(
                st.session_state["prompt_history"][id]["response"],
                unsafe_allow_html=True,
            )

st.chat_input(
    "Ask Anything", on_submit=create_prompt, key="chat_input", args=["chat_input"]
)
