# Troubleshooting Guide

This guide covers common development and Oracle integration issues for the current repository. It documents existing behavior and does not require new workflows.

## Missing Tavily API Key

Symptoms:

- `MissingAPIKeyError` when constructing `TavilyClient`, `AsyncTavilyClient`, or `TavilyHybridClient`.
- Requests are not sent because no Tavily credential is available.

Resolutions:

- Export `TAVILY_API_KEY`.
- Pass `api_key="tvly-..."` when constructing the client.
- For gateway deployments, pass a pre-authenticated `requests.Session` or `httpx.AsyncClient`. When a custom session/client is supplied, the API key is optional.

## Dependency Installation Problems

Symptoms:

- `ModuleNotFoundError: No module named 'oracledb'`.
- `ModuleNotFoundError: No module named 'pymongo'`.
- Import errors around default hybrid RAG embedding/ranking.

Resolutions:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[oracle]"
python -m pip install -e ".[mongodb]"
```

The default hybrid RAG embedding and reranking helpers use Cohere when custom functions are not supplied. Install and configure Cohere for that path, or pass custom `embedding_function` and `ranking_function` callables.

## Oracle Connection Failures

Symptoms:

- `oracledb.DatabaseError` during `oracledb.connect(...)`.
- Connection timeouts.
- Authentication errors.
- Service name or listener errors.

Resolutions:

- Confirm the database is running and reachable.
- Verify `ORACLE_DSN`, for example `localhost:1521/FREEPDB1` for many local Oracle 23ai Free setups.
- Verify `ORACLE_USER` and `ORACLE_PASSWORD`.
- If connecting as `sys` in a local development setup, set `ORACLE_SYSDBA=1` and pass `mode=oracledb.AUTH_MODE_SYSDBA` as shown in the examples.
- Confirm firewalls, Docker port mappings, and service names.

## Oracle Configuration Issues

Symptoms:

- `ValueError: Invalid Oracle identifier`.
- Insert failures because required columns are missing.
- Local search errors because the content or embeddings column is not found.

Resolutions:

- Use valid Oracle identifiers for `table_name`, `content_field`, `embeddings_field`, `cache_timestamp_field`, and metadata filter keys.
- Confirm the configured table exists.
- Confirm the table has the configured content and embedding columns.
- Remember that the client normalizes Oracle identifiers to uppercase.

Minimal table shape:

```sql
CREATE TABLE tavily_documents (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content CLOB,
    embeddings VECTOR(1024, FLOAT32),
    added_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

Match `VECTOR(1024, FLOAT32)` to the dimension produced by your embedding function.

## Vector Search Issues

Symptoms:

- Oracle vector search SQL fails.
- Search returns no local rows.
- Bind or dimension errors during insert/search.

Resolutions:

- Use an Oracle version that supports the `VECTOR` data type and `VECTOR_DISTANCE(...)`.
- Confirm each stored vector has the same dimension as the table column.
- Confirm `embeddings` values are not `NULL`.
- Confirm `max_local` is greater than zero when expecting local results.
- Commit inserted test rows before searching from a separate transaction.

## Vector Index Issues

Symptoms:

- `ensure_oracle_vector_index()` raises a database error.
- Index creation fails with privileges or package availability errors.
- Index creation returns `False`.

Resolutions:

- Confirm the database supports `DBMS_VECTOR.CREATE_INDEX`.
- Confirm the database user has permission to create indexes.
- Confirm `vector_index_name` is a valid Oracle identifier.
- `False` is expected when the index already exists; the helper checks `USER_INDEXES` first and skips creation in that case.
- Choose supported index options: `vector_index_type="HNSW"` or `"IVF"` and a supported distance metric such as `"COSINE"`.

## Native Hybrid Search Issues

Symptoms:

- Errors mentioning `CONTAINS(...)`, `SCORE(1)`, or Oracle Text.
- Native hybrid search returns no text candidates.

Resolutions:

Create an Oracle Text index on the content column before enabling `enable_native_hybrid_search=True`:

```sql
CREATE INDEX tavily_docs_text_idx
ON tavily_documents(content)
INDEXTYPE IS CTXSYS.CONTEXT;
```

The native hybrid path still includes vector candidates, but the text candidate branch requires Oracle Text setup.

## JSON and Provenance Insert Issues

Symptoms:

- Insert failures after enabling `enable_oracle_json_payload=True`.
- Insert failures after enabling `enable_provenance_metadata=True`.
- JSON queries fail because `RAW_PAYLOAD` is missing.

Resolutions:

Add the optional columns before enabling these options:

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

## Freshness Cache Always Misses

Symptoms:

- `retrieval_mode="freshness_cache"` calls Tavily more often than expected.
- Local rows exist but are not returned as cache hits.

Resolutions:

- Confirm the timestamp column exists and matches `cache_timestamp_field`.
- Use a default such as `ADDED_AT TIMESTAMP DEFAULT SYSTIMESTAMP`.
- Increase `cache_ttl_seconds` if rows are older than the freshness window.
- Lower `cache_score_threshold` if local scores are valid but below the hit threshold.
- Confirm the embedding function used for the query is compatible with stored embeddings.

## Semantic Deduplication Does Not Skip Inserts

Symptoms:

- Near-duplicate Tavily results are still inserted.

Resolutions:

- Set `dedup_similarity_threshold` to a float, for example `0.95`.
- Confirm existing rows have non-null embeddings.
- Confirm the embedding function produces comparable vectors for existing and new documents.
- Remember that deduplication is optional and only applies to the Oracle save path.

## Tavily Network, Proxy, or Gateway Issues

Symptoms:

- Tavily requests time out.
- Proxy DNS failures.
- Gateway auth failures.

Resolutions:

- Set `TAVILY_HTTP_PROXY` and `TAVILY_HTTPS_PROXY`, or pass `proxies=...`.
- Use a custom `requests.Session` or `httpx.AsyncClient` for gateway-specific headers.
- Confirm per-call `session_id`, `human_id`, and `client_name` values are strings or string-convertible.
- For tests, prefer the repository request interceptors instead of live network calls.
