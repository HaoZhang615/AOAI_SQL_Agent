import os
import random
from typing import Any, Dict, List, Literal, Annotated, TypedDict

import dotenv
from langchain_openai import AzureChatOpenAI
import streamlit as st
import tiktoken
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from IPython.display import Image
from langchain.agents.agent import AgentAction
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_core.outputs.llm_result import LLMResult
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langchain_core.runnables.graph import CurveStyle, MermaidDrawMethod, NodeStyles
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.prebuilt import ToolNode
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace, trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

dotenv.load_dotenv()

st.set_page_config(
    page_title="AI agentic bot that can interact with a database"
)

st.title("💬 AI agentic RAG")
st.caption("🚀 A Bot that can use an agent to retrieve, augment, generate, validate and iterate")

@st.cache_resource
def setup_tracing():
    exporter = AzureMonitorTraceExporter.from_connection_string(
        os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
    )
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)
    tracer = trace.get_tracer(__name__)
    span_processor = BatchSpanProcessor(exporter, schedule_delay_millis=60000)
    trace.get_tracer_provider().add_span_processor(span_processor)
    LangchainInstrumentor().instrument()
    return tracer

def get_session_id() -> str:
    id = random.randint(0, 1000000)
    return "00000000-0000-0000-0000-" + str(id).zfill(12)

@st.cache_resource
def create_session(st: st) -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = get_session_id()
        print("started new session: " + st.session_state["session_id"])
        st.write("You are running in session: " + st.session_state["session_id"])

tracer = setup_tracing()
create_session(st)

def num_tokens_from_messages(messages: List[str]) -> int:
    encoding = tiktoken.encoding_for_model("gpt-4")
    num_tokens = 3 #min token count for gpt-4 models. Its probably more but enough for a good estimation
    for message in messages:
        num_tokens += len(encoding.encode(message))

    return num_tokens

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for message in st.session_state.chat_history:
    if isinstance(message, HumanMessage):
        with st.chat_message("Human"):
            st.markdown(message.content)
    elif isinstance(message, AIMessage):
        with st.chat_message("AI"):
            st.markdown(message.content)
    elif isinstance(message, ToolMessage):
        with st.chat_message("Tool"):
            st.markdown(message.content)
    else:
        with st.chat_message("Agent"):
            st.markdown(message.content)

class TokenCounterCallback(BaseCallbackHandler):

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[BaseMessage]], **kwargs: Any) -> Any:
        self.prompt_tokens += num_tokens_from_messages([message.content for message in messages[0]])
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        self.completion_tokens += num_tokens_from_messages([generation.text for generation in response.generations[0]])

callback = TokenCounterCallback()

llm: AzureChatOpenAI = None
if "AZURE_OPENAI_API_KEY" in os.environ:
    llm = AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_deployment=os.getenv("AZURE_OPENAI_COMPLETION_DEPLOYMENT_NAME"),
        openai_api_version=os.getenv("AZURE_OPENAI_VERSION"),
        temperature=0,
        streaming=True,
        callbacks=[callback]
    )
else:
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    llm = AzureChatOpenAI(
        azure_ad_token_provider=token_provider,
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_COMPLETION_DEPLOYMENT_NAME"),
        openai_api_version=os.getenv("AZURE_OPENAI_VERSION"),
        temperature=0,
        openai_api_type="azure_ad",
        streaming=True,
        callbacks=[callback]
    )

driver = '{ODBC Driver 18 for SQL Server}'
odbc_str = 'mssql+pyodbc:///?odbc_connect=' \
                'Driver='+driver+ \
                ';' + os.getenv("AZURE_SQL_CONNECTIONSTRING")

db = SQLDatabase.from_uri(odbc_str)

def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks[Any, dict]:
    """
    Create a ToolNode with a fallback to handle errors and surface them to the agent.
    """
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }

toolkit = SQLDatabaseToolkit(db=db, llm=llm)
tools = toolkit.get_tools()

list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")
get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")

@tool
def db_query_tool(query: str) -> str:
    """
    Execute a SQL Server query against the database and get back the result.
    If the query is not correct, an error message will be returned.
    If an error is returned, rewrite the query, check the query, and try again.
    """
    result = db.run_no_throw(query)
    if not result:
        return "Error: Query failed. Please rewrite your query and try again."
    return result

query_check_system = """You are a SQL expert with a strong attention to detail.
Double check the SQL Server query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins
- Not using any create or drop statements

If there are any of the above mistakes, rewrite the query. If there are no mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check."""

query_check_prompt = ChatPromptTemplate.from_messages(
    [("system", query_check_system), ("placeholder", "{messages}")]
)
query_check = query_check_prompt | llm.bind_tools(
    [db_query_tool], tool_choice="required"
)

# Define the state for the agent
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# Define a new graph
workflow = StateGraph(State)


# Add a node for the first tool call
def first_tool_call(state: State) -> dict[str, list[AIMessage]]:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "sql_db_list_tables",
                        "args": {},
                        "id": "tool_abcd123",
                    }
                ],
            )
        ]
    }


def model_check_query(state: State) -> dict[str, list[AIMessage]]:
    """
    Use this tool to double-check if your query is correct before executing it.
    """
    return {"messages": [query_check.invoke({"messages": [state["messages"][-1]]})]}


workflow.add_node("first_tool_call", first_tool_call)

# Add nodes for the first two tools
workflow.add_node(
    "list_tables_tool", create_tool_node_with_fallback([list_tables_tool])
)
workflow.add_node("get_schema_tool", create_tool_node_with_fallback([get_schema_tool]))

# Add a node for a model to choose the relevant tables based on the question and available tables
model_get_schema = llm.bind_tools(
    [get_schema_tool]
)
workflow.add_node(
    "model_get_schema",
    lambda state: {
        "messages": [model_get_schema.invoke(state["messages"])],
    },
)

#-----------------------------------------------------------------------------------------------

# Add a node for a model to generate a query based on the question and schema
query_gen_system = """You are a SQL expert with a strong attention to detail.

Given an input question, output a syntactically correct SQL Server query.

When generating the query:

Unless the user specifies a specific number of examples they wish to obtain, always limit your query to at most 5 results.
You can order the results by a relevant column to return the most interesting examples in the database.
Never query for all the columns from a specific table, only ask for the relevant columns given the question.

If you have enough information to answer the input question, simply invoke the appropriate tool to submit the final answer to the user.

DO NOT make any DML statements (CREATE, INSERT, UPDATE, DELETE, DROP etc.) to the database."""
query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", query_gen_system), ("placeholder", "{messages}")]
)
query_gen = query_gen_prompt | llm

def query_gen_node(state: State):
    return {"messages": [query_gen.invoke(state)]}


workflow.add_node("query_gen", query_gen_node)

#-----------------------------------------------------------------------------------------------

# Add a node for the model to check the query before executing it
workflow.add_node("correct_query", model_check_query)

# Add node for executing the query
workflow.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))

#-----------------------------------------------------------------------------------------------

format_system = """
You receive an unformatted input message and need to format it into a human readable, meaningful response.

If the input message contains tabular data, you should format it into a table. 
If the input message contains a list of items, you should format it into a list.
If the input message contains a single item, you should format it into a sentence.
---
{input}
"""
format_prompt = ChatPromptTemplate.from_messages(
    [("system", format_system), ("placeholder", "{input}")]
)
format_gen = format_prompt | llm

def format_gen_node(state: State):
    return {"messages": [format_gen.invoke({"input": [state["messages"][-1].content]})]}

workflow.add_node("format_gen", format_gen_node)

#-----------------------------------------------------------------------------------------------

# Define a conditional edge to decide whether to continue or end the workflow
def should_continue(state: State) -> Literal["format_gen", "query_gen"]:
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.content.startswith("Error:"):
        return "query_gen"
    else:
        return "format_gen"


# Specify the edges between the nodes
workflow.add_edge(START, "first_tool_call")
workflow.add_edge("first_tool_call", "list_tables_tool")
workflow.add_edge("list_tables_tool", "model_get_schema")
workflow.add_edge("model_get_schema", "get_schema_tool")
workflow.add_edge("get_schema_tool", "query_gen")
workflow.add_edge("query_gen", "correct_query")
workflow.add_edge("correct_query", "execute_query")
workflow.add_conditional_edges(
    "execute_query",
    should_continue,
)
workflow.add_edge("format_gen", END)

# Compile the workflow into a runnable
app = workflow.compile()

human_query = st.chat_input()

if human_query is not None and human_query != "":

    st.session_state.chat_history.append(HumanMessage(human_query))

    inputs = {
        "messages": [
            ("user", human_query),
        ]
    }

    with st.chat_message("Human"):
        st.markdown(human_query)

    with tracer.start_as_current_span("agent-chain") as span:
        for event in app.stream(inputs):  
            for value in event.values():
                print(value)
                message = value["messages"][-1]
                if ( isinstance(message, AIMessage) ):
                    print("AI:", message.content)
                    with st.chat_message("Agent"):
                        if (message.content == ''):
                            toolusage = ''
                            for tool in message.tool_calls:
                                print(tool)
                                toolusage += "name: " + tool["name"] + "  \n\n"
                            st.write("Using the following tools: \n", toolusage)
                        else:
                            st.write(message.content)
                
                if ( isinstance(message, ToolMessage) ):
                    print("Tool:", message.content)
                    with st.chat_message("Tool"):
                        st.write(message.content.replace('\n\n', ''))
        span.set_attribute("llm.usage.completion_tokens",callback.completion_tokens) 
        span.set_attribute("llm.usage.prompt_tokens", callback.prompt_tokens) 
        span.set_attribute("llm.usage.total_tokens", callback.completion_tokens + callback.prompt_tokens) 

    with st.chat_message("Agent"):
        st.write("The conversation has ended. Those were the steps taken to answer your query.")
        st.write("The total number of tokens used in this conversation was: ", callback.completion_tokens + callback.prompt_tokens)
        st.image(
            app.get_graph(xray=True).draw_mermaid_png(
                draw_method=MermaidDrawMethod.API,
            )
        )
