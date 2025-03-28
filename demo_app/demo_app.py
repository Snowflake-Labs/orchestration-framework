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
import io
import logging
import os
import queue
import re
import sys
import threading
import uuid
import warnings
import requests

from agent_gateway.tools.utils import _determine_runtime

import streamlit as st
from dotenv import load_dotenv
from snowflake.snowpark import Session

from agent_gateway import Agent
from agent_gateway.tools import CortexAnalystTool, CortexSearchTool, PythonTool
from agent_gateway.tools.utils import parse_log_message

warnings.filterwarnings("ignore")
load_dotenv()
st.set_page_config(page_title="Agent Gateway")

connection_parameters = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
    "database": os.getenv("SNOWFLAKE_DATABASE"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA"),
}

if _determine_runtime():
    connection_parameters = connection_parameters | {
        "host": os.getenv("SNOWFLAKE_HOST"),
        "authenticator": "oauth",
    }
    with open("/snowflake/session/token") as token_file:
        connection_parameters["token"] = token_file.read()
else:
    connection_parameters = connection_parameters | {
        "user": os.getenv("SNOWFLAKE_USER"),
        "password": os.getenv("SNOWFLAKE_PASSWORD"),
    }


def html_crawl(url):
    response = requests.get(url)
    return response.text


python_crawler_config = {
    "tool_description": "reads the html from a given URL or website",
    "output_description": "html of a webpage",
    "python_func": html_crawl,
}

if "prompt_history" not in st.session_state:
    st.session_state["prompt_history"] = {}

if "snowpark" not in st.session_state or st.session_state.snowpark is None:
    st.session_state.snowpark = Session.builder.configs(
        connection_parameters
    ).getOrCreate()

    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK", "RELATIVE_PATH"],
        "snowflake_connection": st.session_state.snowpark,
    }

    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "ANALYST",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowflake_connection": st.session_state.snowpark,
    }

    # Tools Config
    st.session_state.crawler = PythonTool(**python_crawler_config)
    st.session_state.search = CortexSearchTool(**search_config)
    st.session_state.analyst = CortexAnalystTool(**analyst_config)

    st.session_state.snowflake_tools = [
        st.session_state.search,
        st.session_state.analyst,
        st.session_state.crawler,
    ]

if "agent" not in st.session_state:
    st.session_state.agent = Agent(
        snowflake_connection=st.session_state.snowpark,
        tools=st.session_state.snowflake_tools,
    )


def create_prompt(prompt_key: str):
    if prompt_key in st.session_state:
        prompt_record = dict(prompt=st.session_state[prompt_key], response="waiting")
        st.session_state["prompt_history"][str(uuid.uuid4())] = prompt_record


source_list = []


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

    def process_logs(self):
        raw_logs = self.get_logs()
        lines = raw_logs.strip().split("\n")
        log_output = [parse_log_message(line.strip()) for line in lines if line.strip()]
        cleaned_output = [line for line in log_output if line is not None]
        all_logs = "\n".join(cleaned_output)
        return all_logs

    def clear_logs(self):
        self.log_buffer = io.StringIO()


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
    st.logger = logging.getLogger("AgentGatewayLogger")
    st.logger.propagate = True


def run_acall(prompt, message_queue, agent):
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the async call
    response = loop.run_until_complete(agent.acall(prompt))
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
    message_queue.put(response)


def process_message(prompt_id: str):
    prompt = st.session_state["prompt_history"][prompt_id].get("prompt")
    message_queue = queue.Queue()
    agent = st.session_state.agent
    log_container = st.empty()
    log_handler = setup_logging()

    def run_analysis():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(agent.acall(prompt))
        loop.close()
        message_queue.put(response)

    thread = threading.Thread(target=run_analysis)
    thread.start()

    while True:
        try:
            response = message_queue.get(timeout=1)
            if isinstance(response, dict) and "output" in response:
                final_response = response
                st.session_state["prompt_history"][prompt_id]["response"] = (
                    final_response["output"]
                )
                st.session_state["prompt_history"][prompt_id]["sources"] = (
                    final_response["sources"]
                )
                logs = log_handler.process_logs()
                if logs:
                    log_container.code(logs)
                log_container.empty()
                yield final_response
                break
            else:
                logs = log_handler.process_logs()
                if logs:
                    log_container.code(logs)

        except queue.Empty:
            logs = log_handler.process_logs()
            if logs:
                log_container.code(logs)
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

st.markdown("## 🧠 Snowflake Agent Gateway \n\n\n")
st.markdown("</div>", unsafe_allow_html=True)

with st.container(border=False):
    st.markdown(
        """
    <style>
    [data-testid="stContainer"] {
        height: 70vh !important;
        overflow-y: auto;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )
    for id in st.session_state.prompt_history:
        current_prompt = st.session_state.prompt_history.get(id)

        with st.chat_message("user"):
            st.write(current_prompt.get("prompt"))

        with st.chat_message("assistant"):
            response_container = st.empty()
            if current_prompt.get("response") == "waiting":
                # Start processing messages
                message_generator = process_message(prompt_id=id)

                with st.spinner("Awaiting Response..."):
                    for response in message_generator:
                        response_container.text(response)
            else:
                # Display the final response
                response_container.markdown(
                    current_prompt["response"],
                    unsafe_allow_html=True,
                )
                # Add sources section aligned to the right
                if current_prompt.get("sources") is not None:
                    citations_metadata = [
                        source["metadata"] for source in current_prompt.get("sources")
                    ]

                    sources = []
                    for item in citations_metadata:
                        if (
                            item is not None
                            and isinstance(item, list)
                            and len(item) > 0
                        ):
                            first_element = item[0]
                            if (
                                isinstance(first_element, dict)
                                and len(first_element) > 0
                            ):
                                sources.append(next(iter(first_element.values())))

                    # Filter out None values in sources list
                    sources = [source for source in sources if source is not None]

                    # Determine the sources to display
                    sources_display = ", ".join(sources) if sources else "N/A"

                    st.markdown(
                        f"""
                        <div style="text-align: right; font-size: 0.8em; font-style: italic; margin-top: 5px;">
                            <b>Sources</b>: {sources_display}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


st.chat_input(
    "Ask Anything", on_submit=create_prompt, key="chat_input", args=["chat_input"]
)
