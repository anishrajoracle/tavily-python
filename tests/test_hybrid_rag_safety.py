import pytest

from tavily import TavilyHybridClient


class FakeMongoCollection:
    def __init__(self):
        self.insert_many_called = False

    def list_search_indexes(self):
        return [
            {
                "name": "vector_search",
                "type": "vectorSearch",
                "latestDefinition": {
                    "fields": [
                        {
                            "path": "embeddings",
                            "type": "vector",
                            "similarity": "cosine",
                        }
                    ]
                },
            }
        ]

    def aggregate(self, _):
        return []

    def insert_many(self, documents):
        self.insert_many_called = True
        if not documents:
            raise AssertionError("insert_many should not be called with an empty list.")


class FakeTavilyClient:
    def search(self, *_args, **_kwargs):
        return {
            "results": [
                {
                    "content": "foreign content",
                    "score": 0.8,
                }
            ]
        }


def test_save_foreign_skips_empty_insert_after_custom_filter_removes_everything():
    collection = FakeMongoCollection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="mongodb",
        collection=collection,
        index="vector_search",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3] for _ in texts],
        ranking_function=lambda _, documents, __: documents,
    )
    client.tavily = FakeTavilyClient()

    results = client.search(
        "test query",
        save_foreign=lambda _: None,
    )

    assert results == [{"content": "foreign content", "score": 0.8, "origin": "foreign"}]
    assert collection.insert_many_called is False


def test_embedding_and_ranking_functions_must_be_callable():
    with pytest.raises(TypeError, match="embedding_function must be callable"):
        TavilyHybridClient(
            api_key="tvly-test",
            db_provider="mongodb",
            collection=FakeMongoCollection(),
            index="vector_search",
            embedding_function="not-callable",
            ranking_function=lambda _, documents, __: documents,
        )


def test_mongodb_rejects_freshness_cache_mode():
    with pytest.raises(ValueError, match="freshness_cache.*db_provider='oracle'"):
        TavilyHybridClient(
            api_key="tvly-test",
            db_provider="mongodb",
            collection=FakeMongoCollection(),
            index="vector_search",
            retrieval_mode="freshness_cache",
            embedding_function=lambda texts, _: [[0.1, 0.2, 0.3] for _ in texts],
            ranking_function=lambda _, documents, __: documents,
        )
