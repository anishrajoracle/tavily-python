import array
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from tavily.databases.oracledb.oracle_config import (
    ORACLE_CACHE_HIT_FIELD,
    ORACLE_CONTENT_HASH_FIELD,
    ORACLE_EXPIRES_AT_FIELD,
    ORACLE_IDENTIFIER,
    ORACLE_INSERTED_FROM_FIELD,
    ORACLE_LAST_SEEN_AT_FIELD,
    ORACLE_MEMORY_SCOPE_FIELD,
    ORACLE_PROVIDER_NAME_FIELD,
    ORACLE_QUERY_COUNT_FIELD,
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


ORACLE_TEXT_TOKEN = re.compile(r"[A-Za-z0-9]+")
ORACLE_MEMORY_METADATA_FIELDS = (
    ORACLE_MEMORY_SCOPE_FIELD,
    ORACLE_EXPIRES_AT_FIELD,
    ORACLE_LAST_SEEN_AT_FIELD,
    ORACLE_QUERY_COUNT_FIELD,
)
ORACLE_CACHE_RETRIEVAL_MODES = ("freshness_cache", "cache_then_memory")


def utc_now():
    return datetime.now(timezone.utc)


def utc_naive_now():
    return utc_now().replace(tzinfo=None)


def cache_cutoff_timestamp(cache_ttl_seconds):
    return utc_naive_now() - timedelta(seconds=cache_ttl_seconds)


def validate_client(_client):
    return None


def search_provider(client, query_embeddings, max_local, query=None,
                    cache_ttl_seconds=None, memory_scopes=None):
    return search(
        client,
        query_embeddings,
        max_local,
        query=query,
        cache_ttl_seconds=cache_ttl_seconds,
        memory_scopes=memory_scopes
    )


def insert_provider(client, documents):
    documents = filter_duplicate_documents(client, documents)
    if not documents:
        return
    insert_documents(client, documents)


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


def fetch_table_columns(client):
    cached_columns = getattr(client, "_oracle_table_columns_cache", None)
    if cached_columns is not None:
        return cached_columns

    sql = """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM USER_TAB_COLUMNS
        WHERE TABLE_NAME = :table_name
    """
    with client.connection.cursor() as cursor:
        cursor.execute(sql, table_name=client.table_name)
        columns = {
            validate_identifier(row[0], "column name"): str(row[1]).upper()
            for row in cursor.fetchall()
        }

    client._oracle_table_columns_cache = columns
    return columns


def validate_insert_schema(client, normalized_documents):
    if not normalized_documents:
        return

    table_columns = fetch_table_columns(client)
    if not table_columns:
        raise ValueError(
            f"Oracle table {client.table_name} was not found or has no visible columns."
        )

    insert_columns = set()
    for document in normalized_documents:
        insert_columns.update(document.keys())

    missing_columns = sorted(insert_columns - set(table_columns.keys()))
    if missing_columns:
        raise ValueError(
            f"Oracle table {client.table_name} is missing columns required for "
            f"save_foreign inserts: {', '.join(missing_columns)}."
        )

    _validate_column_type(
        client.table_name,
        client.content_field,
        table_columns[client.content_field],
        _is_text_type,
        "text-compatible"
    )
    _validate_column_type(
        client.table_name,
        client.embeddings_field,
        table_columns[client.embeddings_field],
        _is_vector_type,
        "VECTOR-compatible"
    )

    if ORACLE_RAW_PAYLOAD_FIELD in insert_columns:
        _validate_column_type(
            client.table_name,
            ORACLE_RAW_PAYLOAD_FIELD,
            table_columns[ORACLE_RAW_PAYLOAD_FIELD],
            _is_json_storage_type,
            "JSON-compatible"
        )

    for text_column in (
        ORACLE_SOURCE_URL_FIELD,
        ORACLE_SOURCE_TITLE_FIELD,
        ORACLE_RETRIEVAL_QUERY_FIELD,
        ORACLE_RETRIEVAL_MODE_FIELD,
        ORACLE_INSERTED_FROM_FIELD,
        ORACLE_PROVIDER_NAME_FIELD,
        ORACLE_CONTENT_HASH_FIELD,
    ):
        if text_column in insert_columns:
            _validate_column_type(
                client.table_name,
                text_column,
                table_columns[text_column],
                _is_text_type,
                "text-compatible"
            )

    if ORACLE_RETRIEVAL_TIMESTAMP_FIELD in insert_columns:
        _validate_column_type(
            client.table_name,
            ORACLE_RETRIEVAL_TIMESTAMP_FIELD,
            table_columns[ORACLE_RETRIEVAL_TIMESTAMP_FIELD],
            _is_timestamp_type,
            "timestamp-compatible"
        )

    for timestamp_column in (ORACLE_EXPIRES_AT_FIELD, ORACLE_LAST_SEEN_AT_FIELD):
        if timestamp_column in insert_columns:
            _validate_column_type(
                client.table_name,
                timestamp_column,
                table_columns[timestamp_column],
                _is_timestamp_type,
                "timestamp-compatible"
            )

    if ORACLE_MEMORY_SCOPE_FIELD in insert_columns:
        _validate_column_type(
            client.table_name,
            ORACLE_MEMORY_SCOPE_FIELD,
            table_columns[ORACLE_MEMORY_SCOPE_FIELD],
            _is_text_type,
            "text-compatible"
        )

    if ORACLE_QUERY_COUNT_FIELD in insert_columns:
        _validate_column_type(
            client.table_name,
            ORACLE_QUERY_COUNT_FIELD,
            table_columns[ORACLE_QUERY_COUNT_FIELD],
            _is_number_type,
            "number-compatible"
        )


def _validate_column_type(table_name, column_name, data_type, predicate, expected):
    if not predicate(data_type):
        raise ValueError(
            f"Oracle column {table_name}.{column_name} must be {expected}; "
            f"found {data_type}."
        )


def _is_vector_type(data_type):
    return data_type.startswith("VECTOR")


def _is_text_type(data_type):
    return (
        data_type in {"CLOB", "NCLOB", "LONG"}
        or data_type.startswith("VARCHAR")
        or data_type.startswith("NVARCHAR")
        or data_type.startswith("CHAR")
        or data_type.startswith("NCHAR")
    )


def _is_json_storage_type(data_type):
    return _is_text_type(data_type) or data_type == "JSON"


def _is_timestamp_type(data_type):
    return data_type == "DATE" or data_type.startswith("TIMESTAMP")


def _is_number_type(data_type):
    return (
        data_type == "NUMBER"
        or data_type.startswith("INTEGER")
        or data_type.startswith("BINARY_FLOAT")
        or data_type.startswith("BINARY_DOUBLE")
        or data_type.startswith("FLOAT")
    )


def _is_lob_or_long_type(data_type):
    return data_type in {"BLOB", "CLOB", "NCLOB", "LONG"}


def search(client, query_embeddings, max_local, query=None, cache_ttl_seconds=None,
           memory_scopes=None):
    limit = int(max_local)
    if limit < 1:
        return []

    if client.enable_native_hybrid_search and query:
        try:
            return search_native_hybrid(
                client,
                query_embeddings,
                limit,
                query,
                cache_ttl_seconds=cache_ttl_seconds,
                memory_scopes=memory_scopes
            )
        except Exception as exc:
            if not is_oracle_text_query_error(exc):
                raise

    return search_vector(
        client,
        query_embeddings,
        limit,
        cache_ttl_seconds=cache_ttl_seconds,
        memory_scopes=memory_scopes
    )


def search_vector(client, query_embeddings, max_local, cache_ttl_seconds=None,
                  memory_scopes=None):
    limit = int(max_local)
    if limit < 1:
        return []

    vector_distance = vector_distance_expression(client)
    execute_kwargs = {"query_vector": to_vector(query_embeddings)}
    freshness_filter = build_freshness_filter(
        client,
        cache_ttl_seconds,
        execute_kwargs
    )
    metadata_filter = build_metadata_filter(client.oracle_metadata_filters, execute_kwargs)
    memory_scope_filter = build_memory_scope_filter(client, memory_scopes, execute_kwargs)

    sql = f"""
            SELECT {client.content_field},
                   1 - {vector_distance} AS score,
                   'local' AS origin
            FROM {client.table_name}
            WHERE {client.embeddings_field} IS NOT NULL
              {freshness_filter}
              {metadata_filter}
              {memory_scope_filter}
            ORDER BY {vector_distance}
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


def sanitize_oracle_text_query(query):
    return " ".join(ORACLE_TEXT_TOKEN.findall(str(query)))


def is_oracle_text_query_error(exc):
    message = str(exc)
    return (
        "DRG-" in message
        or "Oracle Text error" in message
        or "ODCIINDEXSTART" in message
    )


def vector_distance_expression(client):
    distance_metric = validate_vector_distance(
        getattr(client, "vector_index_distance", "COSINE")
    )
    return (
        f"VECTOR_DISTANCE({client.embeddings_field}, "
        f":query_vector, {distance_metric})"
    )


def search_native_hybrid(client, query_embeddings, max_local, query,
                         cache_ttl_seconds=None, memory_scopes=None):
    limit = int(max_local)
    if limit < 1:
        return []

    text_query = sanitize_oracle_text_query(query)
    if not text_query:
        return search_vector(
            client,
            query_embeddings,
            limit,
            cache_ttl_seconds=cache_ttl_seconds,
            memory_scopes=memory_scopes
        )

    vector_distance = vector_distance_expression(client)
    execute_kwargs = {
        "query_vector": to_vector(query_embeddings),
        "text_query": text_query,
    }
    freshness_filter = build_freshness_filter(
        client,
        cache_ttl_seconds,
        execute_kwargs
    )
    metadata_filter = build_metadata_filter(client.oracle_metadata_filters, execute_kwargs)
    memory_scope_filter = build_memory_scope_filter(client, memory_scopes, execute_kwargs)

    sql = f"""
            WITH vector_candidates AS (
                SELECT ROWID AS rid,
                       1 - {vector_distance} AS vector_score,
                       0 AS text_score
                FROM {client.table_name}
                WHERE {client.embeddings_field} IS NOT NULL
                  {freshness_filter}
                  {metadata_filter}
                  {memory_scope_filter}
                ORDER BY {vector_distance}
                FETCH FIRST {limit} ROWS ONLY
            ),
            text_candidates AS (
                SELECT ROWID AS rid,
                       1 - {vector_distance} AS vector_score,
                       SCORE(1) / 100 AS text_score
                FROM {client.table_name}
                WHERE {client.embeddings_field} IS NOT NULL
                  AND CONTAINS({client.content_field}, :text_query, 1) > 0
                  {freshness_filter}
                  {metadata_filter}
                  {memory_scope_filter}
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


def build_freshness_filter(client, cache_ttl_seconds, execute_kwargs):
    if cache_ttl_seconds is None:
        return ""

    table_columns = fetch_table_columns(client)
    has_expires_at = ORACLE_EXPIRES_AT_FIELD in table_columns
    has_cache_timestamp = client.cache_timestamp_field in table_columns

    if has_expires_at:
        execute_kwargs["freshness_current_timestamp"] = utc_now()
        if has_cache_timestamp:
            execute_kwargs["cache_cutoff_timestamp"] = cache_cutoff_timestamp(cache_ttl_seconds)
            return (
                f"AND ("
                f"{ORACLE_EXPIRES_AT_FIELD} > :freshness_current_timestamp "
                f"OR ("
                f"{ORACLE_EXPIRES_AT_FIELD} IS NULL "
                f"AND {client.cache_timestamp_field} >= :cache_cutoff_timestamp"
                f")"
                f")"
            )
        return f"AND {ORACLE_EXPIRES_AT_FIELD} > :freshness_current_timestamp"

    if not has_cache_timestamp:
        raise ValueError(
            f"Oracle table {client.table_name} is missing {client.cache_timestamp_field}. "
            "Add the cache timestamp column before using freshness cache TTL."
        )

    execute_kwargs["cache_cutoff_timestamp"] = cache_cutoff_timestamp(cache_ttl_seconds)
    return f"AND {client.cache_timestamp_field} >= :cache_cutoff_timestamp"


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


def build_memory_scope_filter(client, memory_scopes, execute_kwargs):
    if not memory_scopes:
        return ""

    scopes = list(memory_scopes)
    if not scopes:
        return ""

    table_columns = fetch_table_columns(client)
    if ORACLE_MEMORY_SCOPE_FIELD not in table_columns:
        raise ValueError(
            f"Oracle table {client.table_name} is missing {ORACLE_MEMORY_SCOPE_FIELD}. "
            "Add the Oracle memory metadata columns before using cache_then_memory."
        )

    bind_names = []
    for i, scope in enumerate(scopes):
        bind_name = f"memory_scope_{i}"
        bind_names.append(f":{bind_name}")
        execute_kwargs[bind_name] = scope

    return f"AND {ORACLE_MEMORY_SCOPE_FIELD} IN ({', '.join(bind_names)})"


def has_memory_metadata_columns(client):
    table_columns = fetch_table_columns(client)
    return all(column in table_columns for column in ORACLE_MEMORY_METADATA_FIELDS)


def should_write_memory_metadata(client):
    if client.enable_oracle_memory_metadata:
        return True
    return (
        client.retrieval_mode in ORACLE_CACHE_RETRIEVAL_MODES
        and has_memory_metadata_columns(client)
    )


def build_persistence_metadata(client, result, query, cache_hit):
    write_memory_metadata = should_write_memory_metadata(client)
    needs_cache_timestamp = (
        client.retrieval_mode in ORACLE_CACHE_RETRIEVAL_MODES
        or write_memory_metadata
    )
    if not (
        client.enable_oracle_json_payload
        or client.enable_provenance_metadata
        or write_memory_metadata
        or client.oracle_upsert_key is not None
        or needs_cache_timestamp
    ):
        return {}

    timestamp = utc_now()
    metadata = {}

    if needs_cache_timestamp:
        metadata[client.cache_timestamp_field] = timestamp.replace(tzinfo=None)

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

    if write_memory_metadata:
        metadata.update({
            ORACLE_MEMORY_SCOPE_FIELD: client.persistence_depth,
            ORACLE_EXPIRES_AT_FIELD: timestamp + timedelta(seconds=client.cache_ttl_seconds),
            ORACLE_LAST_SEEN_AT_FIELD: timestamp,
            ORACLE_QUERY_COUNT_FIELD: 1,
        })

    if client.oracle_upsert_key == "source_url" and result.get("url"):
        metadata[ORACLE_SOURCE_URL_FIELD] = result["url"]
    elif client.oracle_upsert_key == "content_hash":
        content = result.get("content")
        if content:
            metadata[ORACLE_CONTENT_HASH_FIELD] = build_content_hash(content)

    return metadata


def build_content_hash(content):
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()


def filter_duplicate_documents(client, documents):
    if client.dedup_similarity_threshold is None:
        return documents

    upsert_key = None
    if client.oracle_upsert_key is not None:
        upsert_key = upsert_key_column(client.oracle_upsert_key)

    unique_documents = []
    for document in documents:
        if upsert_key and get_document_value(document, upsert_key):
            unique_documents.append(document)
            continue

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
    vector_distance = vector_distance_expression(client)
    execute_kwargs = {"query_vector": to_vector(embedding)}
    metadata_filter = build_metadata_filter(client.oracle_metadata_filters, execute_kwargs)
    dedup_filter = build_dedup_scope_filter(client, execute_kwargs)
    sql = f"""
            SELECT 1 - {vector_distance} AS score
            FROM {client.table_name}
            WHERE {client.embeddings_field} IS NOT NULL
              {metadata_filter}
              {dedup_filter}
            ORDER BY {vector_distance}
            FETCH FIRST 1 ROWS ONLY
        """

    with client.connection.cursor() as cursor:
        cursor.execute(sql, **execute_kwargs)
        row = cursor.fetchone()

    if row is None:
        return False

    return row[0] >= client.dedup_similarity_threshold


def build_dedup_scope_filter(client, execute_kwargs):
    table_columns = fetch_table_columns(client)
    clauses = []

    if ORACLE_PROVIDER_NAME_FIELD in table_columns:
        clauses.append(f"{ORACLE_PROVIDER_NAME_FIELD} = :dedup_provider_name")
        execute_kwargs["dedup_provider_name"] = "tavily"
    if ORACLE_INSERTED_FROM_FIELD in table_columns:
        clauses.append(f"{ORACLE_INSERTED_FROM_FIELD} = :dedup_inserted_from")
        execute_kwargs["dedup_inserted_from"] = "tavily"

    if (
        ORACLE_MEMORY_SCOPE_FIELD in table_columns
        and ORACLE_EXPIRES_AT_FIELD in table_columns
    ):
        clauses.append(
            f"("
            f"{ORACLE_MEMORY_SCOPE_FIELD} IS NULL "
            f"OR {ORACLE_MEMORY_SCOPE_FIELD} <> :dedup_cache_only_scope "
            f"OR {ORACLE_EXPIRES_AT_FIELD} IS NULL "
            f"OR {ORACLE_EXPIRES_AT_FIELD} > :dedup_current_timestamp"
            f")"
        )
        execute_kwargs["dedup_cache_only_scope"] = "cache_only"
        execute_kwargs["dedup_current_timestamp"] = utc_now()

    if not clauses:
        return ""

    return "AND " + " AND ".join(clauses)


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

    normalized_documents, column_names = normalize_documents(client, documents)
    validate_insert_schema(client, normalized_documents)

    if client.oracle_upsert_key is not None:
        upsert_documents(client, normalized_documents, column_names)
        return

    insert_normalized_documents(client, normalized_documents, column_names)


def normalize_documents(client, documents):
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

    return normalized_documents, column_names


def insert_normalized_documents(client, normalized_documents, column_names, commit=True):
    ordered_columns = order_columns_for_oracle_binds(client, column_names)
    columns = ", ".join(ordered_columns)
    placeholders = ", ".join(f":{column}" for column in ordered_columns)
    sql = f"INSERT INTO {client.table_name} ({columns}) VALUES ({placeholders})"
    rows = [
        {column: document.get(column) for column in ordered_columns}
        for document in normalized_documents
    ]

    try:
        with client.connection.cursor() as cursor:
            cursor.executemany(sql, rows)
        if commit:
            client.connection.commit()
    except Exception:
        if hasattr(client.connection, "rollback"):
            client.connection.rollback()
        raise


def upsert_documents(client, normalized_documents, column_names):
    key_column = upsert_key_column(client.oracle_upsert_key)
    upsertable_documents = [
        document for document in normalized_documents
        if document.get(key_column)
    ]
    insert_only_documents = [
        document for document in normalized_documents
        if not document.get(key_column)
    ]

    if not upsertable_documents:
        if insert_only_documents:
            insert_normalized_documents(client, insert_only_documents, column_names)
        return

    try:
        if insert_only_documents:
            insert_normalized_documents(
                client,
                insert_only_documents,
                column_names,
                commit=False
            )

        with client.connection.cursor() as cursor:
            for document in upsertable_documents:
                ordered_columns = order_columns_for_oracle_binds(
                    client,
                    document.keys()
                )
                update_columns = [
                    column for column in ordered_columns
                    if column != key_column
                ]
                update_assignments = [
                    build_upsert_update_assignment(column)
                    for column in update_columns
                ]
                insert_columns = ", ".join(ordered_columns)
                insert_values = ", ".join(f":{column}" for column in ordered_columns)

                sql = f"""
                    MERGE INTO {client.table_name} target
                    USING (SELECT :{key_column} AS {key_column} FROM DUAL) source
                    ON (target.{key_column} = source.{key_column})
                    WHEN MATCHED THEN UPDATE SET {', '.join(update_assignments)}
                    WHEN NOT MATCHED THEN INSERT ({insert_columns})
                    VALUES ({insert_values})
                """
                row = {
                    column: document.get(column)
                    for column in ordered_columns
                }
                cursor.execute(sql, **row)
    except Exception:
        if hasattr(client.connection, "rollback"):
            client.connection.rollback()
        raise

    client.connection.commit()


def order_columns_for_oracle_binds(client, column_names):
    """Place LOB/LONG-style columns after regular binds to avoid ORA-24816."""
    table_columns = fetch_table_columns(client)
    return sorted(
        column_names,
        key=lambda column: (
            _is_lob_or_long_type(table_columns.get(column, "")),
            column
        )
    )


def upsert_key_column(oracle_upsert_key):
    if oracle_upsert_key == "source_url":
        return ORACLE_SOURCE_URL_FIELD
    if oracle_upsert_key == "content_hash":
        return ORACLE_CONTENT_HASH_FIELD
    raise ValueError("oracle_upsert_key must be 'source_url' or 'content_hash'.")


def build_upsert_update_assignment(column):
    if column == ORACLE_QUERY_COUNT_FIELD:
        return f"target.{column} = NVL(target.{column}, 0) + 1"
    return f"target.{column} = :{column}"


def build_unscoped_cache_cleanup_filter(table_columns, execute_kwargs):
    if ORACLE_RETRIEVAL_MODE_FIELD in table_columns:
        bind_names = []
        for i, mode in enumerate(ORACLE_CACHE_RETRIEVAL_MODES):
            bind_name = f"cleanup_retrieval_mode_{i}"
            bind_names.append(f":{bind_name}")
            execute_kwargs[bind_name] = mode
        clauses = [f"{ORACLE_RETRIEVAL_MODE_FIELD} IN ({', '.join(bind_names)})"]
    else:
        return ""

    if ORACLE_PROVIDER_NAME_FIELD in table_columns:
        clauses.append(f"{ORACLE_PROVIDER_NAME_FIELD} = :cleanup_provider_name")
        execute_kwargs["cleanup_provider_name"] = "tavily"
    if ORACLE_INSERTED_FROM_FIELD in table_columns:
        clauses.append(f"{ORACLE_INSERTED_FROM_FIELD} = :cleanup_inserted_from")
        execute_kwargs["cleanup_inserted_from"] = "tavily"

    if not clauses:
        return ""

    return " AND ".join(f"({clause})" for clause in clauses)


def delete_expired_cache_rows(client, cache_ttl_seconds=None):
    if client.db_provider != "oracle":
        raise ValueError("cleanup_cache is only supported when db_provider='oracle'.")

    table_columns = fetch_table_columns(client)
    ttl_seconds = client.cache_ttl_seconds if cache_ttl_seconds is None else cache_ttl_seconds
    if ttl_seconds <= 0:
        raise ValueError("cache_ttl_seconds must be greater than 0.")

    execute_kwargs = {
        "cache_cutoff_timestamp": cache_cutoff_timestamp(ttl_seconds)
    }
    has_lifecycle_columns = (
        ORACLE_EXPIRES_AT_FIELD in table_columns
        and ORACLE_MEMORY_SCOPE_FIELD in table_columns
    )
    has_cache_timestamp = client.cache_timestamp_field in table_columns

    if has_lifecycle_columns:
        legacy_timestamp_condition = (
            f"{client.cache_timestamp_field} < :cache_cutoff_timestamp"
            if has_cache_timestamp
            else "1 = 0"
        )
        unscoped_filter = build_unscoped_cache_cleanup_filter(
            table_columns,
            execute_kwargs
        )
        unscoped_clause = ""
        if unscoped_filter:
            unscoped_clause = f"""
            OR (
                {ORACLE_MEMORY_SCOPE_FIELD} IS NULL
                AND (
                    {ORACLE_EXPIRES_AT_FIELD} < :current_timestamp
                    OR (
                        {ORACLE_EXPIRES_AT_FIELD} IS NULL
                        AND {legacy_timestamp_condition}
                    )
                )
                AND ({unscoped_filter})
            )
            """

        sql = f"""
            DELETE FROM {client.table_name}
            WHERE (
                {ORACLE_MEMORY_SCOPE_FIELD} = :memory_scope
                AND (
                    {ORACLE_EXPIRES_AT_FIELD} < :current_timestamp
                    OR (
                        {ORACLE_EXPIRES_AT_FIELD} IS NULL
                        AND {legacy_timestamp_condition}
                    )
                )
            )
            {unscoped_clause}
        """
        execute_kwargs["memory_scope"] = "cache_only"
        execute_kwargs["current_timestamp"] = utc_now()
    elif ORACLE_MEMORY_SCOPE_FIELD in table_columns and has_cache_timestamp:
        sql = f"""
            DELETE FROM {client.table_name}
            WHERE {ORACLE_MEMORY_SCOPE_FIELD} = :memory_scope
              AND {client.cache_timestamp_field} < :cache_cutoff_timestamp
        """
        execute_kwargs["memory_scope"] = "cache_only"
    elif has_cache_timestamp:
        unscoped_filter = build_unscoped_cache_cleanup_filter(
            table_columns,
            execute_kwargs
        )
        if not unscoped_filter:
            return 0

        sql = f"""
            DELETE FROM {client.table_name}
            WHERE {client.cache_timestamp_field} < :cache_cutoff_timestamp
              AND ({unscoped_filter})
        """
    else:
        return 0

    with client.connection.cursor() as cursor:
        cursor.execute(sql, **execute_kwargs)
        deleted_rows = cursor.rowcount

    client.connection.commit()
    return deleted_rows
