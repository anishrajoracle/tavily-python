# Modifications Compared to Upstream `tavily-python`

This document summarizes the changes made on top of the original `tavily-ai/tavily-python` repository.

The main goal was to add OracleDB as a first-class database provider for `TavilyHybridClient` while keeping the existing MongoDB behavior intact.

## Files Changed

Compared with upstream `tavily-ai/tavily-python`, the following files were added or modified:

| File | Change type | Purpose |
| --- | --- | --- |
| `tavily/hybrid_rag/hybrid_rag.py` | Modified | Added OracleDB support, provider branching, Oracle search/insert helpers, Oracle retrieval modes, Oracle AI Database feature flags, safer Cohere setup, and guardrails. |
| `setup.py` | Modified | Added optional database extras for OracleDB and MongoDB. |
| `examples/hybrid_rag_oracle.py` | Added | Added a runnable OracleDB example. |
| `examples/hybrid_rag_oracle_modes.py` | Added | Shows Oracle `hybrid_search` and `freshness_cache` configuration side by side. |
| `examples/hybrid_rag_oracle_ai_database.ipynb` | Added | Small notebook for Tavily search, Oracle persistence, freshness-cache hits, provenance inspection, and semantic dedup. |
| `examples/hybrid_rag_oracle_smoke_test.py` | Added | Added a repeatable manual OracleDB + Tavily smoke test script. |
| `tests/test_hybrid_rag_oracle.py` | Added | Added OracleDB-specific unit tests. |
| `tests/test_hybrid_rag_safety.py` | Added | Added safety/regression tests around hybrid RAG behavior. |
| `tests/test_errors.py` | Modified | Made invalid API key tests deterministic by mocking the `401` response instead of making a live network call. |
| `modifications.md` | Added | Documents the integration changes. |
| `testing_summary.md` | Added | Records test commands, results, and manual integration checks. |

## Hybrid RAG Client Changes

File:

```text
tavily/hybrid_rag/hybrid_rag.py
```

### Provider Support

The original client was coupled to MongoDB-style behavior. It expected a MongoDB collection and used MongoDB Atlas Vector Search operations directly.

The client now supports:

```python
db_provider="mongodb"
db_provider="oracle"
```

For upstream merge friendliness, the existing MongoDB branch remains first and the OracleDB path is added as the additional provider branch:

```python
if self.db_provider == "mongodb":
    ...
elif self.db_provider == "oracle":
    ...
else:
    raise ValueError(...)
```

This keeps the existing MongoDB flow easy to review while still treating OracleDB as a supported provider inside the same client.

### Oracle Retrieval Modes

OracleDB now supports two modes:

```python
retrieval_mode="hybrid_search"
retrieval_mode="freshness_cache"
```

`hybrid_search` is the default and preserves the existing Oracle behavior:

```text
query
-> embed query
-> search Oracle local vector store
-> search Tavily when max_foreign > 0
-> combine local + foreign
-> rerank
-> optionally save Tavily results into Oracle
```

`freshness_cache` is Oracle-only and implements the freshness-layer flow:

```text
query
-> embed query
-> search fresh Oracle rows
-> if a local result meets cache_score_threshold:
     return Oracle results only
   else:
     call Tavily
     optionally save Tavily results into Oracle
     return Tavily results only
```

MongoDB continues to support only `hybrid_search`. Passing `retrieval_mode="freshness_cache"` with `db_provider="mongodb"` raises a clean unsupported-mode error.

### Oracle AI Database Feature Flags

Additional Oracle-only capabilities are opt-in so existing deployments keep their current behavior:

```python
enable_native_hybrid_search=False
oracle_metadata_filters=None
enable_oracle_json_payload=False
enable_provenance_metadata=False
dedup_similarity_threshold=None
cache_timestamp_field="ADDED_AT"
```

When enabled, Oracle native hybrid search keeps the existing Python flow but changes the Oracle local candidate query to include:

- `VECTOR_DISTANCE(...)`
- Oracle Text `CONTAINS(...)`
- Oracle Text `SCORE(1)`
- optional exact-match metadata filters

The combined local and Tavily results still flow through the existing Python reranking path.

Oracle JSON/provenance persistence is limited to the Oracle write-through path. With the flags enabled, default `save_foreign=True` documents can include:

- `RAW_PAYLOAD`
- `SOURCE_URL`
- `SOURCE_TITLE`
- `RETRIEVAL_QUERY`
- `RETRIEVAL_TIMESTAMP`
- `RETRIEVAL_MODE`
- `CACHE_HIT`
- `INSERTED_FROM`
- `PROVIDER_NAME`

Semantic deduplication is also Oracle-only and optional. When `dedup_similarity_threshold` is set, the Oracle save path checks the nearest existing vector using the already-computed Tavily embedding and skips inserts whose nearest similarity is at or above the threshold.

The Oracle vector index helper is explicit and does not run automatically:

```python
client.ensure_oracle_vector_index()
```

It checks `USER_INDEXES` first and only calls `DBMS_VECTOR.CREATE_INDEX(...)` when the index is missing.

### Constructor Changes

The constructor now accepts both OracleDB and MongoDB configuration:

```python
db_provider: Literal["mongodb", "oracle"]
collection=None
index: Optional[str] = None
connection=None
table_name: Optional[str] = None
retrieval_mode: Literal["hybrid_search", "freshness_cache"] = "hybrid_search"
cache_ttl_seconds: int = 86400
cache_score_threshold: float = 0.0
cache_timestamp_field: str = "ADDED_AT"
enable_native_hybrid_search: bool = False
oracle_metadata_filters: Optional[dict] = None
enable_oracle_json_payload: bool = False
enable_provenance_metadata: bool = False
vector_index_name: Optional[str] = None
vector_index_type: Literal["HNSW", "IVF"] = "HNSW"
vector_index_distance: str = "COSINE"
vector_index_accuracy: int = 90
vector_index_neighbors: int = 40
vector_index_efconstruction: int = 500
vector_index_partitions: int = 10
dedup_similarity_threshold: Optional[float] = None
```

MongoDB path:

```python
TavilyHybridClient(
    api_key="...",
    db_provider="mongodb",
    collection=mongo_collection,
    index="vector_search",
    embeddings_field="embeddings",
    content_field="content",
)
```

OracleDB path:

```python
TavilyHybridClient(
    api_key="...",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    embeddings_field="EMBEDDINGS",
    content_field="CONTENT",
    retrieval_mode="hybrid_search",
)
```

OracleDB freshness-cache path:

```python
TavilyHybridClient(
    api_key="...",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    embeddings_field="EMBEDDINGS",
    content_field="CONTENT",
    retrieval_mode="freshness_cache",
    cache_ttl_seconds=3600,
    cache_score_threshold=0.75,
)
```

### MongoDB Local Search

The MongoDB path remains in the main client and continues to use the existing Atlas Vector Search aggregation:

```python
collection.aggregate([
    {"$vectorSearch": ...},
    {"$project": ...},
])
```

The MongoDB code remains the first provider branch so the original behavior is easier for upstream maintainers to compare.

### OracleDB Local Search

Added an Oracle-specific local search helper:

```python
_search_oracle(...)
```

OracleDB search uses Oracle vector distance syntax:

```sql
VECTOR_DISTANCE(EMBEDDINGS, :query_vector, COSINE)
```

The result shape is kept compatible with the existing hybrid RAG flow:

```python
{
    "content": ...,
    "score": ...,
    "origin": "local",
}
```

In `freshness_cache` mode, Oracle local search adds a TTL predicate against `ADDED_AT`:

```sql
ADDED_AT >= CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTODSINTERVAL(:cache_ttl_seconds, 'SECOND')
```

Rows returned by this query must also meet `cache_score_threshold` before Tavily is skipped.

When `enable_native_hybrid_search=True`, Oracle local search uses an Oracle Text predicate and score in addition to vector similarity:

```sql
CONTAINS(CONTENT, :text_query, 1) > 0
SCORE(1)
VECTOR_DISTANCE(EMBEDDINGS, :query_vector, COSINE)
```

### Saving Tavily Results

The original save path used:

```python
self.collection.insert_many(documents)
```

That remains the MongoDB save path.

OracleDB now uses:

```python
_insert_oracle_documents(...)
```

The Oracle insert helper:

- Validates Oracle identifiers before SQL construction.
- Converts embedding lists into Oracle-compatible vector binds.
- Uses `executemany(...)` for batch inserts.
- Commits through the provided Oracle connection.
- Optionally includes raw Tavily JSON payloads and provenance columns when enabled.
- Optionally skips near-duplicate documents before insert when `dedup_similarity_threshold` is set.

Oracle vector values are converted with:

```python
array.array("f", values)
```

### Identifier Safety

Oracle table and column names cannot be passed as ordinary bind variables, so identifier validation was added.

Allowed Oracle identifier pattern:

```text
^[A-Za-z_][A-Za-z0-9_]*$
```

Validation applies to:

- `table_name`
- `embeddings_field`
- `content_field`
- custom document keys used during Oracle inserts

Unsafe identifiers raise `ValueError`.

### Cohere Initialization Safety

The previous code attempted to create a Cohere client at import time and used a broad exception handler.

The updated code:

- Imports `cohere` only if available.
- Lazily creates the Cohere client only when the default embedding/ranking functions are used.
- Raises a clearer error if Cohere is unavailable or misconfigured.
- Allows users to avoid Cohere entirely by passing custom `embedding_function` and `ranking_function` callables.

### Additional Guardrails

The hybrid RAG client now also:

- Validates that `embedding_function` is callable.
- Validates that `ranking_function` is callable.
- Avoids calling `insert_many([])` or the Oracle insert path when a custom `save_foreign` function filters out all documents.
- Keeps `collection` documented as a MongoDB collection object, not merely a collection name.

## Dependency Changes

File:

```text
setup.py
```

Added optional extras:

```python
extras_require={
    "oracle": ["oracledb"],
    "mongodb": ["pymongo"],
}
```

This keeps the base SDK lightweight. Users install only the database driver they need:

```bash
pip install -e ".[oracle]"
pip install -e ".[mongodb]"
```

## OracleDB Example

Files added:

```text
examples/hybrid_rag_oracle.py
examples/hybrid_rag_oracle_modes.py
examples/hybrid_rag_oracle_ai_database.ipynb
examples/hybrid_rag_oracle_smoke_test.py
```

`examples/hybrid_rag_oracle.py` shows how to:

- Create a `python-oracledb` connection.
- Optionally use `ORACLE_SYSDBA`.
- Instantiate `TavilyHybridClient` with `db_provider="oracle"`.
- Point the client at an Oracle table containing content and vector embeddings.

`examples/hybrid_rag_oracle_modes.py` shows how to configure:

- Oracle `hybrid_search`
- Oracle `freshness_cache`
- `cache_ttl_seconds`
- `cache_score_threshold`
- Oracle native hybrid search
- JSON/provenance persistence
- semantic deduplication

`examples/hybrid_rag_oracle_ai_database.ipynb` shows:

- Tavily search
- Oracle persistence
- freshness-cache hit behavior
- JSON provenance inspection
- semantic deduplication

`examples/hybrid_rag_oracle_smoke_test.py` is a repeatable manual smoke test. It:

- Reads `TAVILY_API_KEY` from the environment.
- Connects to Oracle using environment-configurable connection settings.
- Creates a small Oracle vector table if it does not already exist.
- Seeds local Oracle rows if the table is empty.
- Runs `TavilyHybridClient(db_provider="oracle")`.
- Fetches Tavily foreign results.
- Saves Tavily foreign results into Oracle with `save_foreign=True`.
- Prints local/foreign results and the final Oracle row count.

## Test Changes

High-level summary:

- Oracle search SQL is generated correctly.
- Oracle vector binds are formatted correctly.
- Oracle inserts work structurally.
- Tavily foreign results can be saved into Oracle.
- Unsafe SQL identifiers are rejected.
- Shared hybrid RAG edge cases do not break inserts.

### New OracleDB Tests

File added:

```text
tests/test_hybrid_rag_oracle.py
```

These tests use fake Oracle connection/cursor objects, so they do not require a live Oracle instance.

Coverage added:

- Oracle search emits `VECTOR_DISTANCE(...)`.
- Oracle search binds query vectors as `array.array("f", ...)`.
- Oracle insert builds the expected `INSERT INTO ... VALUES ...` statement.
- Oracle insert converts embeddings into vector binds.
- Oracle `save_foreign=True` inserts Tavily foreign results through the Oracle path.
- Oracle `freshness_cache` skips Tavily on a fresh, high-scoring local hit.
- Oracle `freshness_cache` calls Tavily and saves foreign results on a cache miss.
- Oracle native hybrid search emits `CONTAINS(...)`, `SCORE(1)`, and metadata filters.
- Oracle JSON/provenance persistence writes raw payload and provenance columns.
- Oracle vector index helper creates missing indexes and skips existing indexes.
- Oracle semantic deduplication skips near-duplicate inserts.
- Unsafe Oracle identifiers are rejected.

### New Safety Tests

File added:

```text
tests/test_hybrid_rag_safety.py
```

Coverage added:

- If a custom `save_foreign` function filters out every document, no empty insert is attempted.
- `embedding_function` must be callable.
- `ranking_function` must be callable.
- MongoDB rejects Oracle-only `freshness_cache` mode.
- MongoDB ignores Oracle-only feature flags in `hybrid_search` mode.

### Existing Error Test Fix

File modified:

```text
tests/test_errors.py
```

The original `test_invalid_api_key` made a live request to Tavily with an invalid API key. In environments with proxy/DNS issues, this failed with a network/proxy error before Tavily could return a `401`.

The test now uses the repository's request interceptor to return a deterministic fake `401` response for both:

- `TavilyClient`
- `AsyncTavilyClient`

This keeps the test focused on SDK error handling and makes the suite pass without requiring live network access.

## Testing Results

Full test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
89 passed in 0.39s
```

Targeted tests:

```bash
.venv/bin/python -m pytest tests/test_errors.py tests/test_hybrid_rag_oracle.py tests/test_hybrid_rag_safety.py
```

Result:

```text
18 passed in 0.04s
```

Manual OracleDB integration testing was also completed against a local Oracle container. The Oracle path successfully:

- Connected to Oracle.
- Created a test user and vector table.
- Inserted vector rows.
- Queried local Oracle vector results through `TavilyHybridClient(db_provider="oracle")`.
- Combined local Oracle results with Tavily API results.
- Saved Tavily foreign results into Oracle with `save_foreign=True`.

Detailed test notes are recorded in:

```text
testing_summary.md
```

## Expected Oracle Table Shape

Recommended table shape:

```sql
CREATE TABLE tavily_documents (
    id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    content CLOB,
    embeddings VECTOR(*, FLOAT32),
    site_url VARCHAR2(1000),
    site_title VARCHAR2(500),
    added_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

Minimum required columns:

```text
CONTENT
EMBEDDINGS
```

Any extra keys returned by a custom `save_foreign` function must map to real Oracle table columns.

`freshness_cache` mode uses `ADDED_AT` for TTL validation. The default Oracle `save_foreign=True` path can rely on the table default to populate it.

Optional Oracle AI Database columns:

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

Optional Oracle Text index for native hybrid search:

```sql
CREATE INDEX tavily_docs_text_idx
ON tavily_documents(content)
INDEXTYPE IS CTXSYS.CONTEXT;
```

## Non-Goals

This work does not create a separate Oracle-only package, wrapper, or cache product.

OracleDB and MongoDB are both supported inside the existing `TavilyHybridClient` as main database provider options.
