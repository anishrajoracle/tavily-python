# Tavily Python SDK

[![GitHub stars](https://img.shields.io/github/stars/tavily-ai/tavily-python?style=social)](https://github.com/tavily-ai/tavily-python/stargazers)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/tavily-python)](https://pypi.org/project/tavily-python/)
[![License](https://img.shields.io/github/license/tavily-ai/tavily-python)](https://github.com/tavily-ai/tavily-python/blob/main/LICENSE)
[![CI](https://github.com/tavily-ai/tavily-python/actions/workflows/tests.yml/badge.svg)](https://github.com/tavily-ai/tavily-python/actions)

The Tavily Python wrapper allows for easy interaction with the Tavily API, offering the full range of our search, extract, crawl, map, and research functionalities directly from your Python programs. Easily integrate smart search, content extraction, and research capabilities into your applications, harnessing Tavily's powerful features.

## Installing

```bash
pip install tavily-python
```

# Tavily Search

Search lets you search the web for a given query.

## Usage

Below are some code snippets that show you how to interact with our search API. The different steps and components of this code are explained in more detail in the API Methods section further down.

### Getting and printing the full Search API response

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Executing a simple search query
response = tavily_client.search("Who is Leo Messi?")

# Step 3. That's it! You've done a Tavily Search!
print(response)
```

### Using exact match to find specific names or phrases

```python
from tavily import TavilyClient

client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Use exact_match=True to only return results containing the exact phrase(s) inside quotes
response = client.search(
    query='"John Smith" CEO Acme Corp',
    exact_match=True
)
print(response)
```

This is equivalent to directly querying our REST API.

### Generating context for a RAG Application

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Executing a context search query
context = tavily_client.get_search_context(query="What happened during the Burning Man floods?")

# Step 3. That's it! You now have a context string that you can feed directly into your RAG Application
print(context)
```

This is how you can generate precise and fact-based context for your RAG application in one line of code.

### Getting a quick answer to a question

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Executing a Q&A search query
answer = tavily_client.qna_search(query="Who is Leo Messi?")

# Step 3. That's it! Your question has been answered!
print(answer)
```

This is how you get accurate and concise answers to questions, in one line of code. Perfect for usage by LLMs!

# Tavily Extract

Extract web page content from one or more specified URLs.

## Usage

Below are some code snippets that demonstrate how to interact with our Extract API. Each step and component of this code is explained in greater detail in the API Methods section below.

### Extracting Raw Content from Multiple URLs using Tavily Extract API

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Defining the list of URLs to extract content from
urls = [
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "https://en.wikipedia.org/wiki/Machine_learning",
    "https://en.wikipedia.org/wiki/Data_science",
    "https://en.wikipedia.org/wiki/Quantum_computing",
    "https://en.wikipedia.org/wiki/Climate_change"
] # You can provide up to 20 URLs simultaneously

# Step 3. Executing the extract request
response = tavily_client.extract(urls=urls, include_images=True)

# Step 4. Printing the extracted raw content
for result in response["results"]:
    print(f"URL: {result['url']}")
    print(f"Raw Content: {result['raw_content']}")
    print(f"Images: {result['images']}\n")

# Note that URLs that could not be extracted will be stored in response["failed_results"]
```

# Tavily Crawl

Crawl lets you traverse a website's content starting from a base URL.

> **Note**: Crawl is currently available on an invite-only basis. For more information, please visit [crawl.tavily.com](https://crawl.tavily.com)

## Usage

Below are some code snippets that demonstrate how to interact with our Crawl API. Each step and component of this code is explained in greater detail in the API Methods section below.

### Crawling a website with instructions

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Defining the starting URL
start_url = "https://wikipedia.org/wiki/Lemon"

# Step 3. Executing the crawl request with instructions to surface only pages about citrus fruits
response = tavily_client.crawl(
    url=start_url,
    max_depth=3,
    limit=50,
    instructions="Find all pages on citrus fruits"
)

# Step 4. Printing pages matching the query
for result in response["results"]:
    print(f"URL: {result['url']}")
    print(f"Snippet: {result['raw_content'][:200]}...\n")

```

# Tavily Map

Map lets you discover and visualize the structure of a website starting from a base URL.

## Usage

Below are some code snippets that demonstrate how to interact with our Map API. Each step and component of this code is explained in greater detail in the API Methods section below.

### Mapping a website with instructions

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Defining the starting URL
start_url = "https://wikipedia.org/wiki/Lemon"

# Step 3. Executing the map request with parameters to focus on specific pages
response = tavily_client.map(
    url=start_url,
    max_depth=2,
    limit=30,
    instructions="Find pages on citrus fruits"
)

# Step 4. Printing the site structure
for result in response["results"]:
    print(f"URL: {result['url']}")

```

# Tavily Research

Research lets you create comprehensive research reports on any topic, with automatic source gathering, analysis, and structured output.

## Usage

Below are some code snippets that demonstrate how to interact with our Research API. Each step and component of this code is explained in greater detail in the API Methods section below.

### Creating a research task and retrieving results

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Creating a research task
response = tavily_client.research(
    input="Research the latest developments in AI",
    model="pro",
    citation_format="apa"
)

# Step 3. Retrieving the research results
request_id = response["request_id"]
result = tavily_client.get_research(request_id)

# Step 4. Printing the research report
print(f"Status: {result['status']}")
print(f"Content: {result['content']}")
print(f"Sources: {len(result['sources'])} sources found")
```

### Streaming research results

```python
from tavily import TavilyClient

# Step 1. Instantiating your TavilyClient
tavily_client = TavilyClient(api_key="tvly-YOUR_API_KEY")

# Step 2. Creating a streaming research task
stream = tavily_client.research(
    input="Research the latest developments in AI",
    model="pro",
    stream=True
)

# Step 3. Processing the stream as it arrives
for chunk in stream:
    print(chunk.decode('utf-8'))
```

# Tavily Hybrid RAG

`TavilyHybridClient` can use MongoDB or OracleDB as a local vector store. MongoDB keeps the existing hybrid-search behavior only.

OracleDB supports three retrieval modes:

- `retrieval_mode="hybrid_search"`: search Oracle first, search Tavily when `max_foreign > 0`, merge and rerank local plus foreign results, and optionally persist Tavily results with `save_foreign=True`.
- `retrieval_mode="freshness_cache"`: Oracle-only. Search fresh Oracle rows first, return Oracle results when at least one row meets `cache_score_threshold`, and skip Tavily on that cache hit. On a cache miss, call Tavily, optionally persist Tavily results into Oracle, and return Tavily results.
- `retrieval_mode="cache_then_memory"`: Oracle-only. Search fresh Oracle cache rows first, search durable Oracle memory rows next, and call Tavily only when both local tiers miss.

Freshness-cache and cache-then-memory modes expect Oracle rows to have an `ADDED_AT` timestamp column, for example `ADDED_AT TIMESTAMP DEFAULT SYSTIMESTAMP`, so the client can apply `cache_ttl_seconds`. Cache-then-memory can also use `MEMORY_SCOPE`, `EXPIRES_AT`, `LAST_SEEN_AT`, and `QUERY_COUNT` when `enable_oracle_memory_metadata=True`.

## Why Oracle

The Oracle path in `TavilyHybridClient` is designed for applications that want Tavily web results to become durable retrieval context over time. Existing Oracle support is additive to the standard Tavily SDK and the MongoDB hybrid RAG workflow.

Oracle-specific value already implemented in this repository:

| Capability | Current support |
| --- | --- |
| Native VECTOR storage | Oracle rows store embeddings in a `VECTOR` column and local retrieval uses `VECTOR_DISTANCE(...)`. |
| Native JSON storage | `enable_oracle_json_payload=True` can persist the raw Tavily payload and retrieval provenance into a JSON column. |
| Hybrid retrieval | `enable_native_hybrid_search=True` combines Oracle Vector Search with Oracle Text scoring for local candidates. |
| Persistent cache | `retrieval_mode="freshness_cache"` checks fresh Oracle rows before calling Tavily and can write Tavily misses back to Oracle. |
| Cache then memory | `retrieval_mode="cache_then_memory"` checks fresh cache first, durable Oracle memory second, and Tavily last. |
| Long-term memory | `retrieval_mode="hybrid_search"` can query persisted Oracle rows, combine them with fresh Tavily results, and rerank the merged set. |
| Oracle reviewability | Optional provenance columns record source URL, source title, retrieval query, retrieval mode, cache-hit state, and provider. |
| Semantic deduplication | `dedup_similarity_threshold` can skip near-duplicate Oracle inserts by comparing the nearest stored vector. |

## Architecture Overview

The Oracle freshness-cache flow follows an Oracle-first lookup, Tavily fallback, and optional Oracle write-through persistence model:

```text
User Query
     |
     v
Oracle Cache Lookup
     |
     +---- Hit ---> Return
     |
     +---- Miss
                |
                v
           Tavily Search
                |
                v
        Oracle Persistence
                |
                v
             Return
```

For `retrieval_mode="freshness_cache"`, the client embeds the query, searches Oracle rows inside the configured TTL window, and returns Oracle results when at least one local result meets `cache_score_threshold`. On a miss, it calls Tavily, optionally saves Tavily results when `save_foreign=True`, and returns the fresh Tavily results.

For `retrieval_mode="cache_then_memory"`, the client performs the same freshness-cache check first. If that misses, it searches durable Oracle memory rows with `memory_score_threshold` and only calls Tavily when both local tiers miss.

For `retrieval_mode="hybrid_search"`, the client searches Oracle local memory, calls Tavily when `max_foreign > 0`, projects both result sets into the existing result shape, reranks them with the configured ranking function, and optionally persists Tavily results.

For a deeper architecture map, capability matrix, and implementation reference table, see [docs/oracle_architecture.md](docs/oracle_architecture.md).

Example notebook:

- `examples/oracle/oracle_tavily.ipynb` — Complete Oracle AI Database demo showing hybrid search, cache-only mode, cache-then-memory mode, VECTOR search, JSON provenance, semantic deduplication, and Tavily fallback.

```python
from tavily import TavilyHybridClient

hybrid_client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    retrieval_mode="hybrid_search",
)

freshness_client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    retrieval_mode="freshness_cache",
    cache_ttl_seconds=3600,
    cache_score_threshold=0.75,
)

cache_then_memory_client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    retrieval_mode="cache_then_memory",
    cache_ttl_seconds=3600,
    cache_score_threshold=0.75,
    memory_score_threshold=0.65,
    persistence_depth="cache_plus_memory",
    enable_oracle_memory_metadata=True,
)

results = cache_then_memory_client.search(
    "latest Oracle Database vector search features",
    max_results=5,
    max_local=5,
    max_foreign=5,
    save_foreign=True,
)
```

Oracle AI Database features are opt-in and Oracle-only:

```python
oracle_client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    enable_native_hybrid_search=True,
    oracle_metadata_filters={"provider_name": "tavily"},
    enable_oracle_json_payload=True,
    enable_provenance_metadata=True,
    dedup_similarity_threshold=0.95,
)
```

`enable_native_hybrid_search=True` adds Oracle Text scoring to the local Oracle candidate query while preserving the existing Tavily merge and rerank flow. The Oracle table should have a Text index on the content column, for example:

```sql
CREATE INDEX tavily_docs_text_idx
ON tavily_documents(content)
INDEXTYPE IS CTXSYS.CONTEXT;
```

`enable_oracle_json_payload=True` and `enable_provenance_metadata=True` add write-through storage for Tavily provenance. These options expect matching Oracle columns, for example:

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

You can create an Oracle vector index explicitly when needed:

```python
oracle_client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="oracle",
    connection=oracle_connection,
    table_name="TAVILY_DOCUMENTS",
    vector_index_name="TAVILY_DOCS_VEC_IDX",
    vector_index_type="HNSW",
    vector_index_distance="COSINE",
)

created = oracle_client.ensure_oracle_vector_index()
```

Provenance can be inspected with normal Oracle JSON SQL:

```sql
SELECT source_url,
       JSON_VALUE(raw_payload, '$.provenance.retrieval_query') AS retrieval_query
FROM tavily_documents
WHERE JSON_EXISTS(raw_payload, '$.provenance.provider_name');
```

## Troubleshooting Guide

Common setup issues are usually configuration-related:

| Issue | Resolution |
| --- | --- |
| Missing Tavily API key | Set `TAVILY_API_KEY`, pass `api_key=...`, or provide a pre-authenticated custom session/client. |
| Oracle connection failure | Verify `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN`, service name, network access, and whether `ORACLE_SYSDBA=1` is required by your local setup. |
| Missing Oracle dependencies | Install the optional Oracle extra with `python -m pip install -e ".[oracle]"` or install `oracledb` in your environment. |
| Vector search errors | Confirm the table has a compatible `VECTOR` column, stored vectors have the expected dimension, and the database supports Oracle Vector Search. |
| Vector index creation errors | Ensure the database supports `DBMS_VECTOR.CREATE_INDEX`, the user has privileges, and the requested index name is a valid Oracle identifier. |
| Native hybrid search errors | Create an Oracle Text index on the content column before using `enable_native_hybrid_search=True`. |
| JSON/provenance insert errors | Add the optional `RAW_PAYLOAD` and provenance columns before enabling JSON/provenance persistence. |
| Freshness cache always misses | Confirm the timestamp column exists, defaults to `SYSTIMESTAMP`, and `cache_ttl_seconds` plus `cache_score_threshold` match your data. |

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed diagnostics and example fixes.

## Contributing Guide

Contributors should preserve the existing public APIs and user workflows. Keep Oracle, Tavily, MongoDB, cache, retrieval, persistence, hybrid search, deduplication, and vector search behavior backward compatible.

Local development basics:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[oracle,mongodb]" pytest
python -m pytest
```

Lightweight quality tooling is configured but intentionally conservative:

```bash
ruff check .
mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for repository structure, coding standards, and pull request guidance.

## Deployment Guide

The current Oracle deployment model expects the application to provide:

- A Tavily API key or a pre-authenticated custom HTTP session/client.
- A `python-oracledb` connection.
- An Oracle table with content and embedding columns.
- Optional timestamp, JSON, provenance, Oracle Text, and vector index setup depending on enabled features.

Local Oracle and Oracle 23ai setups can use the same client configuration shown above. The repository does not require a new service, schema migration runner, or connection factory; existing examples pass an already-created Oracle connection into `TavilyHybridClient`.

See [DEPLOYMENT.md](DEPLOYMENT.md) for local Oracle usage, Oracle 23ai notes, schema examples, and environment variables used by the examples.

## Advanced: Custom Session / Client Injection

For enterprise environments that proxy Tavily traffic through an API gateway (e.g., for centralized auth, logging, or policy enforcement), you can pass a pre-configured HTTP session instead of a Tavily API key.

### Sync (custom `requests.Session`)

```python
import requests
from tavily import TavilyClient

# Pre-configure a session with your gateway's auth
session = requests.Session()
session.headers["Authorization"] = "Bearer your-gateway-token"
session.headers["X-Subscription-Key"] = "your-subscription-key"

# No Tavily API key needed — auth is handled by the session
client = TavilyClient(
    session=session,
    api_base_url="https://your-gateway.com/tavily",
)

response = client.search("latest AI research")
```

### Async (custom `httpx.AsyncClient`)

```python
import httpx
from tavily import AsyncTavilyClient

# Pre-configure an async client with your gateway's auth
custom_client = httpx.AsyncClient(
    headers={"Authorization": "Bearer your-gateway-token"},
    base_url="https://your-gateway.com/tavily",
)

client = AsyncTavilyClient(client=custom_client)

response = await client.search("latest AI research")
```

**Key behaviors:**
- If a custom session/client is provided, `api_key` is optional
- Custom session headers take precedence over SDK defaults (e.g., your `Authorization` won't be overwritten)
- Custom session proxies take precedence over SDK proxy settings
- The SDK will **not** close externally-provided sessions — you manage the lifecycle

## Session & User Tracking

`session_id`, `human_id`, and `client_name` are optional identifiers that help attribute requests to a logical session, an end user, and a named client. All three are sent as HTTP headers (`X-Session-Id`, `X-Human-Id`, `X-Client-Name`) and are never persisted in raw form — `human_id` is hashed server-side.

Set them once at client init, or per-call (per-call wins):

```python
from tavily import TavilyClient

# Client-level — applied to every request
client = TavilyClient(
    api_key="tvly-YOUR_API_KEY",
    session_id="my-session-123",
    human_id="internal-user-id-42",
    client_name="my-app",
)

# Per-call override
client.search("hello", session_id="ad-hoc-session")
```

All three are opt-in. Leave them unset and the SDK sends nothing — behavior is identical to earlier versions.

## Documentation

For a complete guide on how to use the different endpoints and their parameters, please head to our [Python API Reference](https://docs.tavily.com/sdk/python/reference).

## Cost

Tavily is free for personal use for up to 1,000 credits per month.
Head to the [Credits & Pricing](https://docs.tavily.com/documentation/api-credits) in our documentation to learn more about how many API credits each request costs.

## License

This project is licensed under the terms of the MIT license.

## Contact

If you are encountering issues while using Tavily, please email us at support@tavily.com. We'll be happy to help you.

If you want to stay updated on the latest Tavily news and releases, head to our [Developer Community](https://community.tavily.com) to learn more!
