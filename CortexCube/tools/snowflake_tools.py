import dspy
from typing import Any
from CortexCube.agents.tools import Tool
import aiohttp, asyncio
import json, inspect


class CortexSearchTool(Tool):
    """Cortex Search tool for use with SnowflakeCortexCube"""
    k: int = 5
    retrieval_columns: list = []
    service_name : str = ""
    session: object = None

    def __init__(self,config,k=5):

        tool_description = self._prepare_search_description(service_topic=config["service_topic"],data_source_description=config["data_description"])
        super().__init__(name="cortexsearch",description=tool_description,func=self.asearch)
        self.session = config["snowpark_connection"]
        self.k = k
        self.retrieval_columns = config["retrieval_columns"]
        self.service_name = config["service_name"]
        print(f"Cortex Search Tool succesfully initialized")
             
    def __call__(self,question) -> Any:

        return self.asearch(question)
    
    async def asearch(self, query):

        print("Running Cortex Search tool.....")
        headers,url,data =self._prepare_request(query=query)
        async with aiohttp.ClientSession(headers=headers,) as session:
            async with session.post(url=url,json=data) as response:
                response_text = await response.text()
                
                return json.loads(response_text)['results']
    
    def _prepare_request(self,query):

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f'Snowflake Token="{self.session.connection.rest.token}"'}
        
        url = f"""https://{self.session.connection.host}/api/v2/databases/{self.session.get_current_database().replace('"', '')}/schemas/{self.session.get_current_schema().replace('"', '')}/cortex-search-services/{self.service_name}:query"""
       
        data = {
            "query": query,
            "columns": self.retrieval_columns,
            "limit": self.k}
        
        return headers,url,data
    
    
    def _prepare_search_description(self,service_topic,data_source_description):

        base_description = f""""cortexsearch(query: str) -> list:\n
                 - Executes a search for relevant information about {service_topic}.\n
                 - Returns a list of relevant passages from {data_source_description}.\n"""

        return (base_description)

    

    
class CortexAnalystTool(Tool):
    """""Cortex Analyst tool for use with SnowflakeCortexCube"""""
    STAGE : str = ""
    FILE: str = ""
    CONN: object = None
    name: str = ""


    def __init__(self,config) -> None:

        tool_description = self._prepare_analyst_description(connection=config["snowpark_connection"],
                                                             service_topic=config["service_topic"],
                                                             data_source_description=config["data_description"])
        tool_name = f"""{config["snowpark_connection"].get_current_schema().replace('"',"")}_cortexanalyst"""
        super().__init__(name=tool_name,func=self.asearch,description=tool_description)
        self.CONN = config["snowpark_connection"]
        self.FILE = config["semantic_model"]
        self.STAGE = config["stage"]
        
  
        print(f"Cortex Analyst Tool succesfully initialized")
        
    def __call__(self,prompt) -> Any:
        
        for _ in range(3):
            current_prompt  = prompt
            response = self._process_message(prompt=current_prompt)
            
            if response == "Invalid Query":
                rephrase_prompt = dspy.ChainOfThought(PromptRephrase)
                current_prompt = rephrase_prompt(user_prompt=prompt)['rephrased_prompt']
            else:
                break

        return response
    

    async def asearch(self,query):
        print("Running Cortex Analyst tool.....")

        for _ in range(3):
            current_query = query
            url,headers,data = self._prepare_analyst_request(prompt=query)

            async with aiohttp.ClientSession(headers=headers,) as session:
                async with session.post(url=url,json=data) as response:
                    response_text = await response.text()
                    resp =  json.loads(response_text)['message']['content']
            
            if resp == "Invalid Query":
                rephrase_prompt = dspy.ChainOfThought(PromptRephrase)
                current_query = rephrase_prompt(user_prompt=current_query)['rephrased_prompt']
            else:
                break

        query_response = self._process_message(resp)

        return query_response


    def _prepare_analyst_request(self,prompt):

        data = {"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "semantic_model_file": f"""@{self.CONN.get_current_database().replace('"',"")}.{self.CONN.get_current_schema().replace('"',"")}.{self.STAGE}/{self.FILE}"""}
        
        url = f"""https://{self.CONN.connection._host.replace('"',"")}/api/v2/cortex/analyst/message"""

        headers= {"Authorization": f'Snowflake Token="{self.CONN.connection.rest.token}"',
                    "Content-Type": "application/json"}
        
        return url,headers,data
    

    def _process_message(self,response):

        # If Valid SQL is present in Cortex Analyst Response execute the query
        if 'sql' == response[1]['type']:
            sql_query = response[1]['statement']
            query_response = self.CONN.sql(sql_query).to_pandas()
            return str(query_response)
        else:
            return "Invalid Query"
        
    def _prepare_analyst_description(self,connection,service_topic,data_source_description):

        base_analyst_description =  f"""{connection.get_current_schema().replace('"','')}_cortexanalyst(prompt: str) -> str:\n
                  - takes a user's question about {service_topic } and queries {data_source_description}\n
                  - Returns the relevant metrics about {service_topic}\n"""
        
        return (base_analyst_description)



class PromptRephrase(dspy.Signature):
    """Takes in a prompt and rephrases it using context into to a single concise, and specific question.
    If there are references to entities that are not clear or consistent with the question being asked, make the references more appropriate.
    """
    #previous_response = dspy.InputField(desc="previous cortex analyst response")
    user_prompt = dspy.InputField(desc="original user prompt")
    rephrased_prompt = dspy.OutputField(desc="rephrased prompt with more clear and specific intent")



class PythonTool(Tool):
    python_callable: object = None

    def __init__(self,python_func,tool_description,output_description) -> None:
        python_callable = self.asyncify(python_func)
        desc = self._generate_description(python_func=python_func,tool_description=tool_description,output_description=output_description)
        super().__init__(name=python_func.__name__,func=python_callable,description=desc)
        self.python_callable = python_func
        print("Python Tool succesfully initialized")


    def asyncify(self,sync_func):
        async def async_func(*args, **kwargs):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, sync_func, *args, **kwargs)
        return async_func

    def _generate_description(self,python_func,tool_description,output_description):

        full_sig = self._process_full_signature(python_func=python_func)
        return f"""{full_sig}\n - {tool_description}\n - {output_description}"""

    def _process_full_signature(self,python_func):
         
         name = python_func.__name__
         signature =  str(inspect.signature(python_func))
         return name+signature

