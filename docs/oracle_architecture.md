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
| `save_foreign=True` | Persist Tavily results through the existing database write path. |
| `save_foreign=callable` | Existing custom transform hook before persistence. |

## User-Facing Workflows

The current repository supports these user workflows without requiring new APIs:

| Workflow | Entry point |
| --- | --- |
| Standard Tavily search/extract/crawl/map/research | `TavilyClient` and `AsyncTavilyClient`. |
| Custom gateway/session usage | `TavilyClient(session=...)` and `AsyncTavilyClient(client=...)`. |
| MongoDB hybrid RAG | `TavilyHybridClient(db_provider="mongodb", ...)`. |
| Oracle vector retrieval | `TavilyHybridClient(db_provider="oracle", ...)`. |
| Oracle freshness cache | `TavilyHybridClient(db_provider="oracle", retrieval_mode="freshness_cache", ...)`. |
| Oracle long-term memory retrieval | `TavilyHybridClient(db_provider="oracle", retrieval_mode="hybrid_search", ...)`. |
| Oracle-only memory lookup | `search(..., max_foreign=0)`. |
| Tavily write-through persistence | `search(..., save_foreign=True)`. |
| Oracle native hybrid search | `enable_native_hybrid_search=True` with an Oracle Text index. |
| Oracle JSON payload storage | `enable_oracle_json_payload=True` with a `RAW_PAYLOAD JSON` column. |
| Oracle provenance columns | `enable_provenance_metadata=True` with matching provenance columns. |
| Oracle semantic deduplication | `dedup_similarity_threshold=<float>`. |
| Oracle vector index creation | `ensure_oracle_vector_index()`. |

## Why Oracle

Oracle adds a durable database-backed retrieval layer around Tavily search results:

- Native VECTOR support stores embeddings directly in Oracle and searches with `VECTOR_DISTANCE(...)`.
- Native JSON support stores the raw Tavily result and provenance in a queryable JSON column when enabled.
- Oracle Text integration can add lexical scoring to vector similarity for local candidates.
- Freshness-cache mode allows Oracle to answer recent repeated queries without a Tavily call when the local score is high enough.
- Hybrid-search mode turns persisted rows into long-term memory while still allowing fresh Tavily results.
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
5. On a miss, `_search_tavily(...)` calls `self.tavily.search(...)`.
6. `_project_foreign_results(...)` converts Tavily results into the existing hybrid result shape.
7. `ranking_function(...)` reranks merged results in `hybrid_search` mode.
8. `_save_foreign_results(...)` persists Tavily results when `save_foreign` is enabled.

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

## Capability Matrix

| Capability | Existing implementation | Notes |
| --- | --- | --- |
| Tavily integration | `TavilyHybridClient._search_tavily(...)` delegates to `TavilyClient.search(...)`. | No duplicate Tavily request logic in the hybrid client. |
| Oracle VECTOR usage | `tavily.databases.oracledb.search(...)`, `search_native_hybrid(...)`, and `insert_documents(...)`. | Embeddings are bound as float arrays for Oracle vector columns. |
| Oracle JSON usage | `tavily.databases.oracledb.build_persistence_metadata(...)`. | Enabled with `enable_oracle_json_payload=True`. |
| Hybrid retrieval | `retrieval_mode="hybrid_search"`. | Local plus foreign results are reranked by the configured ranking function. |
| Freshness cache lifecycle | `_search_oracle_freshness_cache(...)`. | TTL and score threshold determine cache hits. |
| Oracle persistence workflow | `_save_foreign_results(...)` and `tavily.databases.oracledb.insert_provider(...)`. | Triggered by `save_foreign=True` or a custom `save_foreign` callable. |
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
| Freshness cache flow | `tavily/hybrid_rag/hybrid_rag.py`, `_search_oracle_freshness_cache`. |
| JSON and provenance metadata | `tavily/databases/oracledb.py`, `build_persistence_metadata`. |
| Deduplication | `tavily/databases/oracledb.py`, `filter_duplicate_documents` and `is_duplicate`. |
| Vector index helper | `tavily/hybrid_rag/hybrid_rag.py`, `ensure_oracle_vector_index`. |
| Oracle examples | `examples/oracle_tavily.ipynb`. |
| Oracle tests | `tests/test_hybrid_rag_oracle.py`, `tests/test_hybrid_rag_safety.py`. |

## Convenience API Assessment

The audit suggested possible convenience APIs such as `ensure_schema()`, `store_results()`, `retrieve_cached()`, and `retrieve_memory()`. The current repository already exposes the underlying workflows through stable entry points:

| Suggested API | Existing workflow |
| --- | --- |
| `ensure_schema()` | Schema remains application-managed. `ensure_oracle_vector_index()` exists for the vector index lifecycle. |
| `store_results()` | Use `search(..., save_foreign=True)` or `search(..., save_foreign=callable)`. |
| `retrieve_cached()` | Use `retrieval_mode="freshness_cache"` and `search(...)`. |
| `retrieve_memory()` | Use `retrieval_mode="hybrid_search"` and, for Oracle-only memory lookup, `search(..., max_foreign=0)`. |

No new wrapper APIs were added because the current workflows are already available and changing the public surface was not necessary to satisfy the audit visibility requirements.
