# Deployment Guide

This guide documents the repository's existing deployment model. The current implementation expects applications to provide their own Tavily credentials, Oracle connection, and schema. No new service, connection factory, or migration runner is required.

## Deployment Model

The Oracle workflow is embedded in `TavilyHybridClient`:

```text
Application
     |
     +---- TavilyHybridClient
              |
              +---- Tavily API through TavilyClient
              |
              +---- Existing python-oracledb connection
                       |
                       +---- Oracle table with content and vector columns
```

The application owns:

- Tavily API key or custom authenticated HTTP session/client.
- Oracle connection creation and lifecycle.
- Oracle schema creation and migrations.
- Optional Oracle Text index and vector index setup.
- Optional JSON/provenance columns.

## Local Oracle Usage

The examples use environment variables so the same scripts can run against local Oracle databases:

| Variable | Purpose |
| --- | --- |
| `TAVILY_API_KEY` | Tavily API key used by the SDK. |
| `ORACLE_USER` | Oracle username. |
| `ORACLE_PASSWORD` | Oracle password. |
| `ORACLE_DSN` | Oracle DSN, for example `localhost:1521/FREEPDB1`. |
| `ORACLE_SYSDBA` | Set to `1` when a local setup requires SYSDBA mode. |
| `ORACLE_VECTOR_TABLE` | Table used by Oracle hybrid RAG examples. |
| `ORACLE_CONTENT_FIELD` | Content column name. |
| `ORACLE_EMBEDDINGS_FIELD` | Embedding vector column name. |
| `ORACLE_ENABLE_AI_FEATURES` | Enables optional native hybrid/JSON/provenance example path in `examples/hybrid_rag_oracle_modes.py`. |

Install the Oracle optional dependency:

```bash
python -m pip install -e ".[oracle]"
```

Run a smoke test when a local Oracle database and `TAVILY_API_KEY` are available:

```bash
python examples/hybrid_rag_oracle_smoke_test.py
```

## Oracle 23ai Usage

Oracle 23ai is the expected target for native vector capabilities used by the Oracle path:

- `VECTOR` columns store embeddings.
- `VECTOR_DISTANCE(...)` performs similarity search.
- `DBMS_VECTOR.CREATE_INDEX(...)` can create HNSW or IVF vector indexes through `ensure_oracle_vector_index()`.
- JSON columns can store Tavily payloads and provenance.
- Oracle Text can be used with `CONTAINS(...)` and `SCORE(1)` when native hybrid search is enabled.

The client receives a normal `python-oracledb` connection:

```python
import oracledb
from tavily import TavilyHybridClient

connection = oracledb.connect(
    user="tavily_user",
    password="secret",
    dsn="localhost:1521/FREEPDB1",
)

client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=connection,
    table_name="TAVILY_DOCUMENTS",
)
```

## Minimal Schema

Use a content column and a vector column whose dimension matches your embedding function:

```sql
CREATE TABLE tavily_documents (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content CLOB,
    embeddings VECTOR(1024, FLOAT32),
    added_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

Freshness-cache mode expects a timestamp column such as `ADDED_AT`:

```python
client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=connection,
    table_name="TAVILY_DOCUMENTS",
    retrieval_mode="freshness_cache",
    cache_ttl_seconds=3600,
    cache_score_threshold=0.75,
)
```

## Optional JSON and Provenance Schema

Enable JSON/provenance persistence only after adding matching columns:

```sql
ALTER TABLE tavily_documents ADD (
    raw_payload JSON,
    source_url VARCHAR2(1000),
    source_title VARCHAR2(500),
    retrieval_query VARCHAR2(1000),
    retrieval_timestamp TIMESTAMP WITH TIME ZONE,
    retrieval_mode VARCHAR2(30),
    cache_hit NUMBER(1),
    inserted_from VARCHAR2(30),
    provider_name VARCHAR2(50)
);
```

Then enable the existing flags:

```python
client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=connection,
    table_name="TAVILY_DOCUMENTS",
    enable_oracle_json_payload=True,
    enable_provenance_metadata=True,
)
```

## Optional Oracle Text Index

Native hybrid search adds Oracle Text scoring to local Oracle candidates. Create a text index before enabling it:

```sql
CREATE INDEX tavily_docs_text_idx
ON tavily_documents(content)
INDEXTYPE IS CTXSYS.CONTEXT;
```

Then configure:

```python
client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=connection,
    table_name="TAVILY_DOCUMENTS",
    enable_native_hybrid_search=True,
)
```

## Optional Vector Index

The vector index helper is explicit and idempotent:

```python
created = client.ensure_oracle_vector_index()
```

It returns `True` when it creates the index and `False` when the index already exists. It does not run automatically during client construction or search.

## Existing Configuration Approach

The client is configured through constructor arguments. Existing workflows continue to work unchanged:

```python
results = client.search(
    "latest Oracle Database vector search features",
    max_results=5,
    max_local=5,
    max_foreign=5,
    save_foreign=True,
)
```

Operational guidance:

- Use `max_foreign=0` for Oracle-only local memory lookup.
- Use `save_foreign=True` for default write-through persistence.
- Use a `save_foreign` callable when your schema needs custom columns.
- Keep optional Oracle JSON/provenance, native hybrid search, and deduplication disabled unless the schema and indexes are ready.
- Manage Oracle connection pooling outside the client with your application's standard `python-oracledb` setup.
