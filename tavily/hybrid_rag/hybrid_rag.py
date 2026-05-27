import array
from datetime import datetime, timezone
import json
import re
from typing import Callable, Literal, Optional, Sequence, Union

import requests
from tavily import TavilyClient

try:
    import cohere
except ImportError:
    cohere = None

co = None

_ORACLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ORACLE_CACHE_TIMESTAMP_FIELD = "ADDED_AT"
_RETRIEVAL_MODES = ("hybrid_search", "freshness_cache")
_ORACLE_VECTOR_INDEX_TYPES = ("HNSW", "IVF")
_ORACLE_VECTOR_DISTANCE_METRICS = (
    "EUCLIDEAN",
    "EUCLIDEAN_SQUARED",
    "L2_SQUARED",
    "COSINE",
    "DOT",
    "MANHATTAN",
    "HAMMING",
    "JACCARD",
)
_ORACLE_VECTOR_INDEX_ORGANIZATIONS = {
    "HNSW": "INMEMORY NEIGHBOR GRAPH",
    "IVF": "NEIGHBOR PARTITIONS",
}

_ORACLE_RAW_PAYLOAD_FIELD = "RAW_PAYLOAD"
_ORACLE_SOURCE_URL_FIELD = "SOURCE_URL"
_ORACLE_SOURCE_TITLE_FIELD = "SOURCE_TITLE"
_ORACLE_RETRIEVAL_QUERY_FIELD = "RETRIEVAL_QUERY"
_ORACLE_RETRIEVAL_TIMESTAMP_FIELD = "RETRIEVAL_TIMESTAMP"
_ORACLE_RETRIEVAL_MODE_FIELD = "RETRIEVAL_MODE"
_ORACLE_CACHE_HIT_FIELD = "CACHE_HIT"
_ORACLE_INSERTED_FROM_FIELD = "INSERTED_FROM"
_ORACLE_PROVIDER_NAME_FIELD = "PROVIDER_NAME"


def _validate_oracle_identifier(value, name):
    if not value or not _ORACLE_IDENTIFIER.match(value):
        raise ValueError(f"Invalid Oracle identifier for {name}: {value}")
    return value.upper()


def _to_oracle_vector(values):
    return array.array("f", values)


def _read_lob(value):
    if hasattr(value, "read"):
        return value.read()
    return value


def _get_cohere_client():
    global co

    if co is not None:
        return co

    if cohere is None:
        raise ImportError(
            "The default hybrid RAG embedding and ranking functions require "
            "the 'cohere' package. Install cohere or provide custom "
            "embedding_function and ranking_function callables."
        )

    try:
        co = cohere.Client()
    except Exception as exc:
        raise RuntimeError(
            "Failed to initialize the Cohere client. Set the required Cohere "
            "environment variables or provide custom embedding_function and "
            "ranking_function callables."
        ) from exc

    return co


def _validate_index(client):
    """
    Check that the index specified by the parameters exists and is a valid vector search index.

    Raises:
        ValueError: If the index does not exist, is not of type 'vectorSearch', or if the embeddings field
                    does not exist, is not of type 'vector', or has similarity other than 'cosine'.
    """
    if not hasattr(client.collection, "list_search_indexes"):
        raise ValueError("MongoDB collection must provide list_search_indexes().")

    index_exists = False
    for index in client.collection.list_search_indexes():
        if index.get('name') != client.index:
            continue

        if index.get('type') != 'vectorSearch':
            raise ValueError(f"Index '{client.index}' exists but is not of type "
                             "'vectorSearch'.")

        field_exists = False
        fields = index.get('latestDefinition', {}).get('fields', [])
        for field in fields:
            if field.get('path') != client.embeddings_field:
                continue

            if field.get('type') != 'vector':
                raise ValueError(f"Field '{client.embeddings_field}' exists "
                                 "but is not of type 'vector'.")
            elif field.get('similarity') != 'cosine':
                raise ValueError(f"Field '{client.embeddings_field}' exists but has "
                                 f"similarity '{field.get('similarity')}' instead of 'cosine'.")

            field_exists = True
            break

        if not field_exists:
            raise ValueError(f"Field '{client.embeddings_field}' does not exist in "
                             f"index '{client.index}'.")

        index_exists = True

    if not index_exists:
        raise ValueError(f"Index '{client.index}' does not exist.")


def _cohere_embed(texts, input_type):
    client = _get_cohere_client()
    return client.embed(
        model='embed-english-v3.0',
        texts=texts,
        input_type=input_type
    ).embeddings


def _cohere_rerank(query, documents, top_n):
    client = _get_cohere_client()
    response = client.rerank(model='rerank-english-v3.0', query=query,
                             documents=[doc['content'] for doc in documents], top_n=top_n)

    return [
        documents[result.index] | {'score': result.relevance_score}
        for result in response.results
    ]


class TavilyHybridClient():
    def __init__(
            self,
            api_key: Union[str, None],
            db_provider: Literal['mongodb', 'oracle'],
            collection=None,
            index: Optional[str] = None,
            embeddings_field: str = 'embeddings',
            content_field: str = 'content',
            connection=None,
            table_name: Optional[str] = None,
            embedding_function: Optional[Callable[[Sequence[str], str], Sequence[Sequence[float]]]] = None,
            ranking_function: Optional[Callable[[str, list, int], list]] = None,
            session: Optional[requests.Session] = None,
            retrieval_mode: Literal['hybrid_search', 'freshness_cache'] = 'hybrid_search',
            cache_ttl_seconds: int = 86400,
            cache_score_threshold: float = 0.0,
            cache_timestamp_field: str = _ORACLE_CACHE_TIMESTAMP_FIELD,
            enable_native_hybrid_search: bool = False,
            oracle_metadata_filters: Optional[dict] = None,
            enable_oracle_json_payload: bool = False,
            enable_provenance_metadata: bool = False,
            vector_index_name: Optional[str] = None,
            vector_index_type: Literal['HNSW', 'IVF'] = 'HNSW',
            vector_index_distance: str = 'COSINE',
            vector_index_accuracy: int = 90,
            vector_index_neighbors: int = 40,
            vector_index_efconstruction: int = 500,
            vector_index_partitions: int = 10,
            dedup_similarity_threshold: Optional[float] = None
        ):
        '''
        A client for performing hybrid RAG using both the Tavily API and a local database.

        Parameters:
        api_key (str): The Tavily API key. If this is set to None, it will be loaded from the environment variable TAVILY_API_KEY.
        db_provider (str): The database provider. Supported values are 'mongodb' and 'oracle'.
        collection: The MongoDB collection object that will be used for local search. Required when db_provider='mongodb'.
        index (str): The MongoDB collection's vector search index. Required when db_provider='mongodb'.
        embeddings_field (str): The name of the field in the database that contains the embeddings.
        content_field (str): The name of the field in the database that contains the content.
        connection: A python-oracledb connection. Required when db_provider='oracle'.
        table_name (str): The Oracle table that stores content and vector embeddings. Required when db_provider='oracle'.
        embedding_function (callable): If provided, this function will be used to generate embeddings for the search query and documents.
        ranking_function (callable): If provided, this function will be used to rerank the combined results.
        session (requests.Session): If provided, this pre-configured session will be used for HTTP requests. When set, api_key is optional.
        retrieval_mode (str): Retrieval mode. 'hybrid_search' is supported for MongoDB and Oracle. 'freshness_cache' is Oracle-only.
        cache_ttl_seconds (int): Freshness window used by Oracle freshness_cache mode.
        cache_score_threshold (float): Minimum local score needed for an Oracle freshness_cache hit.
        cache_timestamp_field (str): Oracle timestamp column used by freshness_cache mode.
        enable_native_hybrid_search (bool): If True, Oracle local search uses Oracle Text scoring along with vector similarity.
        oracle_metadata_filters (dict): Optional Oracle column filters applied during local Oracle search.
        enable_oracle_json_payload (bool): If True, Oracle save_foreign=True writes RAW_PAYLOAD JSON.
        enable_provenance_metadata (bool): If True, Oracle save_foreign=True writes provenance columns.
        vector_index_name (str): Optional Oracle vector index name used by ensure_oracle_vector_index().
        vector_index_type (str): Oracle vector index type, 'HNSW' or 'IVF'.
        vector_index_distance (str): Oracle vector index distance metric.
        vector_index_accuracy (int): Oracle vector index target accuracy.
        vector_index_neighbors (int): HNSW neighbors parameter.
        vector_index_efconstruction (int): HNSW efConstruction parameter.
        vector_index_partitions (int): IVF partitions parameter.
        dedup_similarity_threshold (float): If set for Oracle, skip insert when nearest local similarity is at or above this threshold.
        '''

        self.tavily = TavilyClient(api_key, session=session)

        if db_provider not in ('mongodb', 'oracle'):
            raise ValueError("Supported database providers are 'mongodb' and 'oracle'.")
        if retrieval_mode not in _RETRIEVAL_MODES:
            raise ValueError(
                "Supported retrieval modes are 'hybrid_search' and 'freshness_cache'."
            )
        if db_provider != 'oracle' and retrieval_mode == 'freshness_cache':
            raise ValueError(
                "retrieval_mode='freshness_cache' is only supported when "
                "db_provider='oracle'."
            )
        if retrieval_mode == 'freshness_cache':
            if cache_ttl_seconds <= 0:
                raise ValueError("cache_ttl_seconds must be greater than 0.")
            try:
                cache_score_threshold = float(cache_score_threshold)
            except (TypeError, ValueError) as exc:
                raise ValueError("cache_score_threshold must be a number.") from exc

        self.db_provider = db_provider
        self.retrieval_mode = retrieval_mode
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_score_threshold = cache_score_threshold
        self.collection = collection
        self.index = index
        self.connection = connection
        self.table_name = table_name
        self.enable_native_hybrid_search = enable_native_hybrid_search
        self.oracle_metadata_filters = oracle_metadata_filters or {}
        self.enable_oracle_json_payload = enable_oracle_json_payload
        self.enable_provenance_metadata = enable_provenance_metadata
        self.vector_index_name = vector_index_name
        self.vector_index_type = vector_index_type
        self.vector_index_distance = vector_index_distance
        self.vector_index_accuracy = vector_index_accuracy
        self.vector_index_neighbors = vector_index_neighbors
        self.vector_index_efconstruction = vector_index_efconstruction
        self.vector_index_partitions = vector_index_partitions
        self.dedup_similarity_threshold = dedup_similarity_threshold
        self.cache_timestamp_field = cache_timestamp_field

        if db_provider == 'mongodb':
            if collection is None:
                raise ValueError("collection is required when db_provider='mongodb'.")
            if index is None:
                raise ValueError("index is required when db_provider='mongodb'.")
            self.embeddings_field = embeddings_field
            self.content_field = content_field
        elif db_provider == 'oracle':
            if connection is None:
                raise ValueError("connection is required when db_provider='oracle'.")
            if table_name is None:
                raise ValueError("table_name is required when db_provider='oracle'.")
            self.table_name = _validate_oracle_identifier(table_name, "table_name")
            self.embeddings_field = _validate_oracle_identifier(embeddings_field, "embeddings_field")
            self.content_field = _validate_oracle_identifier(content_field, "content_field")
            self.cache_timestamp_field = _validate_oracle_identifier(cache_timestamp_field, "cache_timestamp_field")
            if vector_index_name is not None:
                self.vector_index_name = _validate_oracle_identifier(vector_index_name, "vector_index_name")
            self.vector_index_type = self._validate_oracle_vector_index_type(vector_index_type)
            self.vector_index_distance = self._validate_oracle_vector_distance(vector_index_distance)
            if dedup_similarity_threshold is not None:
                try:
                    self.dedup_similarity_threshold = float(dedup_similarity_threshold)
                except (TypeError, ValueError) as exc:
                    raise ValueError("dedup_similarity_threshold must be a number.") from exc

        self.embedding_function = _cohere_embed if embedding_function is None else embedding_function
        self.ranking_function = _cohere_rerank if ranking_function is None else ranking_function

        if not callable(self.embedding_function):
            raise TypeError("embedding_function must be callable.")
        if not callable(self.ranking_function):
            raise TypeError("ranking_function must be callable.")

        if db_provider == 'mongodb':
            _validate_index(self)
        elif db_provider == 'oracle':
            # Oracle config is validated above when identifiers are normalized.
            pass

    def search(self, query, max_results=10, max_local=None, max_foreign=None,
               save_foreign=False, **kwargs):
        '''
        Return results for the given query from both the tavily API (foreign) and
        the configured database provider (local).

        Parameters:
        query (str): The query to search for.
        max_results (int): The maximum number of results to return.
        max_local (int): The maximum number of local results to return.
        max_foreign (int): The maximum number of foreign results to return.
        save_foreign (bool or function): Whether to save the foreign results in the local database.
            If a function is provided, it will be used to transform the foreign results before saving.
        '''

        if max_local is None:
            max_local = max_results

        if max_foreign is None:
            max_foreign = max_results

        query_embeddings = self.embedding_function([query], 'search_query')[0]

        if self.db_provider == 'mongodb':
            # Search the local collection
            local_results = list(self.collection.aggregate([
                {
                    "$vectorSearch": {
                        "index": self.index,
                        "path": self.embeddings_field,
                        "queryVector": query_embeddings,
                        "numCandidates": max_local + 3,
                        "limit": max_local
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "content": f"${self.content_field}",
                        "score": {
                            "$meta": "vectorSearchScore"
                        },
                        "origin": "local"
                    }
                }
            ]))
        elif self.db_provider == 'oracle':
            if self.retrieval_mode == 'freshness_cache':
                return self._search_oracle_freshness_cache(
                    query,
                    query_embeddings,
                    max_results,
                    max_local,
                    max_foreign,
                    save_foreign,
                    **kwargs
                )
            local_results = self._search_oracle(query_embeddings, max_local, query=query)
        else:
            raise ValueError(f"Unsupported database provider: {self.db_provider}")

        foreign_results = self._search_tavily(query, max_foreign, **kwargs)

        # Combine the results
        projected_foreign_results = self._project_foreign_results(foreign_results)

        combined_results = local_results + projected_foreign_results

        if len(combined_results) == 0:
            return []

        # Sort the combined results
        combined_results = self.ranking_function(query, combined_results, max_results)

        if len(combined_results) > max_results:
            combined_results = combined_results[:max_results]

        self._save_foreign_results(foreign_results, save_foreign, max_foreign, query)

        return combined_results

    def _search_tavily(self, query, max_foreign, **kwargs):
        if max_foreign > 0:
            return self.tavily.search(query, max_results=max_foreign, **kwargs)['results']
        return []

    def _project_foreign_results(self, foreign_results):
        return [
            {
                'content': result['content'],
                'score': result['score'],
                'origin': 'foreign'
            }
            for result in foreign_results
        ]

    def _save_foreign_results(self, foreign_results, save_foreign, max_foreign,
                              query=None, cache_hit=False):
        # Can't use 'not save_foreign' because save_foreign is not necessarily a boolean
        if not (max_foreign > 0 and save_foreign != False):
            return

        documents = []
        embeddings = self.embedding_function([result['content'] for result in foreign_results], 'search_document')
        for i, result in enumerate(foreign_results):
            raw_result = result.copy()
            result['embeddings'] = embeddings[i]

            if save_foreign == True:
                # No custom function provided, save the searchable fields.
                document = {
                    self.content_field: result['content'],
                    self.embeddings_field: result['embeddings']
                }
                if self.db_provider == 'oracle':
                    document.update(
                        self._build_oracle_persistence_metadata(
                            raw_result,
                            query,
                            cache_hit
                        )
                    )
                documents.append(document)
            else:
                # save_foreign is a custom function
                result = save_foreign(result)
                if result:
                    documents.append(result)

        if not documents:
            return

        if self.db_provider == 'mongodb':
            # Add all in one call to make the operation atomic
            self.collection.insert_many(documents)
        elif self.db_provider == 'oracle':
            documents = self._filter_oracle_duplicate_documents(documents)
            if not documents:
                return
            self._insert_oracle_documents(documents)
        else:
            raise ValueError(f"Unsupported database provider: {self.db_provider}")

    def _search_oracle_freshness_cache(self, query, query_embeddings, max_results,
                                       max_local, max_foreign, save_foreign,
                                       **kwargs):
        local_results = self._search_oracle(
            query_embeddings,
            max_local,
            query=query,
            cache_ttl_seconds=self.cache_ttl_seconds
        )
        cache_results = [
            result
            for result in local_results
            if result['score'] >= self.cache_score_threshold
        ]

        if cache_results:
            return cache_results[:max_results]

        foreign_results = self._search_tavily(query, max_foreign, **kwargs)
        results = self._project_foreign_results(foreign_results)

        if len(results) == 0:
            return []

        self._save_foreign_results(
            foreign_results,
            save_foreign,
            max_foreign,
            query,
            cache_hit=False
        )
        return results[:max_results]

    def _search_oracle(self, query_embeddings, max_local, query=None, cache_ttl_seconds=None):
        limit = int(max_local)
        if limit < 1:
            return []

        if self.enable_native_hybrid_search and query:
            return self._search_oracle_native_hybrid(
                query_embeddings,
                max_local,
                query,
                cache_ttl_seconds=cache_ttl_seconds
            )

        execute_kwargs = {"query_vector": _to_oracle_vector(query_embeddings)}
        freshness_filter = self._build_oracle_freshness_filter(cache_ttl_seconds, execute_kwargs)
        metadata_filter = self._build_oracle_metadata_filter(execute_kwargs)

        sql = f"""
            SELECT {self.content_field},
                   1 - VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE) AS score,
                   'local' AS origin
            FROM {self.table_name}
            WHERE {self.embeddings_field} IS NOT NULL
              {freshness_filter}
              {metadata_filter}
            ORDER BY VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE)
            FETCH FIRST {limit} ROWS ONLY
        """

        with self.connection.cursor() as cursor:
            cursor.execute(sql, **execute_kwargs)
            return [
                {
                    'content': _read_lob(row[0]),
                    'score': row[1],
                    'origin': row[2]
                }
                for row in cursor.fetchall()
            ]

    def _search_oracle_native_hybrid(self, query_embeddings, max_local, query,
                                     cache_ttl_seconds=None):
        limit = int(max_local)
        if limit < 1:
            return []

        execute_kwargs = {
            "query_vector": _to_oracle_vector(query_embeddings),
            "text_query": query,
        }
        freshness_filter = self._build_oracle_freshness_filter(cache_ttl_seconds, execute_kwargs)
        metadata_filter = self._build_oracle_metadata_filter(execute_kwargs)

        sql = f"""
            WITH vector_candidates AS (
                SELECT ROWID AS rid,
                       1 - VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE) AS vector_score,
                       0 AS text_score
                FROM {self.table_name}
                WHERE {self.embeddings_field} IS NOT NULL
                  {freshness_filter}
                  {metadata_filter}
                ORDER BY VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE)
                FETCH FIRST {limit} ROWS ONLY
            ),
            text_candidates AS (
                SELECT ROWID AS rid,
                       1 - VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE) AS vector_score,
                       SCORE(1) / 100 AS text_score
                FROM {self.table_name}
                WHERE {self.embeddings_field} IS NOT NULL
                  AND CONTAINS({self.content_field}, :text_query, 1) > 0
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
            SELECT source.{self.content_field},
                   ranked.score,
                   'local' AS origin
            FROM {self.table_name} source
            JOIN ranked_candidates ranked ON source.ROWID = ranked.rid
            ORDER BY ranked.score DESC
        """

        with self.connection.cursor() as cursor:
            cursor.execute(sql, **execute_kwargs)
            return [
                {
                    'content': _read_lob(row[0]),
                    'score': row[1],
                    'origin': row[2]
                }
                for row in cursor.fetchall()
            ]

    def _build_oracle_freshness_filter(self, cache_ttl_seconds, execute_kwargs):
        if cache_ttl_seconds is None:
            return ""

        execute_kwargs["cache_ttl_seconds"] = cache_ttl_seconds
        return (
            f"AND {self.cache_timestamp_field} >= "
            "CAST(SYSTIMESTAMP AS TIMESTAMP) - "
            "NUMTODSINTERVAL(:cache_ttl_seconds, 'SECOND')"
        )

    def _build_oracle_metadata_filter(self, execute_kwargs):
        if not self.oracle_metadata_filters:
            return ""

        clauses = []
        for i, (key, value) in enumerate(self.oracle_metadata_filters.items()):
            column = _validate_oracle_identifier(key, "oracle_metadata_filters key")

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

    def _build_oracle_persistence_metadata(self, result, query, cache_hit):
        if not (self.enable_oracle_json_payload or self.enable_provenance_metadata):
            return {}

        timestamp = datetime.now(timezone.utc)
        metadata = {}

        if self.enable_oracle_json_payload:
            payload = {
                "result": result,
                "provenance": {
                    "source_url": result.get("url"),
                    "retrieval_query": query,
                    "retrieval_timestamp": timestamp.isoformat(),
                    "retrieval_mode": self.retrieval_mode,
                    "cache_hit": cache_hit,
                    "inserted_from": "tavily",
                    "provider_name": "tavily",
                },
            }
            metadata[_ORACLE_RAW_PAYLOAD_FIELD] = json.dumps(
                payload,
                sort_keys=True,
                default=str
            )

        if self.enable_provenance_metadata:
            metadata.update({
                _ORACLE_SOURCE_URL_FIELD: result.get("url"),
                _ORACLE_SOURCE_TITLE_FIELD: result.get("title"),
                _ORACLE_RETRIEVAL_QUERY_FIELD: query,
                _ORACLE_RETRIEVAL_TIMESTAMP_FIELD: timestamp,
                _ORACLE_RETRIEVAL_MODE_FIELD: self.retrieval_mode,
                _ORACLE_CACHE_HIT_FIELD: 1 if cache_hit else 0,
                _ORACLE_INSERTED_FROM_FIELD: "tavily",
                _ORACLE_PROVIDER_NAME_FIELD: "tavily",
            })

        return metadata

    def _filter_oracle_duplicate_documents(self, documents):
        if self.dedup_similarity_threshold is None:
            return documents

        unique_documents = []
        for document in documents:
            embedding = self._get_oracle_document_value(document, self.embeddings_field)
            if embedding is None or not self._is_oracle_duplicate(embedding):
                unique_documents.append(document)
        return unique_documents

    def _get_oracle_document_value(self, document, column_name):
        for key, value in document.items():
            if _validate_oracle_identifier(key, "document key") == column_name:
                return value
        return None

    def _is_oracle_duplicate(self, embedding):
        sql = f"""
            SELECT 1 - VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE) AS score
            FROM {self.table_name}
            WHERE {self.embeddings_field} IS NOT NULL
            ORDER BY VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE)
            FETCH FIRST 1 ROWS ONLY
        """

        with self.connection.cursor() as cursor:
            cursor.execute(sql, query_vector=_to_oracle_vector(embedding))
            row = cursor.fetchone()

        if row is None:
            return False

        return row[0] >= self.dedup_similarity_threshold

    def ensure_oracle_vector_index(self, index_name=None):
        if self.db_provider != 'oracle':
            raise ValueError("ensure_oracle_vector_index is only supported when db_provider='oracle'.")

        index_name = index_name or self.vector_index_name
        if index_name is None:
            index_name = f"{self.table_name}_{self.embeddings_field}_VEC_IDX"
        index_name = _validate_oracle_identifier(index_name, "index_name")

        with self.connection.cursor() as cursor:
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
                table_name=self.table_name,
                idx_vector_col=self.embeddings_field,
                idx_partitioning_scheme="GLOBAL" if self.vector_index_type == "IVF" else None,
                idx_organization=_ORACLE_VECTOR_INDEX_ORGANIZATIONS[self.vector_index_type],
                idx_distance_metric=self.vector_index_distance,
                idx_accuracy=int(self.vector_index_accuracy),
                idx_parameters=self._oracle_vector_index_parameters(),
            )

        self.connection.commit()
        return True

    def _oracle_vector_index_parameters(self):
        if self.vector_index_type == "HNSW":
            return json.dumps({
                "type": "HNSW",
                "neighbors": int(self.vector_index_neighbors),
                "efConstruction": int(self.vector_index_efconstruction),
            })

        return json.dumps({
            "type": "IVF",
            "partitions": int(self.vector_index_partitions),
        })

    def _validate_oracle_vector_index_type(self, value):
        value = value.upper()
        if value not in _ORACLE_VECTOR_INDEX_TYPES:
            raise ValueError("vector_index_type must be 'HNSW' or 'IVF'.")
        return value

    def _validate_oracle_vector_distance(self, value):
        value = value.upper()
        if value not in _ORACLE_VECTOR_DISTANCE_METRICS:
            raise ValueError(
                "vector_index_distance must be one of "
                f"{', '.join(_ORACLE_VECTOR_DISTANCE_METRICS)}."
            )
        return value

    def _insert_oracle_documents(self, documents):
        if not documents:
            return

        normalized_documents = []
        column_names = set()

        for document in documents:
            normalized_document = {
                _validate_oracle_identifier(key, "document key"): value
                for key, value in document.items()
            }

            if self.content_field not in normalized_document or self.embeddings_field not in normalized_document:
                raise ValueError(
                    "Oracle save_foreign documents must include both "
                    f"'{self.content_field}' and '{self.embeddings_field}'."
                )

            for column_name, value in normalized_document.items():
                if column_name == self.embeddings_field:
                    value = _to_oracle_vector(value)
                normalized_document[column_name] = value
                column_names.add(column_name)

            normalized_documents.append(normalized_document)

        ordered_columns = sorted(column_names)
        columns = ", ".join(ordered_columns)
        placeholders = ", ".join(f":{column}" for column in ordered_columns)
        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        rows = [
            {column: document.get(column) for column in ordered_columns}
            for document in normalized_documents
        ]

        with self.connection.cursor() as cursor:
            cursor.executemany(sql, rows)
        self.connection.commit()
