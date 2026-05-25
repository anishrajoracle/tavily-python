import os

import oracledb
from tavily import TavilyHybridClient


connection_args = {
    "user": os.environ.get("ORACLE_USER", "sys"),
    "password": os.environ["ORACLE_PASSWORD"],
    "dsn": os.environ.get("ORACLE_DSN", "localhost:1521/FREE"),
}

if os.environ.get("ORACLE_SYSDBA") == "1":
    connection_args["mode"] = oracledb.AUTH_MODE_SYSDBA

connection = oracledb.connect(**connection_args)

hybrid_rag = TavilyHybridClient(
    api_key=os.environ["TAVILY_API_KEY"],
    db_provider="oracle",
    connection=connection,
    table_name=os.environ.get("ORACLE_VECTOR_TABLE", "TAVILY_DOCUMENTS"),
    embeddings_field=os.environ.get("ORACLE_EMBEDDINGS_FIELD", "EMBEDDINGS"),
    content_field=os.environ.get("ORACLE_CONTENT_FIELD", "CONTENT"),
)

results = hybrid_rag.search("Who is Leo Messi?", max_results=5)

print(results)
