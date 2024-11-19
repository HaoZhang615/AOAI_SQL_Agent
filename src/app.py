# Python
import streamlit as st
from pathlib import Path
import sys

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

# Path to the selected page
page_path = Path(pages[selection])

if page_path.exists():
    with open(page_path, "r") as file:
        exec(file.read())
else:
    st.error("Page not found.")