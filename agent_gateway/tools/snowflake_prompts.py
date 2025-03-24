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
from __future__ import annotations

from agent_gateway.gateway.constants import END_OF_PLAN, FUSION_FINISH, FUSION_REPLAN

PLANNER_PROMPT = (
    "Question: Give me a summary of the financials of Snowflake's competitors\n"
    "Thought: I need to identify which companies are considered Snowflake's competitors.\n"
    '1. cortexsearch("Companies that are considered Snowflake competitors")\n'
    "Thought: I need to find the financials of the $competitors identified in the annual report.\n"
    '2. cortexanalyst("Give me summary statistics of the financials of the $competitors")\n'
    "Thought: I can answer the question now.\n"
    f"3. fuse(){END_OF_PLAN}\n"
    "###\n"
    "Question: What is the EBITDA of Berkshire Hathaway?\n"
    "Thought: I need to get financial metrics from an S&P500 company.\n"
    '1. cortexanalyst("What is the EBITDA of Berkshire Hathaway?")\n'
    "Thought: I can answer the question now.\n"
    f"2. fuse(){END_OF_PLAN}\n"
    "###\n"
    "Question: What is the Revenue of the competitors mentioned in Snowflake's annual report?\n"
    "Thought: I first nneed to identify which companies are considered Snowflake's competitors.\n"
    '1. cortexsearch("Snowflake competitors mentioned in the annual report")\n'
    "Thought: Now that I know the competitors, I can look up their financials in my database, if they're in the S&P500.\n"
    '2. cortexanalyst("What is the Revenue of Amazon, Microsoft, and Google?")\n'
    "Thought: I can answer the question now.\n"
    f"3. fuse(){END_OF_PLAN}\n"
)


OUTPUT_PROMPT = (
    "You must solve the Question. You are given Observations and you can use them to solve the Question. "
    "Then you MUST provide a Thought, and then an Action. Do not use any parenthesis.\n"
    "You will be given a question either some passages or numbers, which are observations.\n\n"
    "Thought step can reason about the observations in 1-2 sentences, and Action can be only one type:\n"
    f" (1) {FUSION_FINISH}(answer): returns the answer and finishes the task using information you found from observations."
    f" (2) {FUSION_REPLAN}: returns the original user's question, clarifying questions or comments about why it wasn't answered, and replans in order to get the information needed to answer the question."
    "\n"
    "Follow the guidelines that you will die if you don't follow:\n"
    "  - Answer should be directly answer the question.\n"
    "  - Thought should be 1-2 sentences.\n"
    "  - Action can only be Finish or Replan\n"
    "  - Action should be Finish if you have enough information to answer the question\n"
    "  - Action Should be Replan if you don't have enough information to answer the question\n"
    "  - You must say <END_OF_RESPONSE> at the end of your response.\n"
    "  - If the user's question is too vague or unclear, say why and ask for clarification.\n"
    "  - If the correct tool is used, but the information does not exist, then let the user know.\n"
    "\n"
    "\n"
    "Here are some examples:\n"
    "\n"
    "Question: What is the EBITDA of Berkshire Hathaway?\n"
    "cortexanalyst('What is the EBITDA of Berkshire Hathaway?')\n"
    "Observation:   SYMBOL                    SHORTNAME  START_DATE  END_DATE        EBITDA\n0  BRK-B  Berkshire Hathaway Inc. New      413.72    413.72  107046002688\n"
    "Thought: Berkshire Hathaway's latest EBITDA is $107,046,002,688, or $107 Billion.\n"
    f"Action: {FUSION_FINISH}(Berkshire's latest EBITDA is $107 Billion.)\n"
    "<END_OF_RESPONSE>\n"
    "\n"
    "\n"
    "Question: What is the stock price of the neighborhood laundromat?\n"
    "cortexanalyst('What is the EBITDA of the neighborhood laundromat?')\n"
    "Observation: Apologies, but the question 'What is the market cap of the neighborhood laundromat?' is unclear because the company neighborhood laundromat is not specified in the provided semantic data model. The model does not include a company with the name neighborhood laundromate, and without additional information, it is not possible to determine which company the user is referring to.\n"
    "Thought: The information requested does not exist in the available tools.\n"
    f"Action: {FUSION_REPLAN}(No data is available for the neighborhood laundromat. Please consider rephrasing your request to be more specific, or contact your administrator to confirm that the system contains the relevant information.)\n"
    "<END_OF_RESPONSE>\n"
    "\n"
    "\n"
    "Question: What is the latest news about Berkshire Hathaway?\n"
    "newstool(Berkshire Hathaway)\n"
    "Observation: '[{'uuid': 'c177ede5-07a7-4f63-a3b7-52790c8fd08e', 'title': 'Berkshire Hathaway-berkshire Hathaway Inc -- Berkshire Says It H…', 'description': 'BERKSHIRE HATHAWAY-BERKSHIRE HATHAWAY INC -- BERKSHIRE SAYS IT HAD $147.4 BLN OF CASH AND EQUIVALENTS AS OF JUNE 30...', 'keywords': 'Markets', 'snippet': \"Berkshire Hathaway Inc. (Berkshire) is a holding company owning subsidiaries engaged in various business activities. Berkshire's various business activities inc...",
    "url': 'https://www.marketscreener.com/quote/stock/BERKSHIRE-HATHAWAY-INC-11915/news/BERKSHIRE-HATHAWAY-BERKSHIRE-HATHAWAY-INC-BERKSHIRE-SAYS-IT-H-8230-44531571/', 'image_url': 'https://www.marketscreener.com/images/twitter_MS_fdblanc.png', 'language': 'en', 'published_at': '2023-08-05T12:15:15.000000Z', 'source': 'marketscreener.com', 'categories': ['business'], 'relevance_score': 55.634586}, {'uuid': '56202cf0-38af-4a20-b411-994c92d8c7cd', 'title': 'Berkshire Hathaway Inc. (OTCMKTS:BRK-A) Major Shareholder Berkshire Hathaway Inc Acquires 716,355 Shares', 'description': 'Read Berkshire Hathaway Inc. (OTCMKTS:BRK-A) Major Shareholder Berkshire Hathaway Inc Acquires 716,355 Shares at ETF Daily News', 'keywords': 'Berkshire Hathaway, OTCMKTS:BRK-A, BRK-A, Financial Service, Insider Trading, Insider Trades, Stocks', 'snippet': 'Berkshire Hathaway Inc. (OTCMKTS:BRK-A – Get Rating) major shareholder Berkshire Hathaway Inc bought 716,355 shares of Berkshire Hathaway stock in a transacti...', 'url': 'https://www.etfdailynews.com/2022/05/13/berkshire-hathaway-inc-otcmktsbrk-a-major-shareholder-berkshire-hathaway-inc-acquires-716355-shares/', 'image_url': 'https://www.americanbankingnews.com/wp-content/timthumb/timthumb.php?src=https://www.marketbeat.com/logos/berkshire-hathaway-inc-logo.png?v=20211203153558&w=240&h=240&zc=2', 'language': 'en', 'published_at': '2022-05-13T11:18:50.000000Z', 'source': 'etfdailynews.com', 'categories': ['business'], 'relevance_score': 53.612434}]"
    "\n"
    "Thought: The recent news about Berkshire Hathaway include information about its financials and recent activities.\n"
    f"Action: {FUSION_FINISH}('Recent news about Berkshire Hathaways includes:\n- Article: Berkshire Hathaway-Berkshire Hathaway Inc -- Berkshire Says It H…  Source: [Market Screener](https://www.marketscreener.com/quote/stock/BERKSHIRE-HATHAWAY-INC-11915/news/BERKSHIRE-HATHAWAY-BERKSHIRE-HATHAWAY-INC-BERKSHIRE-SAYS-IT-H-8230-44531571/) \n - Article: Berkshire Hathaway Inc. (OTCMKTS:BRK-A) Major Shareholder Berkshire Hathaway Inc Acquires 716,355 Shares' Source: [ETF Daily News](https://www.etfdailynews.com/2022/05/13/berkshire-hathaway-inc-otcmktsbrk-a-major-shareholder-berkshire-hathaway-inc-acquires-716355-shares/)) '\n"
    "<END_OF_RESPONSE>\n"
    "\n"
    "\n"
    "Question: How many queries are processed on Snowflake's platform?\n"
    "cortexsearch(How many queries are processed on Snowflake's platform?)\n"
    "Observation: ['deliver the Data Cloud, enabling a consistent, global user experience.\nOur platform supports a wide range of workloads that enable our customers’ most important business objectives, including data warehousing, data lakes, data engineering, data\nscience, data application development, and data sharing. From January 1, 2022 to January 31, 2022, we processed an average of over 1,496 million daily queries across all of our\ncustomer accounts, up from an average of over 777 million daily queries during the corresponding month of the prior fiscal year. We also recently launched our Powered by\nSnowflake program to help companies build, operate, and grow applications in the Data Cloud by supporting developers across all stages of the application journey. Members of the\nprogram have access to go-to-market, customer support, and engineering expertise.\nWe have an industry-vertical focus, which allows us to go to market with tailored business solutions. For example, we have launched the Financial Services Data Cloud, the\nMedia Data Cloud, the Healthcare and Life Sciences Data Cloud, and the Retail Data Cloud. Each of these Data Clouds brings together Snowflake’s platform capabilities with\nindustry-specific partner solutions and datasets to drive business growth and deliver improved experiences and insights.\nOur business benefits from powerful network effects. The Data Cloud will continue to grow as organizations move their siloed data from cloud-based repositories and on-\npremises data centers to the Data Cloud. The more customers adopt our platform, the more data can be exchanged with other Snowflake customers, partners, data providers, and\ndata consumers, enhancing the value of our platform for all users. We believe this network effect will help us drive our vision of the Data Cloud.\n75/14/24, 8:55 AM snow-20220131\nhttps://www.sec.gov/Archives/edgar/data/1640147/000164014722000023/snow-20220131.htm 8/183Table of Contents',"
    "'the Data Cloud, enabling a consistent, global user experience.\nOur platform supports a wide range of workloads that enable our customers’ most important business objectives, including data warehouse, data lake, data engineering, AI/ML,\napplications, collaboration, cybersecurity and Unistore. From January 1, 2024 to January 31, 2024, we processed an average of approximately 4.2 billion daily queries across all our\ncustomer accounts, up from an average of approximately 2.6 billion daily queries during the corresponding month of the prior fiscal year. We are committed to expanding our\nplatform’s use cases and supporting developers in building their applications and businesses. In 2021, we launched Snowpark for Java and Scala to allow developers to build in the\nlanguage of their choice, and in 2022 we added support for Python. In 2023, we launched Snowpark Container Services, a fully managed container platform designed to facilitate\nthe deployment, management, and scaling of containerized applications and AI/ML models within our ecosystem. We continue to invest in our Native Application program to help\ncompanies build, operate, and market applications in the Data Cloud by supporting developers across all stages of the application journey.\nWe have an industry-vertical focus, which allows us to go to market with tailored business solutions. For example, we have launched the Telecom Data Cloud, the Financial\nServices Data Cloud, the Media Data Cloud, the Healthcare and Life Sciences Data Cloud, and the Retail Data Cloud. Each of these brings together Snowflake’s platform\ncapabilities with industry-specific partner solutions and datasets to drive business growth and deliver improved experiences and insights.\nOur business benefits from powerful network effects. The Data Cloud will continue to grow as organizations move their siloed data from cloud-based repositories and on-',"
    "'Our cloud-native architecture consists of three independently scalable but logically integrated layers across compute, storage, and cloud services. The compute layer provides\ndedicated resources to enable users to simultaneously access common data sets for many use cases with minimal latency. The storage layer ingests massive amounts and varieties of\nstructured, semi-structured, and unstructured data to create a unified data record. The cloud services layer intelligently optimizes each use case’s performance requirements with no\nadministration. This architecture is built on three major public clouds across 38 regional deployments around the world. These deployments are generally interconnected to deliver\nthe Data Cloud, enabling a consistent, global user experience.\nOur platform supports a wide range of workloads that enable our customers’ most important business objectives, including data warehousing, data lakes, and Unistore, as well\nas collaboration, data engineering, cybersecurity, data science and machine learning, and application development. From January 1, 2023 to January 31, 2023, we processed an\naverage of approximately 2.6 billion daily queries across all our customer accounts, up from an average of approximately 1.5 billion daily queries during the corresponding month\nof the prior fiscal year. We are committed to expanding our platform’s use cases and supporting developers in building their applications and businesses. In 2021, we launched\nSnowpark for Java to allow developers to build in the language of their choice, and in 2022 we added support for Python. We continue to invest in our Powered by Snowflake\nprogram to help companies build, operate, and market applications in the Data Cloud by supporting developers across all stages of the application journey. As of January 31, 2023,\nwe had over 820 Powered by Snowflake registrants. Powered by Snowflake partners have access to go-to-market, customer support, and engineering expertise.',"
    "'performance comparable to a relational, structured representation.\n•Query Capabilities. Our platform is engineered to query petabytes of data. It implements support for a large subset of the ANSI SQL standard for read operations and data\nmodification operations. Our platform provides additional features, including:\n◦Time travel. Our platform keeps track of all changes happening to a table, which enables customers to query previous versions based on their preferences. Customers\ncan query as of a relative point in time or as of an absolute point in time. This has a broad array of use cases for customers, including error recovery, time-based\nanalysis, and data quality checks.5/14/24, 8:59 AM snow-20210131\nhttps://www.sec.gov/Archives/edgar/data/1640147/000164014721000073/snow-20210131.htm 17/193◦ Cloning. Our architecture enables us to offer zero-copy cloning, an operation by which entire tables, schemas, or databases can be duplicated—or cloned—without\nhaving to copy or duplicate the underlying data. Our platform leverages the separation between cloud services and storage to be able to track independent clones of\nobjects sharing the same physical copy of the underlying data. This enables a variety of customer use cases such as making copies of production data for data\nscientists, creating custom snapshots in time, or testing data pipelines.\n105/14/24, 8:59 AM snow-20210131\nhttps://www.sec.gov/Archives/edgar/data/1640147/000164014721000073/snow-20210131.htm 18/193Table of Contents\n•Compute Model. Our platform offers a variety of capabilities to operate on data, from ingestion to transformation, as well as rich query and analysis. Our compute services\nare primarily presented to users in one of two models, either through explicit specification of compute clusters we call virtual warehouses or through a number of serverless\nservices.',"
    "'performance.\n◦ Metadata. When data is ingested, our platform automatically extracts and stores metadata to speed up query processing. It does so by collecting data distribution\ninformation for all columns in every micro-partition.5/14/24, 8:55 AM snow-20240131\nhttps://www.sec.gov/Archives/edgar/data/1640147/000164014724000101/snow-20240131.htm 20/217◦Semi-structured and unstructured data. In addition to structured, relational data, our platform supports semi-structured data, including JSON, Avro, and Parquet, and\nunstructured data, including PDF documents, screenshots, recordings, and images. Data in these formats can be ingested and queried with performance comparable to a\nrelational, structured representation.\n135/14/24, 8:55 AM snow-20240131\nhttps://www.sec.gov/Archives/edgar/data/1640147/000164014724000101/snow-20240131.htm 21/217Table of Contents\n•Query Capabilities. Our platform is engineered to query petabytes of data. It implements support for a large subset of the ANSI SQL standard for read operations and data\nmodification operations. Our platform provides additional features, including:\n◦Time travel. Our platform keeps track of all changes happening to a table, which enables customers to query previous versions based on their preferences. Customers\ncan query as of a relative point in time or as of an absolute point in time. This has a broad array of use cases for customers, including error recovery, time-based\nanalysis, and data quality checks.\n◦ Cloning. Our architecture enables us to offer zero-copy cloning, an operation by which entire tables, schemas, or databases can be duplicated—or cloned—without\nhaving to copy or duplicate the underlying data. Our platform leverages the separation between cloud services and storage to be able to track independent clones of\nobjects sharing the same physical copy of the underlying data. This enables a variety of customer use cases such as making copies of production data for data']"
    "Thought: Berkshire Hathaway's latest EBITDA is $107,046,002,688, or $107 Billion.\n"
    f"Action: {FUSION_FINISH}(Based on January 2024 data, Snowflake processes an average of approximately 4.2 billion daily queries across all customer account. This is an increase up from an average of approximately 2.6 billion daily queries during the corresponding month of the prior year.)\n"
    "<END_OF_RESPONSE>\n"
    "\n"
    "\n",
)
