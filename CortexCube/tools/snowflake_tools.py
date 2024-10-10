from CortexCube.agents.tools import Tool
import dspy
from typing import Any, Type
from pydantic import BaseModel, Field, ValidationError
from snowflake.snowpark.functions import col
import aiohttp
import asyncio
import re
import json
import inspect


class CortexSearchTool(Tool):
    """Cortex Search tool for use with SnowflakeCortexCube"""

    k: int = 5
    retrieval_columns: list = []
    service_name: str = ""
    session: object = None
    auto_filter: bool = False
    filter_generator: object = None

    def __init__(self, config, k=5):

        tool_description = self._prepare_search_description(
            service_topic=config["service_topic"],
            data_source_description=config["data_description"],
        )
        super().__init__(
            name="cortexsearch", description=tool_description, func=self.asearch
        )
        self.auto_filter = config["auto_filter"]
        self.session = config["snowpark_connection"]
        if self.auto_filter:
            self.filter_generator = SmartSearch()
            lm = dspy.Snowflake(session=self.session, model="mixtral-8x7b")
            dspy.settings.configure(lm=lm)

        self.k = k
        self.retrieval_columns = config["retrieval_columns"]
        self.service_name = config["service_name"]
        print(f"Cortex Search Tool successfully initialized")

    def __call__(self, question) -> Any:

        return self.asearch(question)

    async def asearch(self, query):

        print("Running Cortex Search tool.....")
        headers, url, data = self._prepare_request(query=query)
        async with aiohttp.ClientSession(
            headers=headers,
        ) as session:
            async with session.post(url=url, json=data) as response:
                response_text = await response.text()

                return json.loads(response_text)["results"]

    def _prepare_request(self, query):

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{self.session.connection.rest.token}"',
        }

        url = f"""https://{self.session.connection.host}/api/v2/databases/{self.session.get_current_database().replace('"', '')}/schemas/{self.session.get_current_schema().replace('"', '')}/cortex-search-services/{self.service_name}:query"""

        if self.auto_filter:
            search_attributes, sample_vals = self._get_sample_values(
                snowpark_session=self.session, cortex_search_service=self.service_name
            )
            raw_filter = self.filter_generator(
                query=query,
                attributes=str(search_attributes),
                sample_values=str(sample_vals),
            )["answer"]
            filter = json.loads(raw_filter)
        else:
            filter = None

        data = {
            "query": query,
            "columns": self.retrieval_columns,
            "limit": self.k,
            "filter": filter,
        }

        return headers, url, data

    def _prepare_search_description(self, service_topic, data_source_description):

        base_description = f""""cortexsearch(query: str) -> list:\n
                 - Executes a search for relevant information about {service_topic}.\n
                 - Returns a list of relevant passages from {data_source_description}.\n"""

        return base_description

    def _generate_search_filter(self, cortex_search_service, query, columns, k):
        """Cortex Search Query with automatic metadata filter generation."""
        self._get_s

    def _get_search_attributes(self, snowpark_session, search_service_name):
        df = snowpark_session.sql("SHOW CORTEX SEARCH SERVICES")
        raw_atts = (
            df.where(col('"name"') == search_service_name)
            .select('"attribute_columns"')
            .to_pandas()
            .loc[0]
            .values[0]
        )
        attribute_list = raw_atts.split(",")

        return attribute_list

    def _get_search_table(self, snowpark_session, search_service_name):
        df = snowpark_session.sql("SHOW CORTEX SEARCH SERVICES")
        table_def = (
            df.where(col('"name"') == search_service_name)
            .select('"definition"')
            .to_pandas()
            .loc[0]
            .values[0]
        )

        pattern = r"FROM\s+([\w\.]+)"
        match = re.search(pattern, table_def)

        if match:
            from_value = match.group(1)
            return from_value
        else:
            print("No match found.")

        return table_def

    def _get_sample_values(
        self, snowpark_session, cortex_search_service, max_samples=10
    ):
        sample_values = {}
        attributes = self._get_search_attributes(
            snowpark_session=snowpark_session, search_service_name=cortex_search_service
        )
        table_name = self._get_search_table(
            snowpark_session=snowpark_session, search_service_name=cortex_search_service
        )

        for attribute in attributes:
            query = f"""SELECT DISTINCT({attribute}) FROM {table_name} LIMIT {max_samples}"""
            sample_values[attribute] = list(
                snowpark_session.sql(query).to_pandas()[attribute].values
            )

        return attributes, sample_values


def get_min_length(model: Type[BaseModel]):
    min_length = 0
    for key, field in model.model_fields.items():
        if issubclass(field.annotation, BaseModel):
            min_length += get_min_length(field.annotation)
        min_length += len(key)
    return min_length


class JSONFilter(BaseModel):
    answer: str = Field(description="The filter_query in valid JSON format")

    @classmethod
    def model_validate_json(
        cls,
        json_data: str,
        *,
        strict: bool | None = None,
        context: dict[str, Any] | None = None,
    ):
        __tracebackhide__ = True
        try:
            return cls.__pydantic_validator__.validate_json(
                json_data, strict=strict, context=context
            )
        except ValidationError:
            min_length = get_min_length(cls)
            for substring_length in range(len(json_data), min_length - 1, -1):
                for start in range(len(json_data) - substring_length + 1):
                    substring = json_data[start : start + substring_length]
                    try:
                        res = cls.__pydantic_validator__.validate_json(
                            substring, strict=strict, context=context
                        )
                        return res
                    except ValidationError:
                        pass
        raise ValueError("Could not find valid json")


class GenerateFilter(dspy.Signature):
    """
    Given a query, attributes in the data, and example values of each attribute, generate a filter in valid JSON format.
    Ensure the filter only uses valid operators: @eq, @contains,@and,@or,@not
    Ensure only the valid JSON is output with no other reasoning.

    ---
    Query: What was the sentiment of CEOs between 2021 and 2024?
    Attributes: industry,hq,date
    Sample Values: {"industry":["biotechnology","healthcare","agriculture"],"HQ":["NY, US","CA,US","FL,US"],"date":["01/01,1999","01/01/2024"]}
    Answer: {"@or":[{"@eq":{"year":"2021"}},{"@eq":{"year":"2022"}},{"@eq":{"year":"2023"}},{"@eq":{"year":"2024"}}]}

    Query: Wha is the sentiment of Biotech CEO's of companies based in New York?
    Attributes: industry,hq,date
    Sample Values: {"industry":["biotechnology","healthcare","agriculture"],"HQ":["NY, US","CA,US","FL,US"],"date":["01/01,1999","01/01/2024"]}
    Answer: {"@and": [ { "@eq": { "industry"": "biotechnology" } }, { "@eq": { "HQ": "NY,US" } }]}

    Query: What is the sentiment of Biotech CEOs outside of California?
    Attributes: industry,hq,date
    Sample Values: {"industry":["biotechnology","healthcare","agriculture"],"HQ":["NY, US","CA,US","FL,US"],"date":["01/01,1999","01/01/2024"]}
    Answer: {"@and":[{ "@eq": { "industry": "biotechnology" } },{"@not":{"@eq":{"HQ":"CA,US"}}}]}

    Query: What is the sentiment of Biotech CEOs outside of California?
    Attributes: industry,hq,date
    Sample Values: {"industry":["biotechnology","healthcare","agriculture"],"HQ":["NY, US","CA,US","FL,US"],"date":["01/01,1999","01/01/2024"]}
    Answer: {"@and":[{ "@eq": { "industry": "biotechnology" } },{"@not":{"@eq":{"HQ":"CA,US"}}}]}

    Query: What is sentiment towards ag and biotech companies based outside of the US?
    Attributes: industry,hq,date
    Sample Values: {"industry"":["biotechnology","healthcare","agriculture"],"COUNTRY":["United States","Ireland","Russia","Georgia","Spain"],"month":["01","02","03","06","11","12""],""year"":["2022","2023","2024"]}
    Answer:{"@and": [{ "@or": [{"@eq":{ "industry": "biotechnology" } },{"@eq":{"industry":"agriculture"}}]},{ "@not": {"@eq": { "COUNTRY": "United States" } }}]}

    """

    query = dspy.InputField(desc="user query")
    attributes = dspy.InputField(desc="attributes to filter on")
    sample_values = dspy.InputField(desc="examples of values per attribute")
    answer: JSONFilter = dspy.OutputField(
        desc="filter query in valid JSON format. ONLY output the filter query in JSON, no reasoning"
    )


class SmartSearch(dspy.Module):
    def __init__(self):
        super().__init__()
        self.filter_gen = dspy.ChainOfThought(GenerateFilter)

    def forward(self, query, attributes, sample_values):
        filter_query = self.filter_gen(
            query=query, attributes=attributes, sample_values=sample_values
        )

        return filter_query


class CortexAnalystTool(Tool):
    """""Cortex Analyst tool for use with SnowflakeCortexCube""" ""

    STAGE: str = ""
    FILE: str = ""
    CONN: object = None
    name: str = ""

    def __init__(self, config) -> None:

        tool_description = self._prepare_analyst_description(
            connection=config["snowpark_connection"],
            service_topic=config["service_topic"],
            data_source_description=config["data_description"],
        )
        tool_name = f"""{config["snowpark_connection"].get_current_schema().replace('"',"")}_cortexanalyst"""
        super().__init__(
            name=tool_name, func=self.asearch, description=tool_description
        )
        self.CONN = config["snowpark_connection"]
        self.FILE = config["semantic_model"]
        self.STAGE = config["stage"]

        print(f"Cortex Analyst Tool succesfully initialized")

    def __call__(self, prompt) -> Any:

        for _ in range(3):
            current_prompt = prompt
            response = self._process_message(prompt=current_prompt)

            if response == "Invalid Query":
                rephrase_prompt = dspy.ChainOfThought(PromptRephrase)
                current_prompt = rephrase_prompt(user_prompt=prompt)["rephrased_prompt"]
            else:
                break

        return response

    async def asearch(self, query):
        print("Running Cortex Analyst tool.....")

        for _ in range(3):
            current_query = query
            url, headers, data = self._prepare_analyst_request(prompt=query)

            async with aiohttp.ClientSession(
                headers=headers,
            ) as session:
                async with session.post(url=url, json=data) as response:
                    response_text = await response.text()
                    resp = json.loads(response_text)["message"]["content"]

            if resp == "Invalid Query":
                rephrase_prompt = dspy.ChainOfThought(PromptRephrase)
                current_query = rephrase_prompt(user_prompt=current_query)[
                    "rephrased_prompt"
                ]
            else:
                break

        query_response = self._process_message(resp)

        return query_response

    def _prepare_analyst_request(self, prompt):

        data = {
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
            "semantic_model_file": f"""@{self.CONN.get_current_database().replace('"',"")}.{self.CONN.get_current_schema().replace('"',"")}.{self.STAGE}/{self.FILE}""",
        }

        url = f"""https://{self.CONN.connection._host.replace('"',"")}/api/v2/cortex/analyst/message"""

        headers = {
            "Authorization": f'Snowflake Token="{self.CONN.connection.rest.token}"',
            "Content-Type": "application/json",
        }

        return url, headers, data

    def _process_message(self, response):

        # If Valid SQL is present in Cortex Analyst Response execute the query
        if "sql" == response[1]["type"]:
            sql_query = response[1]["statement"]
            query_response = self.CONN.sql(sql_query).to_pandas()
            return str(query_response)
        else:
            return "Invalid Query"

    def _prepare_analyst_description(
        self, connection, service_topic, data_source_description
    ):

        base_analyst_description = f"""{connection.get_current_schema().replace('"','')}_cortexanalyst(prompt: str) -> str:\n
                  - takes a user's question about {service_topic } and queries {data_source_description}\n
                  - Returns the relevant metrics about {service_topic}\n"""

        return base_analyst_description


class PromptRephrase(dspy.Signature):
    """Takes in a prompt and rephrases it using context into to a single concise, and specific question.
    If there are references to entities that are not clear or consistent with the question being asked, make the references more appropriate.
    """

    # previous_response = dspy.InputField(desc="previous cortex analyst response")
    user_prompt = dspy.InputField(desc="original user prompt")
    rephrased_prompt = dspy.OutputField(
        desc="rephrased prompt with more clear and specific intent"
    )


class PythonTool(Tool):
    python_callable: object = None

    def __init__(self, python_func, tool_description, output_description) -> None:
        python_callable = self.asyncify(python_func)
        desc = self._generate_description(
            python_func=python_func,
            tool_description=tool_description,
            output_description=output_description,
        )
        super().__init__(
            name=python_func.__name__, func=python_callable, description=desc
        )
        self.python_callable = python_func
        print("Python Tool successfully initialized")

    def asyncify(self, sync_func):
        async def async_func(*args, **kwargs):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, sync_func, *args, **kwargs)

        return async_func

    def _generate_description(self, python_func, tool_description, output_description):

        full_sig = self._process_full_signature(python_func=python_func)
        return f"""{full_sig}\n - {tool_description}\n - {output_description}"""

    def _process_full_signature(self, python_func):

        name = python_func.__name__
        signature = str(inspect.signature(python_func))
        return name + signature
