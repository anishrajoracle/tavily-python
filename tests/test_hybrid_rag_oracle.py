import pytest

from tavily import TavilyHybridClient


class FakeCursor:
    def __init__(self):
        self.executed = None
        self.executemany_call = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, **kwargs):
        self.executed = (sql, kwargs)

    def executemany(self, sql, rows):
        self.executemany_call = (sql, rows)

    def fetchall(self):
        return [("local content", 0.75, "local")]


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


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


def test_oracle_rejects_unsafe_identifiers():
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        TavilyHybridClient(
            api_key="tvly-test",
            db_provider="oracle",
            connection=FakeConnection(),
            table_name="documents; drop table users",
        )
