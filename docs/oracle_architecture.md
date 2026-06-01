# Oracle Architecture and Audit Visibility

This document describes the Oracle-related behavior that already exists in the repository. It is intentionally descriptive: it does not introduce a new architecture, new required workflow, or new public contract.

## Public API Inventory

The package exports these user-facing symbols from `tavily/__init__.py`:

| Symbol | Purpose |
| --- | --- |
| `TavilyClient` | Synchronous Tavily API client. |
| `AsyncTavilyClient` | Asynchronous Tavily API client. |
| `TavilyHybridClient` | Hybrid RAG client for MongoDB or Oracle local retrieval plus Tavily search. |
| `Client` | Deprecated alias/subclass of `TavilyClient`. |
| `InvalidAPIKeyError`, `UsageLimitExceededError`, `MissingAPIKeyError`, `BadRequestError` | Public error classes exported at package level. |

Primary synchronous workflows in `TavilyClient`:

| Method | Workflow |
| --- | --- |
| `search(...)` | Tavily Search API. |
| `extract(...)` | Tavily Extract API. |
| `crawl(...)` | Tavily Crawl API. |
| `map(...)` | Tavily Map API. |
| `research(...)` | Tavily Research API task creation and streaming. |
| `get_research(...)` | Retrieve a research task by request ID. |
| `get_search_context(...)` | Deprecated search-context helper. |
| `qna_search(...)` | Deprecated Q&A helper. |
| `close()`, context manager methods | Session lifecycle management. |

Primary asynchronous workflows in `AsyncTavilyClient` mirror the synchronous client and add `get_company_info(...)`.

Primary hybrid RAG workflows in `TavilyHybridClient`:

| Method or option | Workflow |
| --- | --- |
| `search(...)` | Local database retrieval, Tavily retrieval, reranking, and optional write-through persistence. |
| `ensure_oracle_vector_index(...)` | Optional Oracle vector index helper. It checks `USER_INDEXES` first and creates the index only when missing. |
| `db_provider="mongodb"` | Existing MongoDB Atlas Vector Search path. |
| `db_provider="oracle"` | Oracle Vector Search path. |
| `retrieval_mode="hybrid_search"` | Query local memory, optionally query Tavily, merge, rerank, and optionally persist Tavily results. |
| `retrieval_mode="freshness_cache"` | Query fresh Oracle cache rows first, skip Tavily on a cache hit, and call Tavily plus optional persistence on a miss. |
| `retrieval_mode="cache_then_memory"` | Query fresh Oracle cache rows first, then durable Oracle memory rows, and call Tavily only when both local layers miss. |
| `persistence_depth="cache_only"` | Persist Tavily results as cache rows. |
| `persistence_depth="cache_plus_memory"` | Persist Tavily results as rows that can serve both the freshness cache and long-term memory lookup. |
| `memory_score_threshold=<float>` | Minimum Oracle memory score needed for `cache_then_memory` to avoid a Tavily call. |
| `memory_max_results=<int>` | Optional maximum number of Oracle memory rows inspected in `cache_then_memory`. |
| `enable_oracle_memory_metadata=True` | Writes cache/memory lifecycle fields when the target table has matching columns. |
| `cleanup_cache(...)` | Manually deletes expired Oracle cache rows. |
| `auto_cleanup_cache=True` | Runs expired-cache cleanup automatically before search, throttled by `cache_cleanup_interval_seconds`. |
| `oracle_upsert_key="source_url"` | Uses Oracle `MERGE` so repeated Tavily results with the same source URL update the existing row. |
| `oracle_upsert_key="content_hash"` | Uses Oracle `MERGE` so repeated Tavily results with the same content hash update the existing row. |
| `max_persisted_foreign=<int>` | Caps how many Tavily results are written through to the local database. |
| `persist_score_threshold=<float>` | Skips Tavily results below the configured score during persistence. |
| `oracle_user`, `oracle_password`, `oracle_dsn` | Optional Oracle convenience connection parameters used when `connection` is not supplied. |
| `mongo_uri`, `mongo_database`, `mongo_collection` | Optional MongoDB convenience connection parameters used when `collection` is not supplied. |
| `save_foreign=True` | Persist Tavily results through the existing database write path. |
| `save_foreign=callable` | Existing custom transform hook before persistence. |

## User-Facing Workflows

The current repository supports these user workflows without requiring new APIs:

| Workflow | Entry point |
| --- | --- |
| Standard Tavily search/extract/crawl/map/research | `TavilyClient` and `AsyncTavilyClient`. |
| Custom gateway/session usage | `TavilyClient(session=...)` and `AsyncTavilyClient(client=...)`. |
| MongoDB hybrid RAG | `TavilyHybridClient(db_provider="mongodb", ...)`. |
| MongoDB connection convenience | `TavilyHybridClient(db_provider="mongodb", mongo_uri=..., mongo_database=..., mongo_collection=...)`. |
| Oracle vector retrieval | `TavilyHybridClient(db_provider="oracle", ...)`. |
| Oracle connection convenience | `TavilyHybridClient(db_provider="oracle", oracle_user=..., oracle_password=..., oracle_dsn=...)`. |
| Oracle freshness cache | `TavilyHybridClient(db_provider="oracle", retrieval_mode="freshness_cache", ...)`. |
| Oracle cache then memory | `TavilyHybridClient(db_provider="oracle", retrieval_mode="cache_then_memory", ...)`. |
| Oracle long-term memory retrieval | `TavilyHybridClient(db_provider="oracle", retrieval_mode="hybrid_search", ...)`. |
| Oracle-only memory lookup | `search(..., max_foreign=0)`. |
| Tavily write-through persistence | `search(..., save_foreign=True)`. |
| Oracle native hybrid search | `enable_native_hybrid_search=True` with an Oracle Text index. |
| Oracle JSON payload storage | `enable_oracle_json_payload=True` with a `RAW_PAYLOAD JSON` column. |
| Oracle provenance columns | `enable_provenance_metadata=True` with matching provenance columns. |
| Oracle semantic deduplication | `dedup_similarity_threshold=<float>`. |
| Oracle URL/content-hash upsert | `oracle_upsert_key="source_url"` or `"content_hash"`. |
| Oracle manual cache cleanup | `cleanup_cache()`. |
| Oracle automatic cache cleanup | `auto_cleanup_cache=True`. |
| Oracle vector index creation | `ensure_oracle_vector_index()`. |

## Why Oracle

Oracle adds a durable database-backed retrieval layer around Tavily search results:

- Native VECTOR support stores embeddings directly in Oracle and searches with `VECTOR_DISTANCE(...)`.
- Native JSON support stores the raw Tavily result and provenance in a queryable JSON column when enabled.
- Oracle Text integration can add lexical scoring to vector similarity for local candidates.
- Freshness-cache mode allows Oracle to answer recent repeated queries without a Tavily call when the local score is high enough.
- Cache-then-memory mode lets Oracle check fresh cache first, then durable memory, before falling back to Tavily.
- Hybrid-search mode turns persisted rows into long-term memory while still allowing fresh Tavily results.
- Optional cache/memory metadata can mark row lifecycle scope and expiration windows for clearer auditability.
- Optional provenance fields make audit and review easier without changing the default result shape.
- Optional semantic deduplication reduces repeated inserts by comparing new embeddings to the nearest stored vector.

## Architecture Overview

Freshness cache mode:

```text
User Query
     |
     v
Query Embedding
     |
     v
Oracle Cache Lookup
     |
     +---- Hit above threshold ---> Return Oracle results
     |
     +---- Miss
                |
                v
           Tavily Search
                |
                v
      Optional Oracle Persistence
                |
                v
          Return Tavily results
```

Cache then memory mode:

```text
User Query
     |
     v
Query Embedding
     |
     v
Fresh Oracle Cache Lookup
     |
     +---- Cache hit above threshold ---> Return Oracle cache results
     |
     +---- Cache miss
                |
                v
       Oracle Memory Lookup
                |
                +---- Memory hit above threshold ---> Return Oracle memory results
                |
                +---- Memory miss
                           |
                           v
                      Tavily Search
                           |
                           v
             Optional Oracle Persistence
                           |
                           v
                    Return Tavily results
```

Hybrid search mode:

```text
User Query
     |
     v
Query Embedding
     |
     +----> Oracle Local Search
     |
     +----> Tavily Search when max_foreign > 0
                    |
                    v
             Project Result Shape
                    |
                    v
             Rerank Combined Set
                    |
                    v
      Optional Oracle Persistence
                    |
                    v
                 Return
```

## Search Flow

1. `TavilyHybridClient.search(...)` embeds the user query with the configured `embedding_function`.
2. For Oracle, `tavily.databases.oracledb.search_provider(...)` searches the configured table with `VECTOR_DISTANCE(...)`.
3. In `freshness_cache` mode, `tavily.databases.oracledb.build_freshness_filter(...)` adds the TTL predicate against `cache_timestamp_field`.
4. If fresh local results meet `cache_score_threshold`, `TavilyHybridClient._search_oracle_freshness_cache(...)` returns local results and does not call Tavily.
5. In `cache_then_memory` mode, a fresh-cache miss performs a second Oracle lookup without the TTL filter.
6. If memory results meet `memory_score_threshold`, `TavilyHybridClient._search_oracle_cache_then_memory(...)` returns memory results and does not call Tavily.
7. On a local miss, `_search_tavily(...)` calls `self.tavily.search(...)`.
8. `_project_foreign_results(...)` converts Tavily results into the existing hybrid result shape.
9. `ranking_function(...)` reranks merged results in `hybrid_search` mode.
10. `_save_foreign_results(...)` persists Tavily results when `save_foreign` is enabled.
11. If configured, `persist_score_threshold` and `max_persisted_foreign` reduce the result set before embeddings are generated for persistence.
12. If configured, `oracle_upsert_key` writes with Oracle `MERGE` instead of append-only `INSERT`.

## Data Flow and Persistence

The Oracle persistence path is opt-in and write-through:

```text
Tavily result
     |
     v
Embedding Function
     |
     v
Searchable document:
  CONTENT
  EMBEDDINGS
     |
     +---- Optional RAW_PAYLOAD JSON
     +---- Optional provenance columns
     |
     v
Semantic dedup check when configured
     |
     v
Oracle INSERT
```

The default `save_foreign=True` Oracle document includes only the configured content and embedding columns. JSON and provenance columns are added only when `enable_oracle_json_payload` or `enable_provenance_metadata` is enabled.

When `enable_oracle_memory_metadata=True`, Oracle persistence also writes cache/memory lifecycle fields when the target table includes compatible columns:

| Column | Meaning |
| --- | --- |
| `MEMORY_SCOPE` | Stores the configured `persistence_depth`, either `cache_only` or `cache_plus_memory`. |
| `EXPIRES_AT` | Stores the insert timestamp plus `cache_ttl_seconds`; cache lookups still use the configured cache timestamp field for TTL filtering. |
| `LAST_SEEN_AT` | Stores the insert timestamp for initial audit visibility. |
| `QUERY_COUNT` | Starts at `1` for the inserted Tavily result. |

These fields are insert metadata today. Hit-time updates to `LAST_SEEN_AT` and `QUERY_COUNT` are intentionally not automatic yet because they require a stable row identity or upsert strategy.

When `oracle_upsert_key` is enabled, Oracle persistence uses `MERGE` rather than append-only `INSERT` for rows that have the configured key:

| Upsert key | Required column | Behavior |
| --- | --- | --- |
| `source_url` | `SOURCE_URL` | Repeated Tavily results from the same URL update the existing row. |
| `content_hash` | `CONTENT_HASH` | Repeated Tavily results with identical content update the existing row. |

Rows that do not have the configured key fall back to the normal insert path. When `QUERY_COUNT` is present in the persisted columns, matched upserts increment it with `NVL(QUERY_COUNT, 0) + 1`.

`cleanup_cache()` is a manual cleanup helper. With memory metadata columns present, it deletes only expired `cache_only` rows so `cache_plus_memory` rows can continue acting as long-term memory. Without those metadata columns, it falls back to the configured cache timestamp field and TTL.

`auto_cleanup_cache=True` turns that same cleanup behavior into an on-demand retention policy. The client checks cleanup before search and runs it only when at least `cache_cleanup_interval_seconds` have elapsed since the previous automatic cleanup. It is intentionally not a background thread or database scheduler.

The client can either receive database handles from the application or create them from convenience parameters:

```python
oracle_client = TavilyHybridClient(
    api_key="tvly-...",
    db_provider="oracle",
    oracle_user="intern_user",
    oracle_password="...",
    oracle_dsn="localhost:1521/FREEPDB1",
    table_name="tavily_documents",
)

mongo_client = TavilyHybridClient(
    api_key="tvly-...",
    db_provider="mongodb",
    mongo_uri="mongodb://localhost:27017",
    mongo_database="memory",
    mongo_collection="documents",
    index="vector_search",
)
```

When the client creates the database handle, `close()` closes the managed Oracle connection or MongoDB client.

## Capability Matrix

| Capability | Existing implementation | Notes |
| --- | --- | --- |
| Tavily integration | `TavilyHybridClient._search_tavily(...)` delegates to `TavilyClient.search(...)`. | No duplicate Tavily request logic in the hybrid client. |
| Oracle VECTOR usage | `tavily.databases.oracledb.search(...)`, `search_native_hybrid(...)`, and `insert_documents(...)`. | Embeddings are bound as float arrays for Oracle vector columns. |
| Oracle JSON usage | `tavily.databases.oracledb.build_persistence_metadata(...)`. | Enabled with `enable_oracle_json_payload=True`. |
| Hybrid retrieval | `retrieval_mode="hybrid_search"`. | Local plus foreign results are reranked by the configured ranking function. |
| Freshness cache lifecycle | `_search_oracle_freshness_cache(...)`. | TTL and score threshold determine cache hits. |
| Cache then memory lifecycle | `_search_oracle_cache_then_memory(...)`. | Cache is checked first, Oracle memory second, and Tavily last. |
| Persistence depth | `persistence_depth="cache_only"` or `"cache_plus_memory"`. | Used when Oracle memory metadata is enabled. |
| Memory hit controls | `memory_score_threshold` and `memory_max_results`. | Used by `cache_then_memory` after a cache miss. |
| Cache/memory metadata | `enable_oracle_memory_metadata=True`. | Writes `MEMORY_SCOPE`, `EXPIRES_AT`, `LAST_SEEN_AT`, and `QUERY_COUNT`. |
| Manual cache cleanup | `cleanup_cache(...)`. | Deletes expired cache rows on demand. |
| Automatic retention | `auto_cleanup_cache=True`. | Calls cleanup before search at a throttled interval. |
| URL/content-hash upsert | `oracle_upsert_key`. | Uses Oracle `MERGE` when a stable URL or content hash is available. |
| Persistence controls | `max_persisted_foreign` and `persist_score_threshold`. | Bound database growth by saving fewer Tavily results. |
| Convenience DB connections | `oracle_user`/`oracle_password`/`oracle_dsn` and `mongo_uri`/`mongo_database`/`mongo_collection`. | Optional shorthand when the app does not want to construct the DB handle itself. |
| Oracle persistence workflow | `_save_foreign_results(...)` and `tavily.databases.oracledb.insert_provider(...)`. | Triggered by `save_foreign=True` or a custom `save_foreign` callable. |
| Oracle insert schema validation | `tavily.databases.oracledb.validate_insert_schema(...)`. | Checks target columns and conservative type compatibility before `executemany(...)`. |
| Semantic deduplication | `tavily.databases.oracledb.filter_duplicate_documents(...)` and `is_duplicate(...)`. | Enabled only when `dedup_similarity_threshold` is set. |
| Native Oracle hybrid search | `tavily.databases.oracledb.search_native_hybrid(...)`. | Requires an Oracle Text index on the content column. |
| Vector index lifecycle | `ensure_oracle_vector_index(...)`. | Explicit helper; it does not run automatically. |
| Metadata filtering | `tavily.databases.oracledb.build_metadata_filter(...)`. | Column names are validated as Oracle identifiers. |

## Oracle Implementation References

| Area | Reference |
| --- | --- |
| Oracle constructor options and validation | `tavily/hybrid_rag/hybrid_rag.py`, `TavilyHybridClient.__init__`, plus `tavily/databases/oracledb.py` validation helpers. |
| Oracle vector search SQL | `tavily/databases/oracledb.py`, `search`. |
| Oracle native hybrid SQL | `tavily/databases/oracledb.py`, `search_native_hybrid`. |
| Retrieval-mode orchestration | `tavily/hybrid_rag/retrieval_modes.py`. |
| JSON and provenance metadata | `tavily/databases/oracledb.py`, `build_persistence_metadata`. |
| Cache/memory lifecycle metadata | `tavily/databases/oracledb.py`, `build_persistence_metadata` and `build_memory_scope_filter`. |
| Manual cache cleanup | `tavily/databases/oracledb.py`, `delete_expired_cache_rows`. |
| Convenience DB connections | `tavily/databases/connections.py`. |
| Oracle upsert persistence | `tavily/databases/oracledb.py`, `upsert_documents`. |
| Insert schema validation | `tavily/databases/oracledb.py`, `fetch_table_columns` and `validate_insert_schema`. |
| Deduplication | `tavily/databases/oracledb.py`, `filter_duplicate_documents` and `is_duplicate`. |
| Vector index helper | `tavily/hybrid_rag/hybrid_rag.py`, `ensure_oracle_vector_index`. |
| Oracle examples | `examples/oracle_tavily.ipynb`. |
| Oracle tests | `tests/test_hybrid_rag_oracle.py`, `tests/test_hybrid_rag_safety.py`. |

## Convenience API Assessment

The audit suggested possible convenience APIs such as `ensure_schema()`, `store_results()`, `retrieve_cached()`, and `retrieve_memory()`. The current repository already exposes the underlying workflows through stable entry points:

| Suggested API | Existing workflow |
| --- | --- |
| `ensure_schema()` | Schema remains application-managed. `ensure_oracle_vector_index()` exists for the vector index lifecycle, and insert-time schema validation fails early when required columns or compatible types are missing. |
| `store_results()` | Use `search(..., save_foreign=True)` or `search(..., save_foreign=callable)`. |
| `retrieve_cached()` | Use `retrieval_mode="freshness_cache"` and `search(...)`. |
| `retrieve_memory()` | Use `retrieval_mode="hybrid_search"` and, for Oracle-only memory lookup, `search(..., max_foreign=0)`. For a cache-first memory workflow, use `retrieval_mode="cache_then_memory"`. |

No new wrapper APIs were added because the current workflows are already available and changing the public surface was not necessary to satisfy the audit visibility requirements.
