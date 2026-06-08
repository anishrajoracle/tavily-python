# MongoDB Provider for Tavily Hybrid RAG

This provider keeps the original MongoDB-backed Hybrid RAG behavior for `TavilyHybridClient`.

MongoDB acts as the local vector store. Tavily supplies fresh external results, and `save_foreign=True` can write Tavily results back into the MongoDB collection for future local retrieval.

## Retrieval Flow

MongoDB currently supports `retrieval_mode="hybrid_search"`.

```text
User query
  -> embed query
  -> search MongoDB vector index
  -> optionally search Tavily
  -> merge local + Tavily results
  -> rerank
  -> optionally save Tavily results into MongoDB
```

Oracle-only modes such as `freshness_cache` and `cache_then_memory` are intentionally rejected for MongoDB.

## Connection Pattern

Your application can either pass an existing MongoDB collection:

```python
from pymongo import MongoClient
from tavily import TavilyHybridClient

mongo = MongoClient("mongodb://localhost:27017")
collection = mongo["my_database"]["my_collection"]

client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="mongodb",
    collection=collection,
    index="vector_search_index",
    embeddings_field="embeddings",
    content_field="content",
)
```

Or use the convenience connection parameters:

```python
from tavily import TavilyHybridClient

client = TavilyHybridClient(
    api_key="tvly-YOUR_API_KEY",
    db_provider="mongodb",
    mongo_uri="mongodb://localhost:27017",
    mongo_database="my_database",
    mongo_collection="my_collection",
    index="vector_search_index",
)
```

When the SDK creates the MongoDB client through `mongo_uri`, `client.close()` closes that managed client.

## Expected Collection Shape

The provider expects each searchable document to contain:

| Field | Purpose |
| --- | --- |
| `content` | Text returned in local search results. Configurable with `content_field`. |
| `embeddings` | Vector embedding used by MongoDB Atlas Vector Search. Configurable with `embeddings_field`. |

You can store extra metadata in the same documents, but the default local result projection only returns:

- `content`
- `score`
- `origin="local"`

## Vector Index Requirements

The configured MongoDB search index must:

- exist on the collection,
- have `type="vectorSearch"`,
- include the configured embeddings field,
- use a vector field type,
- use cosine similarity.

`validate_index()` checks this during `TavilyHybridClient` initialization.

## Persistence Behavior

When `save_foreign=True`, Tavily results are embedded and inserted with:

```python
{
    content_field: result["content"],
    embeddings_field: result["embeddings"],
}
```

When `save_foreign` is a function, the function receives each Tavily result and can return a custom MongoDB document. Returning `None` skips that result.

The MongoDB provider uses append-style persistence today. It does not currently implement TTL cleanup, URL/content-hash upsert, semantic deduplication, or cache/memory lifecycle metadata. Those controls are Oracle-specific in the current implementation.

## Code Layout

MongoDB-specific implementation files:

- `tavily/databases/mongodb/mongodb.py`
- `tavily/databases/mongodb/__init__.py`

Shared Hybrid RAG orchestration lives in:

- `tavily/hybrid_rag/hybrid_rag.py`
- `tavily/hybrid_rag/embeddings.py`

MongoDB remains separate from the Oracle provider, so Oracle-specific cache and memory behavior does not change the existing MongoDB search path.
