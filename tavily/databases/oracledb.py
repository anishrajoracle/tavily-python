import array
from datetime import datetime, timezone
import json

from tavily.databases.config import (
    ORACLE_CACHE_HIT_FIELD,
    ORACLE_IDENTIFIER,
    ORACLE_INSERTED_FROM_FIELD,
    ORACLE_PROVIDER_NAME_FIELD,
    ORACLE_RAW_PAYLOAD_FIELD,
    ORACLE_RETRIEVAL_MODE_FIELD,
    ORACLE_RETRIEVAL_QUERY_FIELD,
    ORACLE_RETRIEVAL_TIMESTAMP_FIELD,
    ORACLE_SOURCE_TITLE_FIELD,
    ORACLE_SOURCE_URL_FIELD,
    ORACLE_VECTOR_DISTANCE_METRICS,
    ORACLE_VECTOR_INDEX_ORGANIZATIONS,
    ORACLE_VECTOR_INDEX_TYPES,
)


def validate_identifier(value, name):
    if not value or not ORACLE_IDENTIFIER.match(value):
        raise ValueError(f"Invalid Oracle identifier for {name}: {value}")
    return value.upper()


def to_vector(values):
    return array.array("f", values)


def read_lob(value):
    if hasattr(value, "read"):
        return value.read()
    return value


def search(client, query_embeddings, max_local, query=None, cache_ttl_seconds=None):
    limit = int(max_local)
    if limit < 1:
        return []

    if client.enable_native_hybrid_search and query:
        return search_native_hybrid(
            client,
            query_embeddings,
            max_local,
            query,
            cache_ttl_seconds=cache_ttl_seconds
        )

    execute_kwargs = {"query_vector": to_vector(query_embeddings)}
    freshness_filter = build_freshness_filter(
        client.cache_timestamp_field,
        cache_ttl_seconds,
        execute_kwargs
    )
    metadata_filter = build_metadata_filter(client.oracle_metadata_filters, execute_kwargs)

    sql = f"""
            SELECT {client.content_field},
                   1 - VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE) AS score,
                   'local' AS origin
            FROM {client.table_name}
            WHERE {client.embeddings_field} IS NOT NULL
              {freshness_filter}
              {metadata_filter}
            ORDER BY VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE)
            FETCH FIRST {limit} ROWS ONLY
        """

    with client.connection.cursor() as cursor:
        cursor.execute(sql, **execute_kwargs)
        return [
            {
                "content": read_lob(row[0]),
                "score": row[1],
                "origin": row[2]
            }
            for row in cursor.fetchall()
        ]


def search_native_hybrid(client, query_embeddings, max_local, query,
                         cache_ttl_seconds=None):
    limit = int(max_local)
    if limit < 1:
        return []

    execute_kwargs = {
        "query_vector": to_vector(query_embeddings),
        "text_query": query,
    }
    freshness_filter = build_freshness_filter(
        client.cache_timestamp_field,
        cache_ttl_seconds,
        execute_kwargs
    )
    metadata_filter = build_metadata_filter(client.oracle_metadata_filters, execute_kwargs)

    sql = f"""
            WITH vector_candidates AS (
                SELECT ROWID AS rid,
                       1 - VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE) AS vector_score,
                       0 AS text_score
                FROM {client.table_name}
                WHERE {client.embeddings_field} IS NOT NULL
                  {freshness_filter}
                  {metadata_filter}
                ORDER BY VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE)
                FETCH FIRST {limit} ROWS ONLY
            ),
            text_candidates AS (
                SELECT ROWID AS rid,
                       1 - VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE) AS vector_score,
                       SCORE(1) / 100 AS text_score
                FROM {client.table_name}
                WHERE {client.embeddings_field} IS NOT NULL
                  AND CONTAINS({client.content_field}, :text_query, 1) > 0
                  {freshness_filter}
                  {metadata_filter}
                ORDER BY SCORE(1) DESC
                FETCH FIRST {limit} ROWS ONLY
            ),
            ranked_candidates AS (
                SELECT rid,
                       MAX(vector_score) + MAX(text_score) AS score
                FROM (
                    SELECT rid, vector_score, text_score FROM vector_candidates
                    UNION ALL
                    SELECT rid, vector_score, text_score FROM text_candidates
                )
                GROUP BY rid
                ORDER BY score DESC
                FETCH FIRST {limit} ROWS ONLY
            )
            SELECT source.{client.content_field},
                   ranked.score,
                   'local' AS origin
            FROM {client.table_name} source
            JOIN ranked_candidates ranked ON source.ROWID = ranked.rid
            ORDER BY ranked.score DESC
        """

    with client.connection.cursor() as cursor:
        cursor.execute(sql, **execute_kwargs)
        return [
            {
                "content": read_lob(row[0]),
                "score": row[1],
                "origin": row[2]
            }
            for row in cursor.fetchall()
        ]


def build_freshness_filter(cache_timestamp_field, cache_ttl_seconds, execute_kwargs):
    if cache_ttl_seconds is None:
        return ""

    execute_kwargs["cache_ttl_seconds"] = cache_ttl_seconds
    return (
        f"AND {cache_timestamp_field} >= "
        "CAST(SYSTIMESTAMP AS TIMESTAMP) - "
        "NUMTODSINTERVAL(:cache_ttl_seconds, 'SECOND')"
    )


def build_metadata_filter(oracle_metadata_filters, execute_kwargs):
    if not oracle_metadata_filters:
        return ""

    clauses = []
    for i, (key, value) in enumerate(oracle_metadata_filters.items()):
        column = validate_identifier(key, "oracle_metadata_filters key")

        if value is None:
            clauses.append(f"{column} IS NULL")
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
            if not values:
                clauses.append("1 = 0")
                continue

            bind_names = []
            for j, item in enumerate(values):
                bind_name = f"metadata_filter_{i}_{j}"
                bind_names.append(f":{bind_name}")
                execute_kwargs[bind_name] = item
            clauses.append(f"{column} IN ({', '.join(bind_names)})")
        else:
            bind_name = f"metadata_filter_{i}"
            execute_kwargs[bind_name] = value
            clauses.append(f"{column} = :{bind_name}")

    return "AND " + " AND ".join(clauses)


def build_persistence_metadata(client, result, query, cache_hit):
    if not (client.enable_oracle_json_payload or client.enable_provenance_metadata):
        return {}

    timestamp = datetime.now(timezone.utc)
    metadata = {}

    if client.enable_oracle_json_payload:
        payload = {
            "result": result,
            "provenance": {
                "source_url": result.get("url"),
                "retrieval_query": query,
                "retrieval_timestamp": timestamp.isoformat(),
                "retrieval_mode": client.retrieval_mode,
                "cache_hit": cache_hit,
                "inserted_from": "tavily",
                "provider_name": "tavily",
            },
        }
        metadata[ORACLE_RAW_PAYLOAD_FIELD] = json.dumps(
            payload,
            sort_keys=True,
            default=str
        )

    if client.enable_provenance_metadata:
        metadata.update({
            ORACLE_SOURCE_URL_FIELD: result.get("url"),
            ORACLE_SOURCE_TITLE_FIELD: result.get("title"),
            ORACLE_RETRIEVAL_QUERY_FIELD: query,
            ORACLE_RETRIEVAL_TIMESTAMP_FIELD: timestamp,
            ORACLE_RETRIEVAL_MODE_FIELD: client.retrieval_mode,
            ORACLE_CACHE_HIT_FIELD: 1 if cache_hit else 0,
            ORACLE_INSERTED_FROM_FIELD: "tavily",
            ORACLE_PROVIDER_NAME_FIELD: "tavily",
        })

    return metadata


def filter_duplicate_documents(client, documents):
    if client.dedup_similarity_threshold is None:
        return documents

    unique_documents = []
    for document in documents:
        embedding = get_document_value(document, client.embeddings_field)
        if embedding is None or not is_duplicate(client, embedding):
            unique_documents.append(document)
    return unique_documents


def get_document_value(document, column_name):
    for key, value in document.items():
        if validate_identifier(key, "document key") == column_name:
            return value
    return None


def is_duplicate(client, embedding):
    sql = f"""
            SELECT 1 - VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE) AS score
            FROM {client.table_name}
            WHERE {client.embeddings_field} IS NOT NULL
            ORDER BY VECTOR_DISTANCE({client.embeddings_field}, :query_vector, COSINE)
            FETCH FIRST 1 ROWS ONLY
        """

    with client.connection.cursor() as cursor:
        cursor.execute(sql, query_vector=to_vector(embedding))
        row = cursor.fetchone()

    if row is None:
        return False

    return row[0] >= client.dedup_similarity_threshold


def ensure_vector_index(client, index_name=None):
    if client.db_provider != "oracle":
        raise ValueError("ensure_oracle_vector_index is only supported when db_provider='oracle'.")

    index_name = index_name or client.vector_index_name
    if index_name is None:
        index_name = f"{client.table_name}_{client.embeddings_field}_VEC_IDX"
    index_name = validate_identifier(index_name, "index_name")

    with client.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM USER_INDEXES WHERE INDEX_NAME = :index_name",
            index_name=index_name
        )
        if cursor.fetchone()[0] > 0:
            return False

        cursor.execute(
            """
                BEGIN
                    DBMS_VECTOR.CREATE_INDEX(
                        idx_name => :index_name,
                        table_name => :table_name,
                        idx_vector_col => :idx_vector_col,
                        idx_include_cols => NULL,
                        idx_partitioning_scheme => :idx_partitioning_scheme,
                        idx_organization => :idx_organization,
                        idx_distance_metric => :idx_distance_metric,
                        idx_accuracy => :idx_accuracy,
                        idx_parameters => :idx_parameters,
                        idx_parallel_creation => 1
                    );
                END;
                """,
            index_name=index_name,
            table_name=client.table_name,
            idx_vector_col=client.embeddings_field,
            idx_partitioning_scheme="GLOBAL" if client.vector_index_type == "IVF" else None,
            idx_organization=ORACLE_VECTOR_INDEX_ORGANIZATIONS[client.vector_index_type],
            idx_distance_metric=client.vector_index_distance,
            idx_accuracy=int(client.vector_index_accuracy),
            idx_parameters=vector_index_parameters(client),
        )

    client.connection.commit()
    return True


def vector_index_parameters(client):
    if client.vector_index_type == "HNSW":
        return json.dumps({
            "type": "HNSW",
            "neighbors": int(client.vector_index_neighbors),
            "efConstruction": int(client.vector_index_efconstruction),
        })

    return json.dumps({
        "type": "IVF",
        "partitions": int(client.vector_index_partitions),
    })


def validate_vector_index_type(value):
    value = value.upper()
    if value not in ORACLE_VECTOR_INDEX_TYPES:
        raise ValueError("vector_index_type must be 'HNSW' or 'IVF'.")
    return value


def validate_vector_distance(value):
    value = value.upper()
    if value not in ORACLE_VECTOR_DISTANCE_METRICS:
        raise ValueError(
            "vector_index_distance must be one of "
            f"{', '.join(ORACLE_VECTOR_DISTANCE_METRICS)}."
        )
    return value


def insert_documents(client, documents):
    if not documents:
        return

    normalized_documents = []
    column_names = set()

    for document in documents:
        normalized_document = {
            validate_identifier(key, "document key"): value
            for key, value in document.items()
        }

        if client.content_field not in normalized_document or client.embeddings_field not in normalized_document:
            raise ValueError(
                "Oracle save_foreign documents must include both "
                f"'{client.content_field}' and '{client.embeddings_field}'."
            )

        for column_name, value in normalized_document.items():
            if column_name == client.embeddings_field:
                value = to_vector(value)
            normalized_document[column_name] = value
            column_names.add(column_name)

        normalized_documents.append(normalized_document)

    ordered_columns = sorted(column_names)
    columns = ", ".join(ordered_columns)
    placeholders = ", ".join(f":{column}" for column in ordered_columns)
    sql = f"INSERT INTO {client.table_name} ({columns}) VALUES ({placeholders})"
    rows = [
        {column: document.get(column) for column in ordered_columns}
        for document in normalized_documents
    ]

    with client.connection.cursor() as cursor:
        cursor.executemany(sql, rows)
    client.connection.commit()
