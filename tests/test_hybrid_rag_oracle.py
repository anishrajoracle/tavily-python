import pytest

from tavily import TavilyHybridClient
from tavily.databases import oracledb as oracle_database


DEFAULT_SCHEMA_ROWS = [
    ("CONTENT", "CLOB"),
    ("EMBEDDINGS", "VECTOR"),
    ("SITE_URL", "VARCHAR2"),
    ("RAW_PAYLOAD", "CLOB"),
    ("SOURCE_URL", "VARCHAR2"),
    ("SOURCE_TITLE", "VARCHAR2"),
    ("RETRIEVAL_QUERY", "VARCHAR2"),
    ("RETRIEVAL_TIMESTAMP", "TIMESTAMP WITH TIME ZONE"),
    ("RETRIEVAL_MODE", "VARCHAR2"),
    ("CACHE_HIT", "NUMBER"),
    ("INSERTED_FROM", "VARCHAR2"),
    ("PROVIDER_NAME", "VARCHAR2"),
]


class FakeCursor:
    def __init__(self, rows=None, schema_rows=None, fetchone_results=None):
        self.executed = None
        self.executed_calls = []
        self.executemany_call = None
        self.rows = rows
        self.schema_rows = schema_rows
        self.active_rows = None
        self.fetchone_results = fetchone_results or []

        if self.rows is None:
            self.rows = [("local content", 0.75, "local")]
        if self.schema_rows is None:
            self.schema_rows = DEFAULT_SCHEMA_ROWS

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, **kwargs):
        self.executed = (sql, kwargs)
        self.executed_calls.append((sql, kwargs))
        if "USER_TAB_COLUMNS" in sql:
            self.active_rows = self.schema_rows
        else:
            self.active_rows = self.rows

    def executemany(self, sql, rows):
        self.executemany_call = (sql, rows)

    def fetchall(self):
        return self.active_rows if self.active_rows is not None else self.rows

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


class FakeConnection:
    def __init__(self, rows=None, schema_rows=None, fetchone_results=None):
        self.cursor_instance = FakeCursor(
            rows=rows,
            schema_rows=schema_rows,
            fetchone_results=fetchone_results,
        )
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
                    "url": "https://example.com/oracle",
                    "title": "Oracle example",
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
    assert "CONTAINS" not in sql


def test_oracle_native_hybrid_search_uses_oracle_text_and_metadata_filters():
    connection = FakeConnection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        enable_native_hybrid_search=True,
        oracle_metadata_filters={"provider_name": "tavily"},
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    client.search("test query", max_local=1, max_foreign=0)

    sql, kwargs = connection.cursor_instance.executed
    assert "CONTAINS(CONTENT, :text_query, 1) > 0" in sql
    assert "SCORE(1) / 100 AS text_score" in sql
    assert "WITH vector_candidates AS" in sql
    assert "UNION ALL" in sql
    assert "VECTOR_DISTANCE(EMBEDDINGS, :query_vector, COSINE)" in sql
    assert "PROVIDER_NAME = :metadata_filter_0" in sql
    assert kwargs["text_query"] == "test query"
    assert kwargs["metadata_filter_0"] == "tavily"


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

    oracle_database.insert_documents(client, [
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


def test_oracle_save_foreign_can_store_json_payload_and_provenance_metadata():
    connection = FakeConnection()
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        enable_oracle_json_payload=True,
        enable_provenance_metadata=True,
        embedding_function=lambda texts, _: [[0.7, 0.8, 0.9] for _ in texts],
        ranking_function=lambda _, documents, __: documents,
    )
    client.tavily = FakeTavilyClient()

    client.search(
        "test query",
        max_local=0,
        max_foreign=1,
        save_foreign=True,
    )

    sql, rows = connection.cursor_instance.executemany_call
    row = rows[0]
    raw_payload = row["RAW_PAYLOAD"]
    assert "RAW_PAYLOAD" in sql
    assert row["SOURCE_URL"] == "https://example.com/oracle"
    assert row["SOURCE_TITLE"] == "Oracle example"
    assert row["RETRIEVAL_QUERY"] == "test query"
    assert row["RETRIEVAL_MODE"] == "hybrid_search"
    assert row["CACHE_HIT"] == 0
    assert row["INSERTED_FROM"] == "tavily"
    assert row["PROVIDER_NAME"] == "tavily"
    assert raw_payload
    assert '"provider_name": "tavily"' in raw_payload
    assert '"url": "https://example.com/oracle"' in raw_payload


def test_oracle_insert_schema_validation_rejects_missing_columns():
    schema_rows = [
        ("CONTENT", "CLOB"),
    ]
    connection = FakeConnection(schema_rows=schema_rows)
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    with pytest.raises(ValueError, match="missing columns.*EMBEDDINGS"):
        oracle_database.insert_documents(client, [
            {
                "content": "foreign content",
                "embeddings": [0.4, 0.5, 0.6],
            }
        ])

    assert connection.cursor_instance.executemany_call is None
    assert connection.committed is False


def test_oracle_insert_schema_validation_rejects_wrong_vector_column_type():
    schema_rows = [
        ("CONTENT", "CLOB"),
        ("EMBEDDINGS", "CLOB"),
    ]
    connection = FakeConnection(schema_rows=schema_rows)
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    with pytest.raises(ValueError, match="EMBEDDINGS.*VECTOR-compatible"):
        oracle_database.insert_documents(client, [
            {
                "content": "foreign content",
                "embeddings": [0.4, 0.5, 0.6],
            }
        ])

    assert connection.cursor_instance.executemany_call is None
    assert connection.committed is False


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


def test_oracle_vector_index_helper_creates_index_when_missing():
    connection = FakeConnection(fetchone_results=[(0,)])
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        vector_index_name="tavily_docs_vec_idx",
        vector_index_type="HNSW",
        vector_index_distance="COSINE",
        vector_index_neighbors=32,
        vector_index_efconstruction=200,
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    created = client.ensure_oracle_vector_index()

    assert created is True
    assert connection.committed is True
    _, create_kwargs = connection.cursor_instance.executed_calls[-1]
    assert "DBMS_VECTOR.CREATE_INDEX" in connection.cursor_instance.executed_calls[-1][0]
    assert create_kwargs["index_name"] == "TAVILY_DOCS_VEC_IDX"
    assert create_kwargs["table_name"] == "TAVILY_DOCUMENTS"
    assert create_kwargs["idx_vector_col"] == "EMBEDDINGS"
    assert create_kwargs["idx_organization"] == "INMEMORY NEIGHBOR GRAPH"
    assert create_kwargs["idx_distance_metric"] == "COSINE"
    assert '"type": "HNSW"' in create_kwargs["idx_parameters"]
    assert '"neighbors": 32' in create_kwargs["idx_parameters"]
    assert '"efConstruction": 200' in create_kwargs["idx_parameters"]


def test_oracle_vector_index_helper_skips_existing_index():
    connection = FakeConnection(fetchone_results=[(1,)])
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        vector_index_name="tavily_docs_vec_idx",
        embedding_function=lambda texts, _: [[0.1, 0.2, 0.3]],
        ranking_function=lambda _, documents, __: documents,
    )

    created = client.ensure_oracle_vector_index()

    assert created is False
    assert connection.committed is False
    assert len(connection.cursor_instance.executed_calls) == 1


def test_oracle_semantic_dedup_skips_near_duplicate_foreign_insert():
    connection = FakeConnection(rows=[], fetchone_results=[(0.99,)])
    client = TavilyHybridClient(
        api_key="tvly-test",
        db_provider="oracle",
        connection=connection,
        table_name="tavily_documents",
        dedup_similarity_threshold=0.95,
        embedding_function=lambda texts, _: [[0.7, 0.8, 0.9] for _ in texts],
        ranking_function=lambda _, documents, __: documents,
    )
    client.tavily = FakeTavilyClient()

    results = client.search(
        "test query",
        max_local=0,
        max_foreign=1,
        save_foreign=True,
    )

    assert results == [
        {"content": "foreign oracle content", "score": 0.91, "origin": "foreign"}
    ]
    assert connection.cursor_instance.executemany_call is None
    assert connection.committed is False
    assert "FETCH FIRST 1 ROWS ONLY" in connection.cursor_instance.executed_calls[-1][0]


def test_oracle_rejects_unsafe_identifiers():
    with pytest.raises(ValueError, match="Invalid Oracle identifier"):
        TavilyHybridClient(
            api_key="tvly-test",
            db_provider="oracle",
            connection=FakeConnection(),
            table_name="documents; drop table users",
        )
