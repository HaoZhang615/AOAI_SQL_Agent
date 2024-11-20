import streamlit as st
from pathlib import Path
import sys
import os

# Define the pages and their corresponding paths
pages = {
    "AI Search Optimized": "src/sql-agents-ai-search-optimized/app.py",
    "Dynamic Tool": "src/sql-agents-dynamic-tool/app.py",
    "Fixed Tool": "src/sql-agents-fixed-tool/app.py",
    "ReAct": "src/sql-react/app.py",
    "Tools": "src/sql-tools/app.py",
}

# Sidebar for navigation
st.sidebar.title("Try Different SQL Agent Approaches")
selection = st.sidebar.radio("Go to", list(pages.keys()))

# Sidebar for database connection configuration
st.sidebar.title("Database Configuration")
# db_driver = st.sidebar.text_input("Driver", value="{ODBC Driver 18 for SQL Server}")
db_driver = "{ODBC Driver 18 for SQL Server}"
db_connection_string = st.sidebar.text_input("Connection String e.g. 'Server=tcp:<your-dbserver-name>.database.windows.net,1433;Database=<your-db-name>;Uid=<username>;Pwd=<password>;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;'", value=os.getenv("AZURE_SQL_CONNECTIONSTRING", ""), type="password")

# add the db_connection_string to the session state
st.session_state.db_connection_string = db_connection_string

st.sidebar.title("Azure OpenAI Configuration")
azure_openai_api_endpoint = st.sidebar.text_input(
    "Azure OpenAI API Endpoint", value=os.getenv("AZURE_OPENAI_ENDPOINT", "")
)
azure_openai_api_key = st.sidebar.text_input(
    "Azure OpenAI API Key", value=os.getenv("AZURE_OPENAI_API_KEY", ""), type="password"
)
azure_openai_completion_deployment_name = st.sidebar.text_input(
    "Azure OpenAI Completion Model Deployment Name", value=os.getenv("AZURE_OPENAI_COMPLETION_DEPLOYMENT_NAME", "")
)
azure_openai_embedding_deployment_name = st.sidebar.text_input(
    "Azure OpenAI Embedding Model Deployment Name", value=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "")
)
azure_openai_api_version = st.sidebar.text_input(
    "Azure OpenAI API Version", value=os.getenv("AZURE_OPENAI_VERSION", "")
)

# Path to the selected page
page_path = Path(pages[selection])

if page_path.exists():
    with open(page_path, "r") as file:
        # Pass the database parameters to the sub-page
        exec(file.read(), {
            "db_driver": db_driver,
            "db_connection_string": db_connection_string,
            "azure_openai_api_endpoint": azure_openai_api_endpoint,
            "azure_openai_api_key": azure_openai_api_key,
            "azure_openai_completion_deployment_name": azure_openai_completion_deployment_name,
            "azure_openai_embedding_deployment_name": azure_openai_embedding_deployment_name,
            "azure_openai_api_version": azure_openai_api_version,
        })
else:
    st.error("Page not found.")