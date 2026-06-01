# Oracle Memory Layer Demo Runbook

Use this as presenter notes for the `feature/oracle-memory-layer` demo.

Target length: 8-10 minutes.

## Demo Goal

Show that Tavily remains the freshness layer while Oracle becomes the persistent memory layer.

The demo should prove three things:

1. Tavily can fetch fresh web results.
2. Oracle stores those results as vector-searchable memory with provenance.
3. Future queries can use Oracle first through three retrieval modes.

## 8-10 Minute Demo Plan

Use this as the main path. Keep the longer sections below as backup notes.

| Time | What To Show | Main Point |
| --- | --- | --- |
| 0:00-1:00 | Branch, notebook, SQL Developer setup | This is a working Tavily + Oracle branch. |
| 1:00-2:00 | The three retrieval modes | We support hybrid, cache-first, and cache-then-memory workflows. |
| 2:00-3:30 | Client initialization cell | The behavior is configurable through client parameters. |
| 3:30-5:00 | `hybrid_search` run | Oracle memory and Tavily freshness can work together. |
| 5:00-6:30 | `freshness_cache` repeated run | A repeated query can hit Oracle instead of Tavily. |
| 6:30-8:00 | `cache_then_memory` run | Oracle can act as cache first, durable memory second, Tavily last. |
| 8:00-9:30 | SQL Developer metadata query | Rows are stored with provenance, memory scope, TTL, and upsert metadata. |
| 9:30-10:00 | Closing summary | Tavily stays fresh; Oracle makes results reusable and auditable. |

Do not run the full test suite live unless someone asks. Mention it at the end and keep the command ready.

## Screen Setup

Use three windows side by side:

- VS Code or Jupyter: `examples/oracle_tavily.ipynb`
- SQL Developer: connected to the Oracle demo schema
- Terminal: repository root

Before presenting, run:

```bash
git branch --show-current
```

Expected:

```text
feature/oracle-memory-layer
```

## Opening Script

Say:

```text
I will keep this short and show the full loop: Tavily fetches fresh results, Oracle stores them, and future queries can reuse Oracle before calling Tavily again.

The integration story is Tavily as the freshness layer and Oracle as the memory layer.
The new part is that the client now supports three retrieval modes, including a cache-then-memory path for agent workflows.
```

## The Three Modes

Show this before running anything:

| Mode | What It Does | When To Use |
| --- | --- | --- |
| `hybrid_search` | Searches Oracle memory and Tavily, merges results, then reranks. | Best when the app wants both durable memory and fresh web context together. |
| `freshness_cache` | Checks fresh Oracle cache rows first, calls Tavily only on cache miss. | Best when the app wants to avoid repeated Tavily calls for recent similar queries. |
| `cache_then_memory` | Checks fresh cache, then durable Oracle memory, then Tavily. | Best for agent memory workflows where Oracle should answer if either cache or memory is good enough. |

Say in 30 seconds:

```text
The third mode, cache_then_memory, is the most important one for the Oracle memory-layer story. It gives us a layered fallback: fresh cache first, durable memory second, Tavily last.
```

## Run Notebook Setup

In `examples/oracle_tavily.ipynb`, run the setup cells through:

- Setup and Prerequisites
- Oracle Connection
- Schema / Table Setup
- Initialize the Tavily + Oracle Client
- Demo Query Setup

Pause at client initialization and show these three clients:

```python
hybrid_client = TavilyHybridClient(... retrieval_mode="hybrid_search")
cache_client = TavilyHybridClient(... retrieval_mode="freshness_cache")
cache_memory_client = TavilyHybridClient(... retrieval_mode="cache_then_memory")
```

Then point out only these controls:

```python
retrieval_mode
persistence_depth
cache_ttl_seconds
oracle_upsert_key
max_persisted_foreign
```

Say:

```text
These are the important knobs. We can choose the retrieval strategy, decide whether rows are only cache or also durable memory, expire cache rows, upsert by URL or content hash, and limit how many Tavily results get persisted.
```

## Mode 1: Hybrid Search

Run the `Mode 1: Hybrid Search` notebook section.

Say:

```text
Hybrid mode combines Oracle local memory with Tavily fresh results. This is useful when we want broad recall and fresh context in one response.
```

Point out result origins:

```text
origin=local means Oracle returned it.
origin=foreign means Tavily returned it during this call.
```

Do not spend too long here. Show the result origins, then say you will prove persistence in SQL Developer after all three modes.

If someone asks for immediate proof, run:

```sql
SELECT RETRIEVAL_QUERY,
       SOURCE_URL,
       SOURCE_TITLE,
       RETRIEVAL_MODE,
       PROVIDER_NAME,
       DBMS_LOB.SUBSTR(CONTENT, 160, 1) AS CONTENT_SNIPPET
FROM TAVILY_DOCUMENTS
WHERE PROVIDER_NAME = 'tavily'
ORDER BY RETRIEVAL_TIMESTAMP DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY;
```

Say if you run the query:

```text
This proves that the Tavily result did not disappear after the request. Oracle now has it as durable memory with provenance.
```

## Mode 2: Freshness Cache

Run the `Mode 2: Freshness Cache Search` notebook section.

Say:

```text
Freshness-cache mode checks only fresh Oracle cache rows. If the cache hit is good enough, Tavily is skipped. If not, Tavily refreshes the result and writes it back.
```

Run the first call and second call. Explain quickly:

```text
The first call may be foreign if there is no fresh cache row yet.
The second call should become local if the new row is inside the TTL and meets the score threshold.
```

Show the key knobs:

```python
cache_ttl_seconds
cache_score_threshold
persistence_depth="cache_only"
```

## Mode 3: Cache Then Memory

Run the `Mode 3: Cache Then Memory Search` notebook section.

Say:

```text
This is the layered agent workflow.

First, Oracle checks fresh cache.
Second, Oracle checks durable memory.
Only if both miss does the client call Tavily.
```

Show these knobs:

```python
memory_score_threshold
memory_max_results
persistence_depth="cache_plus_memory"
```

This is the most important live section. Spend slightly more time here than on the first two modes.

Then run the lifecycle metadata inspection cell.

In SQL Developer, run:

```sql
SELECT MEMORY_SCOPE,
       EXPIRES_AT,
       LAST_SEEN_AT,
       QUERY_COUNT,
       SOURCE_URL,
       CONTENT_HASH,
       RETRIEVAL_MODE,
       DBMS_LOB.SUBSTR(CONTENT, 160, 1) AS CONTENT_SNIPPET
FROM TAVILY_DOCUMENTS
WHERE PROVIDER_NAME = 'tavily'
ORDER BY LAST_SEEN_AT DESC NULLS LAST, RETRIEVAL_TIMESTAMP DESC NULLS LAST
FETCH FIRST 10 ROWS ONLY;
```

Explain in one minute:

```text
MEMORY_SCOPE tells us whether a row is cache_only or cache_plus_memory.

cache_only rows are safe to delete after expiration.
cache_plus_memory rows can still be useful as durable memory after the cache window expires.

SOURCE_URL and CONTENT_HASH are optional stable keys for Oracle MERGE upsert.
QUERY_COUNT can increment on matched upserts.
```

## Comparison Table

Scroll to `Compare All Three Retrieval Modes`.

Say:

```text
This table is the summary of the feature.

hybrid_search is memory plus freshness together.
freshness_cache is fresh cache or Tavily.
cache_then_memory is cache, then memory, then Tavily.
```

## Cleanup And Retention

Scroll to `Cleanup / Optional Reset`.

Say only if there is time or someone asks about database growth:

```text
There are two cleanup levels.

cleanup_cache() is manual cleanup.
auto_cleanup_cache=True turns cleanup into a search-triggered retention policy.

It is intentionally not a background thread. It runs before search, only after cache_cleanup_interval_seconds has elapsed.
```

Show:

```python
cleanup_cache()
auto_cleanup_cache=True
cache_cleanup_interval_seconds
```

## Tests

Do not run this during the 10-minute demo unless asked. Keep it ready as proof:

```bash
.venv/bin/python -m pytest tests/test_hybrid_rag_oracle.py tests/test_hybrid_rag_safety.py
```

If they specifically ask for the full suite, run:

```bash
.venv/bin/python -m pytest
```

Expected from the last verified branch run:

```text
104 passed
```

## Closing Script

Say:

```text
The value here is not that Oracle replaces Tavily. Tavily remains the fresh search provider.

Oracle makes Tavily results reusable, auditable, queryable, and memory-aware.

The branch adds the missing memory-layer pieces: cache_then_memory mode, lifecycle metadata, URL/content-hash upsert, persistence limits, cleanup/retention, convenience connection parameters, tests, docs, and the updated notebook demo.
```

## Best 60-Second Version

If time is short, show only:

1. Branch name.
2. Three initialized clients in notebook.
3. One `hybrid_search` run.
4. One `freshness_cache` repeated run.
5. One `cache_then_memory` run.
6. SQL Developer lifecycle metadata query.
7. Test result summary.

Say:

```text
The strongest proof is origin plus SQL Developer.

When origin is foreign, Tavily supplied the result.
When origin is local, Oracle supplied it.
SQL Developer shows the rows being stored with memory scope, expiry, query count, source URL, and content hash.
```
