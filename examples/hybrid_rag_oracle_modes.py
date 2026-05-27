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

common_config = {
    "api_key": os.environ["TAVILY_API_KEY"],
    "db_provider": "oracle",
    "connection": connection,
    "table_name": os.environ.get("ORACLE_VECTOR_TABLE", "TAVILY_DOCUMENTS"),
    "embeddings_field": os.environ.get("ORACLE_EMBEDDINGS_FIELD", "EMBEDDINGS"),
    "content_field": os.environ.get("ORACLE_CONTENT_FIELD", "CONTENT"),
}

hybrid_client = TavilyHybridClient(
    **common_config,
    retrieval_mode="hybrid_search",
)

hybrid_results = hybrid_client.search(
    "latest Oracle Database vector search features",
    max_results=5,
    max_local=5,
    max_foreign=5,
    save_foreign=True,
)

freshness_client = TavilyHybridClient(
    **common_config,
    retrieval_mode="freshness_cache",
    cache_ttl_seconds=3600,
    cache_score_threshold=0.75,
)

freshness_results = freshness_client.search(
    "latest Oracle Database vector search features",
    max_results=5,
    max_local=5,
    max_foreign=5,
    save_foreign=True,
)

print("hybrid_search")
print(hybrid_results)
print("freshness_cache")
print(freshness_results)

connection.close()
