import os

import oracledb
from tavily import TavilyHybridClient


TABLE_NAME = os.environ.get("ORACLE_VECTOR_TABLE", "TAVILY_DOCS")
CONTENT_FIELD = os.environ.get("ORACLE_CONTENT_FIELD", "CONTENT")
EMBEDDINGS_FIELD = os.environ.get("ORACLE_EMBEDDINGS_FIELD", "EMBEDDINGS")


def test_embedding_function(texts, input_type):
    vectors = []
    for text in texts:
        lowered = text.lower()
        if "oracle" in lowered or "database" in lowered:
            vectors.append([1.0, 0.0, 0.0])
        elif "mongo" in lowered:
            vectors.append([0.0, 1.0, 0.0])
        else:
            vectors.append([0.5, 0.5, 0.0])
    return vectors


def passthrough_ranking_function(query, documents, top_n):
    return documents[:top_n]


def ignore_existing_table(error):
    error_obj = error.args[0]
    if getattr(error_obj, "code", None) != 955:
        raise error


def ensure_table(connection):
    with connection.cursor() as cursor:
        try:
            cursor.execute(
                f"""
                CREATE TABLE {TABLE_NAME} (
                    ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    {CONTENT_FIELD} CLOB,
                    {EMBEDDINGS_FIELD} VECTOR(3, FLOAT32)
                )
                """
            )
            connection.commit()
        except oracledb.DatabaseError as exc:
            ignore_existing_table(exc)


def seed_local_rows(client, connection):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        row_count = cursor.fetchone()[0]

    if row_count > 0:
        return

    client._insert_oracle_documents(
        [
            {
                CONTENT_FIELD: "Oracle Database vector search is working",
                EMBEDDINGS_FIELD: [1.0, 0.0, 0.0],
            },
            {
                CONTENT_FIELD: "MongoDB Atlas vector search existing path",
                EMBEDDINGS_FIELD: [0.0, 1.0, 0.0],
            },
        ]
    )


def main():
    connection = oracledb.connect(
        user=os.environ.get("ORACLE_USER", "tavily_itest"),
        password=os.environ.get("ORACLE_PASSWORD", "tavily123"),
        dsn=os.environ.get("ORACLE_DSN", "localhost:1521/FREEPDB1"),
    )

    ensure_table(connection)

    client = TavilyHybridClient(
        api_key=os.environ["TAVILY_API_KEY"],
        db_provider="oracle",
        connection=connection,
        table_name=TABLE_NAME,
        embeddings_field=EMBEDDINGS_FIELD,
        content_field=CONTENT_FIELD,
        embedding_function=test_embedding_function,
        ranking_function=passthrough_ranking_function,
    )

    seed_local_rows(client, connection)

    results = client.search(
        "latest Oracle Database vector search features",
        max_results=5,
        max_local=2,
        max_foreign=3,
        save_foreign=True,
    )

    for result in results:
        content = result["content"][:160].replace("\n", " ")
        print(result["origin"], result["score"], content)

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        print("row_count=", cursor.fetchone()[0])

    connection.close()


if __name__ == "__main__":
    main()
