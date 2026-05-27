import pytest

from tavily import TavilyHybridClient


class FakeCursor:
    def __init__(self, rows=None):
        self.executed = None
        self.executed_calls = []
        self.executemany_call = None
        self.rows = rows

        if self.rows is None:
            self.rows = [("local content", 0.75, "local")]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, **kwargs):
        self.executed = (sql, kwargs)
        self.executed_calls.append((sql, kwargs))

    def executemany(self, sql, rows):
        self.executemany_call = (sql, rows)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=None):
        self.cursor_instance = FakeCursor(rows=rows)
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


class FakeTavilyClient:
    def __init__(self):
        self.calls = []

    def search(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        return {
            "results": [
                {
                    "content": "foreign oracle content",
                    "score": 0.91,
                }
            ]
        }


class FailingTavilyClient:
    def search(self, *_args, **_kwargs):
        raise AssertionError("Tavily should not be called.")


def failing_ranking_function(*_args):
    raise AssertionError("ranking_function should not be called.")


def test_oracle_search_uses_vector_distance_without_touching_mongodb_collection():
    connection = FakeConnection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    results = client.search("test query", max_local=1, max_foreign=0)

    sql, kwargs = connection.cursor_instance.executed
    assert "VECTOR_DISTANCE(EMBEDDINGS, :query_vector, COSINE)" in sql
    assert "FROM TAVILY_DOCUMENTS" in sql
    assert "FETCH FIRST 1 ROWS ONLY" in sql
    assert kwargs["query_vector"].typecode == "f"
    assert list(kwargs["query_vector"]) == pytest.approx([0.1, 0.2, 0.3])
    assert results == [{"content": "local content", "score": 0.75, "origin": "local"}]


def test_oracle_insert_converts_embeddings_to_vector_bind():
    connection = FakeConnection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    client._insert_oracle_documents([
        {
            "content": "foreign content",
            "embeddings": [0.4, 0.5, 0.6],
            "site_url": "https://example.com",
        }
    ])

    sql, rows = connection.cursor_instance.executemany_call
    assert sql == (
        "INSERT INTO TAVILY_DOCUMENTS "
        "(CONTENT, EMBEDDINGS, SITE_URL) "
        "VALUES (:CONTENT, :EMBEDDINGS, :SITE_URL)"
    )
    assert rows[0]["CONTENT"] == "foreign content"
    assert rows[0]["SITE_URL"] == "https://example.com"
    assert rows[0]["EMBEDDINGS"].typecode == "f"
    assert list(rows[0]["EMBEDDINGS"]) == pytest.approx([0.4, 0.5, 0.6])
    assert connection.committed is True


def test_oracle_freshness_cache_hit_skips_tavily_and_returns_local_results():
    connection = FakeConnection(rows=[("fresh local content", 0.82, "local")])
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        retrieval_mode="freshness_cache",
        cache_ttl_seconds=300,
        cache_score_threshold=0.8,
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3] for _ in texts],
        ranking_function=failing_ranking_function,
    )
    client.tavily = FailingTavilyClient()

    results = client.search(
        "test query",
        max_results=2,
        max_local=1,
        max_foreign=1,
        save_foreign=True,
    )

    sql, kwargs = connection.cursor_instance.executed
    assert "ADDED_AT >=" in sql
    assert "NUMTODSINTERVAL(:cache_ttl_seconds, 'SECOND')" in sql
    assert kwargs["cache_ttl_seconds"] == 300
    assert len(connection.cursor_instance.executed_calls) == 1
    assert connection.cursor_instance.executemany_call is None
    assert results == [
        {"content": "fresh local content", "score": 0.82, "origin": "local"}
    ]


def test_oracle_freshness_cache_miss_calls_tavily_and_saves_foreign_results():
    connection = FakeConnection(rows=[("low score local content", 0.4, "local")])
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        retrieval_mode="freshness_cache",
        cache_ttl_seconds=60,
        cache_score_threshold=0.8,
        embedding_function=lambda texts, _: [[0.7, 0.8, 0.9] for _ in texts],
        ranking_function=failing_ranking_function,
    )
    client.tavily = FakeTavilyClient()

    results = client.search(
        "test query",
        max_results=1,
        max_local=1,
        max_foreign=1,
        save_foreign=True,
    )

    assert len(client.tavily.calls) == 1
    sql, rows = connection.cursor_instance.executemany_call
    assert results == [
        {"content": "foreign oracle content", "score": 0.91, "origin": "foreign"}
    ]
    assert sql == (
        "INSERT INTO TAVILY_DOCUMENTS "
        "(CONTENT, EMBEDDINGS) "
        "VALUES (:CONTENT, :EMBEDDINGS)"
    )
    assert rows[0]["CONTENT"] == "foreign oracle content"
    assert rows[0]["EMBEDDINGS"].typecode == "f"
    assert list(rows[0]["EMBEDDINGS"]) == pytest.approx([0.7, 0.8, 0.9])
    assert connection.committed is True


def test_oracle_save_foreign_inserts_tavily_results():
    connection = FakeConnection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        embedding_function=lambda texts, _: [[0.7, 0.8, 0.9] for _ in texts],
        ranking_function=lambda _, documents, __: documents,
    )
    client.tavily = FakeTavilyClient()

    results = client.search(
        "test query",
        max_results=2,
        max_local=1,
        max_foreign=1,
        save_foreign=True,
    )

    sql, rows = connection.cursor_instance.executemany_call
    assert results == [
        {"content": "local content", "score": 0.75, "origin": "local"},
        {"content": "foreign oracle content", "score": 0.91, "origin": "foreign"},
    ]
    assert sql == (
        "INSERT INTO TAVILY_DOCUMENTS "
        "(CONTENT, EMBEDDINGS) "
        "VALUES (:CONTENT, :EMBEDDINGS)"
    )
    assert rows[0]["CONTENT"] == "foreign oracle content"
    assert rows[0]["EMBEDDINGS"].typecode == "f"
    assert list(rows[0]["EMBEDDINGS"]) == pytest.approx([0.7, 0.8, 0.9])
    assert connection.committed is True


def test_oracle_rejects_unsafe_identifiers():
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        TavilyHybridClient(
            api_key="tvly-test",
            db_provider="oracle",
            connection=FakeConnection(),
            table_name="documents; drop table users",
        )
