from dotenv import load_dotenv
from snowflake.snowpark import Session

import streamlit as st
import contextlib
import io
import json
import asyncio

import os
import uuid
import sys
import requests

from CortexCube import CortexCube, CortexAnalystTool, CortexSearchTool, PythonTool
import warnings
warnings.filterwarnings('ignore')

load_dotenv("../.env")

st.set_page_config(page_title="Snowflake Cortex Cube")

connection_parameters = {

    "account": os.getenv('SNOWFLAKE_ACCOUNT'),
    "user": os.getenv('SNOWFLAKE_USER'),
    "password": os.getenv('SNOWFLAKE_PASSWORD'),
    "role": os.getenv('SNOWFLAKE_ROLE'),
    "warehouse": os.getenv('SNOWFLAKE_WAREHOUSE'),
    "database": os.getenv('SNOWFLAKE_DATABASE'),
    "schema": os.getenv('SNOWFLAKE_SCHEMA')}


os.environ["NEWS_API_TOKEN"] = os.getenv("NEWS_API_TOKEN")
snowpark = Session.builder.configs(connection_parameters).create()

class NewsTool:

    def __init__(self, token, limit) -> None:

        self.api_token = token
        self.limit = limit

    def search(self, news_query: str) -> str:

        print("Running News Search tool....")
        news_request = f"""https://api.thenewsapi.com/v1/news/all?api_token={self.api_token}&search={news_query}&language=en&limit={self.limit}"""
        response = requests.get(news_request)
        json_response = json.loads(response.content)['data']

        return str(json_response)


tool_desc = "searches for relevant news based on user query"
output = "relevant articles"
news_api_func = NewsTool(token=os.getenv("NEWS_API_TOKEN"), limit=3).search


if 'prompt_history' not in st.session_state:
    st.session_state['prompt_history'] = {}

if 'snowpark' not in st.session_state or st.session_state.snowpark is None:

    st.session_state.snowpark = Session.builder.configs(
        connection_parameters).create()

    search_config = {
        "service_name": "SEC_SEARCH_SERVICE",
        "service_topic": "Snowflake's business,product offerings,and performance",
        "data_description": "Snowflake annual reports",
        "retrieval_columns": ["CHUNK"],
        "snowpark_connection": snowpark
    }

    analyst_config = {
        "semantic_model": "sp500_semantic_model.yaml",
        "stage": "SEMANTICS",
        "service_topic": "S&P500 company and stock metrics",
        "data_description": "a table with stock and financial metrics about S&P500 companies ",
        "snowpark_connection": snowpark
    }

    # Tools Config
    st.session_state.annual_reports = CortexSearchTool(**search_config)
    st.session_state.sp500 = CortexAnalystTool(**analyst_config)
    st.session_state.news_search = PythonTool(
        python_func=news_api_func, tool_description=tool_desc, output_description=output)
    st.session_state.snowflake_tools = [
        st.session_state.annual_reports, st.session_state.sp500, st.session_state.news_search]


if 'analyst' not in st.session_state:

    st.session_state.analyst = CortexCube(snowpark_session=st.session_state.snowpark,tools=st.session_state.snowflake_tools)


def create_prompt(prompt_key: str):

    if prompt_key in st.session_state:
        prompt_record = dict(
            prompt=st.session_state[prompt_key], response='waiting')
        st.session_state['prompt_history'][str(uuid.uuid4())] = prompt_record


class StreamlitOutputRedirector:
    def __init__(self, placeholder):
        self.buffer = io.StringIO()
        self.placeholder = placeholder

    def write(self, text):
        self.buffer.write(text)
        self.placeholder.code(self.buffer.getvalue())

    def flush(self):
        pass

    def get_output(self):
        return self.buffer.getvalue()


source_list = []


@contextlib.contextmanager
def redirect_stdout_to_streamlit(placeholder):
    redirector = StreamlitOutputRedirector(placeholder)
    old_stdout = sys.stdout
    sys.stdout = redirector
    try:
        yield redirector
    finally:
        sys.stdout = old_stdout


def process_message(prompt_id: str) -> None:
    """Processes a message and adds the response to the chat."""
    prompt = st.session_state['prompt_history'][prompt_id].get('prompt')
    output_container = st.empty()
    tool_info_container = st.empty()

    with redirect_stdout_to_streamlit(output_container) as redirector:
        # Call the analyst method and capture the output
        response = asyncio.run(
            st.session_state.analyst.acall(prompt))['output']

        # Extract tool information from the output
        lines = redirector.get_output().split('\n')
        sources = []
        for line in lines:
            tool_name = extract_tool_name(line)
            if tool_name is not None:
                sources.append(tool_name)
                # Display tool information
                # tool_info_container.write(f"Using tool: {tool_name}")

    # Construct the final response with tool information
    cleaned_sources = [source for source in set(sources) if source != '']
    source_output = ', '.join(list(set(cleaned_sources)))
    final_response = f"""{response} \n\n<span style="float:right;color:gray">Source: {source_output}</span>"""
    st.session_state['prompt_history'][prompt_id]['response'] = final_response
    st.rerun()

# def extract_tool_name(yield_string):
#     # Check if the input string matches the pattern
#     if 'tool selected' in yield_string:
#         # Extract the selected tool name
#         words = yield_string.split('tool selected')
#         selected_tool_name = words[0]  # Assuming the tool name is the first word
#         if selected_tool_name.lower() != "finish":
#             return selected_tool_name.strip()


def extract_tool_name(statement):
    start = statement.find('Running') + len('Running') + 1
    end = statement.find('tool')
    return statement[start:end].strip()


# Add custom CSS to resize the logo
st.markdown("""
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
""", unsafe_allow_html=True)

st.logo("SIT_logo_white.png")
# st.title("Cortex Multi Agent Analyst")
st.markdown(
    "<h1>🧠 Snowflake Cortex<sup style='font-size:.8em;'>3</sup></h1>",
    unsafe_allow_html=True,
)
st.caption(
    "A Multi-Agent System with access to Cortex, Cortex Search, Cortex Analyst, and more.")

# for id in st.session_state.prompt_history:

#     current_prompt = st.session_state.prompt_history.get(id)

#     with st.chat_message('user'):
#         st.write(current_prompt.get('prompt'))
#     with st.chat_message('assistant'):

#         if current_prompt.get('response') == 'waiting':

#             with st.status("Awaiting Response", expanded=True):

#                 st.write_stream(process_message(prompt_id=id))
#         else:
# st.write(st.session_state['prompt_history'][id]['response'],unsafe_allow_html=True)

for id in st.session_state.prompt_history:
    current_prompt = st.session_state.prompt_history.get(id)

    with st.chat_message('user'):
        st.write(current_prompt.get('prompt'))
    with st.chat_message('assistant'):
        if current_prompt.get('response') == 'waiting':
            with st.status("Awaiting Response", expanded=True):
                st.write_stream(process_message(prompt_id=id))
        else:
            st.write(st.session_state['prompt_history']
                     [id]['response'], unsafe_allow_html=True)


st.chat_input("Ask Anything", on_submit=create_prompt,
              key='chat_input', args=['chat_input'])
