# OracleDB Provider for Tavily Hybrid RAG

This provider adds Oracle-backed vector retrieval, freshness caching, and long-term memory behavior to `TavilyHybridClient`.

The high-level pattern is:

```text
User query
  -> Oracle lookup, based on retrieval_mode
  -> Tavily fallback when Oracle misses
  -> optional Oracle write-through persistence
  -> ranked results returned to the caller
```

Tavily stays the freshness layer. Oracle becomes the local memory layer that can reuse useful Tavily results over time.

## Retrieval Modes

| Mode | What it checks first | When Tavily is called | Typical use |
| --- | --- | --- | --- |
| `hybrid_search` | Oracle local vector rows | Whenever `max_foreign > 0` | Blend local memory with fresh Tavily results. |
| `freshness_cache` | Fresh Oracle cache rows inside the TTL window | Only when the fresh cache misses | Avoid repeated Tavily calls for recently-seen queries. |
| `cache_then_memory` | Fresh Oracle cache, then durable Oracle memory | Only when both local tiers miss | Prefer recent cache, fall back to long-term memory, then Tavily. |

## Cache vs Memory

Persistence is controlled by `persistence_depth`.

| Value | Meaning |
| --- | --- |
| `cache_only` | Rows are treated as short-lived cache rows. They can expire and be removed by cleanup. |
| `cache_plus_memory` | Rows are also durable memory rows. They can be reused after cache TTL expiry. |

When `enable_oracle_memory_metadata=True`, the provider can write these lifecycle columns:

| Column | Purpose |
| --- | --- |
| `MEMORY_SCOPE` | Stores `cache_only` or `cache_plus_memory`. |
| `EXPIRES_AT` | Expiration timestamp for cache behavior. |
| `LAST_SEEN_AT` | Last time the row was inserted or updated. |
| `QUERY_COUNT` | Number of times the row was written through or upserted. |

`cleanup_cache()` deletes expired `cache_only` rows when the memory metadata columns exist. It intentionally does not delete `cache_plus_memory` rows, because those rows are the long-term memory tier.

## Schema

The minimum Oracle table needs a content column, a vector column, and a timestamp column:

```sql
CREATE TABLE tavily_documents (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content CLOB,
    embeddings VECTOR(1024, FLOAT32),
    added_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

Most Oracle features need optional metadata columns:

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
    provider_name VARCHAR2(50),
    memory_scope VARCHAR2(30),
    expires_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    query_count NUMBER DEFAULT 0,
    content_hash VARCHAR2(64)
);
```

The demo notebooks call helper code that creates or upgrades this table shape automatically for local demos.

## Scoring

Oracle local vector score is based on cosine distance:

```sql
1 - VECTOR_DISTANCE(embeddings, :query_vector, COSINE)
```

This is a ranking signal, not a probability. A local score like `0.5` does not mean "50 percent correct." It means the query vector and stored vector are close enough under the chosen embedding model and distance metric to be useful for ranking.

Tavily result scores and Oracle vector scores are not guaranteed to be calibrated to the same scale. The configured `ranking_function` decides how merged results are sorted.

## Native Oracle Text Hybrid Search

`enable_native_hybrid_search=True` combines Oracle Vector Search with Oracle Text scoring. It requires an Oracle Text index on the content column:

```sql
CREATE INDEX tavily_docs_text_idx
ON tavily_documents(content)
INDEXTYPE IS CTXSYS.CONTEXT;
```

The demo notebooks keep `enable_native_hybrid_search=False` for stability. Raw natural-language questions can include characters that Oracle Text parses as query syntax, which can produce parser errors unless the query is sanitized or simplified.

## Persistence Controls

The provider includes several controls to prevent the table from growing too quickly:

| Option | Purpose |
| --- | --- |
| `max_persisted_foreign` | Caps how many Tavily results are written per search. |
| `persist_score_threshold` | Persists only Tavily results above a score threshold. |
| `dedup_similarity_threshold` | Skips near-duplicate inserts using vector similarity. |
| `oracle_upsert_key` | Updates existing rows by `source_url` or `content_hash` instead of repeatedly inserting. |
| `cache_ttl_seconds` | Controls the fresh-cache time window. |
| `cleanup_cache()` | Deletes expired cache-only rows. |
| `auto_cleanup_cache=True` | Runs cleanup before search, rate-limited by `cache_cleanup_interval_seconds`. |

## JSON and Provenance

When `enable_oracle_json_payload=True`, the provider can store the raw Tavily result payload in `RAW_PAYLOAD`.

When `enable_provenance_metadata=True`, it can also fill reviewable columns such as `SOURCE_URL`, `SOURCE_TITLE`, `RETRIEVAL_QUERY`, `RETRIEVAL_TIMESTAMP`, `RETRIEVAL_MODE`, `CACHE_HIT`, `INSERTED_FROM`, and `PROVIDER_NAME`.

This makes the memory layer inspectable through normal SQL.

## Developer Notebooks

The focused Oracle notebooks live in `examples/oracle`.

| Notebook | What it demonstrates |
| --- | --- |
| `oracle_tavily_mode_hybrid_search.ipynb` | Seeding Oracle with Tavily results, local-only lookup, and mixed Oracle plus Tavily results. |
| `oracle_tavily_mode_freshness_cache.ipynb` | First run misses local cache and calls Tavily; second run hits fresh Oracle cache. |
| `oracle_tavily_mode_cache_then_memory.ipynb` | First run calls Tavily; after TTL expiry, second run uses durable Oracle memory. |
| `oracle_tavily_evaluation_metrics.ipynb` | Compact latency, origin, and row-count metrics across all retrieval modes. |
| `oracle_tavily_ai_features.ipynb` | JSON payloads, provenance, upsert, persistence caps, score thresholds, semantic deduplication, cleanup, and vector-index helper behavior. |

Each focused notebook has a clearly marked query cell and a final cleanup cell. The cleanup keeps repeated runs predictable, so the first run can demonstrate Tavily fallback and later runs can demonstrate Oracle reuse.

## Code Layout

Oracle-specific implementation files:

- `tavily/databases/oracledb/oracledb.py`
- `tavily/databases/oracledb/oracle_config.py`
- `tavily/databases/oracledb/__init__.py`

Shared Hybrid RAG orchestration lives in:

- `tavily/hybrid_rag/hybrid_rag.py`
- `tavily/hybrid_rag/retrieval_modes.py`
- `tavily/hybrid_rag/embeddings.py`

MongoDB remains a separate provider and is not coupled to the Oracle implementation.
