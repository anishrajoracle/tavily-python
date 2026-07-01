from math import isfinite
from typing import Callable, Literal, Optional, Sequence, Union
from time import monotonic

import requests
from tavily import TavilyClient
from tavily.databases import get_provider
from tavily.databases.base import DatabaseProvider
from tavily.databases.connections import connect_mongodb, connect_oracle
from tavily.databases.oracledb import oracledb as oracle_database
from tavily.databases.config import PERSISTENCE_DEPTHS, RETRIEVAL_MODES
from tavily.databases.oracledb.oracle_config import ORACLE_CACHE_TIMESTAMP_FIELD
from tavily.hybrid_rag.embeddings import cohere_embed, cohere_rerank
from tavily.hybrid_rag import retrieval_modes


def _finite_float(value, name):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    return parsed


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
            retrieval_mode: Literal['hybrid_search', 'freshness_cache', 'cache_then_memory'] = 'hybrid_search',
            cache_ttl_seconds: int = 86400,
            cache_score_threshold: float = 0.0,
            cache_timestamp_field: str = ORACLE_CACHE_TIMESTAMP_FIELD,
            persistence_depth: Optional[Literal['cache_only', 'cache_plus_memory']] = None,
            memory_score_threshold: float = 0.0,
            memory_max_results: Optional[int] = None,
            enable_oracle_memory_metadata: bool = False,
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
            dedup_similarity_threshold: Optional[float] = None,
            oracle_upsert_key: Optional[Literal['source_url', 'content_hash']] = None,
            max_persisted_foreign: Optional[int] = None,
            persist_score_threshold: Optional[float] = None,
            oracle_user: Optional[str] = None,
            oracle_password: Optional[str] = None,
            oracle_dsn: Optional[str] = None,
            oracle_connection_kwargs: Optional[dict] = None,
            mongo_uri: Optional[str] = None,
            mongo_database: Optional[str] = None,
            mongo_collection: Optional[str] = None,
            mongo_client_kwargs: Optional[dict] = None,
            auto_cleanup_cache: bool = False,
            cache_cleanup_interval_seconds: int = 3600,
            text_index_name: Optional[str] = None
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
        retrieval_mode (str): Retrieval mode. 'hybrid_search' is supported for MongoDB and Oracle. 'freshness_cache' and 'cache_then_memory' are Oracle-only.
        cache_ttl_seconds (int): Freshness window used by Oracle freshness_cache mode.
        cache_score_threshold (float): Minimum local score needed for an Oracle freshness_cache hit.
        cache_timestamp_field (str): Oracle timestamp column used by freshness_cache mode.
        persistence_depth (str): Oracle memory lifecycle scope, 'cache_only' or 'cache_plus_memory'. Defaults to 'cache_plus_memory' for cache_then_memory and 'cache_only' otherwise.
        memory_score_threshold (float): Minimum local score needed for an Oracle long-term memory hit.
        memory_max_results (int): Maximum long-term memory results to inspect in cache_then_memory mode.
        enable_oracle_memory_metadata (bool): If True, Oracle save_foreign=True writes cache/memory lifecycle columns.
        enable_native_hybrid_search (bool): If True, Oracle local search uses Oracle Text scoring along with vector similarity.
        oracle_metadata_filters (dict): Optional Oracle column filters applied during local Oracle search.
        enable_oracle_json_payload (bool): If True, Oracle save_foreign=True writes RAW_PAYLOAD JSON.
        enable_provenance_metadata (bool): If True, Oracle save_foreign=True writes provenance columns.
        text_index_name (str): Optional Oracle Text index name used by ensure_oracle_text_index().
        vector_index_name (str): Optional Oracle vector index name used by ensure_oracle_vector_index().
        vector_index_type (str): Oracle vector index type, 'HNSW' or 'IVF'.
        vector_index_distance (str): Oracle vector index distance metric.
        vector_index_accuracy (int): Oracle vector index target accuracy.
        vector_index_neighbors (int): HNSW neighbors parameter.
        vector_index_efconstruction (int): HNSW efConstruction parameter.
        vector_index_partitions (int): IVF partitions parameter.
        dedup_similarity_threshold (float): If set for Oracle, skip insert when nearest local similarity is at or above this threshold.
        oracle_upsert_key (str): If set for Oracle, merge persisted Tavily rows by 'source_url' or 'content_hash'.
        max_persisted_foreign (int): Optional cap on how many Tavily results are persisted per search.
        persist_score_threshold (float): Optional minimum Tavily score required before persisting a result.
        oracle_user (str): Optional Oracle username used to create a connection when connection is not provided.
        oracle_password (str): Optional Oracle password used to create a connection when connection is not provided.
        oracle_dsn (str): Optional Oracle DSN used to create a connection when connection is not provided.
        oracle_connection_kwargs (dict): Extra keyword arguments forwarded to oracledb.connect().
        mongo_uri (str): Optional MongoDB URI used to create a collection when collection is not provided.
        mongo_database (str): MongoDB database name used with mongo_uri.
        mongo_collection (str): MongoDB collection name used with mongo_uri.
        mongo_client_kwargs (dict): Extra keyword arguments forwarded to pymongo.MongoClient().
        auto_cleanup_cache (bool): If True for Oracle, expired cache rows are cleaned up before search.
        cache_cleanup_interval_seconds (int): Minimum seconds between automatic cleanup attempts.
        '''

        self.tavily = None
        self._managed_mongo_client = None
        self._managed_oracle_connection = None

        should_connect_mongodb = (
            db_provider == 'mongodb'
            and collection is None
            and any(value is not None for value in (mongo_uri, mongo_database, mongo_collection))
        )
        should_connect_oracle = (
            db_provider == 'oracle'
            and connection is None
            and any(value is not None for value in (oracle_user, oracle_password, oracle_dsn))
        )

        self.database_provider: DatabaseProvider = get_provider(db_provider)
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ValueError(
                "Supported retrieval modes are 'hybrid_search', "
                "'freshness_cache', and 'cache_then_memory'."
            )
        if db_provider != 'oracle' and retrieval_mode in ('freshness_cache', 'cache_then_memory'):
            raise ValueError(
                "retrieval_mode='freshness_cache' and "
                "retrieval_mode='cache_then_memory' are only supported when "
                "db_provider='oracle'."
            )
        if (
            db_provider == 'oracle'
            and (
                retrieval_mode in ('freshness_cache', 'cache_then_memory')
                or enable_oracle_memory_metadata
            )
        ):
            if cache_ttl_seconds <= 0:
                raise ValueError("cache_ttl_seconds must be greater than 0.")
        if db_provider == 'oracle' and retrieval_mode in ('freshness_cache', 'cache_then_memory'):
            cache_score_threshold = _finite_float(
                cache_score_threshold,
                "cache_score_threshold"
            )
        if db_provider == 'oracle' and retrieval_mode == 'cache_then_memory':
            enable_oracle_memory_metadata = True
        if persistence_depth is None:
            if db_provider == 'oracle' and retrieval_mode == 'cache_then_memory':
                persistence_depth = 'cache_plus_memory'
            else:
                persistence_depth = 'cache_only'
        if db_provider == 'oracle':
            if persistence_depth not in PERSISTENCE_DEPTHS:
                raise ValueError(
                    "persistence_depth must be 'cache_only' or 'cache_plus_memory'."
                )
            memory_score_threshold = _finite_float(
                memory_score_threshold,
                "memory_score_threshold"
            )
            if memory_max_results is not None and memory_max_results <= 0:
                raise ValueError("memory_max_results must be greater than 0.")
            if oracle_upsert_key not in (None, "source_url", "content_hash"):
                raise ValueError(
                    "oracle_upsert_key must be 'source_url', 'content_hash', or None."
                )
        if max_persisted_foreign is not None and max_persisted_foreign <= 0:
            raise ValueError("max_persisted_foreign must be greater than 0.")
        if persist_score_threshold is not None:
            persist_score_threshold = _finite_float(
                persist_score_threshold,
                "persist_score_threshold"
            )
        if auto_cleanup_cache and db_provider != 'oracle':
            raise ValueError("auto_cleanup_cache is only supported when db_provider='oracle'.")
        if auto_cleanup_cache and cache_cleanup_interval_seconds <= 0:
            raise ValueError("cache_cleanup_interval_seconds must be greater than 0.")

        self.db_provider = db_provider
        self.retrieval_mode = retrieval_mode
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_score_threshold = cache_score_threshold
        self.persistence_depth = persistence_depth
        self.memory_score_threshold = memory_score_threshold
        self.memory_max_results = memory_max_results
        self.enable_oracle_memory_metadata = enable_oracle_memory_metadata
        self.collection = collection
        self.index = index
        self.connection = connection
        self.table_name = table_name
        self.enable_native_hybrid_search = enable_native_hybrid_search
        self.oracle_metadata_filters = oracle_metadata_filters or {}
        self.enable_oracle_json_payload = enable_oracle_json_payload
        self.enable_provenance_metadata = enable_provenance_metadata
        self.text_index_name = text_index_name
        self.vector_index_name = vector_index_name
        self.vector_index_type = vector_index_type
        self.vector_index_distance = vector_index_distance
        self.vector_index_accuracy = vector_index_accuracy
        self.vector_index_neighbors = vector_index_neighbors
        self.vector_index_efconstruction = vector_index_efconstruction
        self.vector_index_partitions = vector_index_partitions
        self.dedup_similarity_threshold = dedup_similarity_threshold
        self.oracle_upsert_key = oracle_upsert_key if db_provider == 'oracle' else None
        self.max_persisted_foreign = max_persisted_foreign
        self.persist_score_threshold = persist_score_threshold
        self.auto_cleanup_cache = auto_cleanup_cache
        self.cache_cleanup_interval_seconds = cache_cleanup_interval_seconds
        self._last_cache_cleanup_at = None
        self.cache_timestamp_field = cache_timestamp_field

        if db_provider == 'mongodb':
            if collection is None and not should_connect_mongodb:
                raise ValueError("collection is required when db_provider='mongodb'.")
            if index is None:
                raise ValueError("index is required when db_provider='mongodb'.")
            self.embeddings_field = embeddings_field
            self.content_field = content_field
        elif db_provider == 'oracle':
            if connection is None and not should_connect_oracle:
                raise ValueError("connection is required when db_provider='oracle'.")
            if table_name is None:
                raise ValueError("table_name is required when db_provider='oracle'.")
            self.table_name = oracle_database.validate_identifier(table_name, "table_name")
            self.embeddings_field = oracle_database.validate_identifier(embeddings_field, "embeddings_field")
            self.content_field = oracle_database.validate_identifier(content_field, "content_field")
            self.cache_timestamp_field = oracle_database.validate_identifier(
                cache_timestamp_field,
                "cache_timestamp_field"
            )
            if vector_index_name is not None:
                self.vector_index_name = oracle_database.validate_identifier(vector_index_name, "vector_index_name")
            if text_index_name is not None:
                self.text_index_name = oracle_database.validate_identifier(text_index_name, "text_index_name")
            self.vector_index_type = oracle_database.validate_vector_index_type(vector_index_type)
            self.vector_index_distance = oracle_database.validate_vector_distance(vector_index_distance)
            if dedup_similarity_threshold is not None:
                self.dedup_similarity_threshold = _finite_float(
                    dedup_similarity_threshold,
                    "dedup_similarity_threshold"
                )
            if self.vector_index_distance != "COSINE" and (
                retrieval_mode in ("freshness_cache", "cache_then_memory")
                or self.dedup_similarity_threshold is not None
            ):
                raise ValueError(
                    "Oracle cache/memory thresholds and semantic deduplication "
                    "currently require vector_index_distance='COSINE'."
                )

        self.embedding_function = cohere_embed if embedding_function is None else embedding_function
        self.ranking_function = cohere_rerank if ranking_function is None else ranking_function

        if not callable(self.embedding_function):
            raise TypeError("embedding_function must be callable.")
        if not callable(self.ranking_function):
            raise TypeError("ranking_function must be callable.")

        try:
            if should_connect_mongodb:
                self._managed_mongo_client, collection = connect_mongodb(
                    mongo_uri,
                    mongo_database,
                    mongo_collection,
                    mongo_client_kwargs=mongo_client_kwargs
                )
                self.collection = collection

            if should_connect_oracle:
                connection = connect_oracle(
                    oracle_user,
                    oracle_password,
                    oracle_dsn,
                    oracle_connection_kwargs=oracle_connection_kwargs
                )
                self._managed_oracle_connection = connection
                self.connection = connection

            self.tavily = TavilyClient(api_key, session=session)
            self.database_provider.validate_client(self)
        except Exception:
            self.close()
            raise

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

        self._maybe_cleanup_cache()

        query_embeddings = self.embedding_function([query], 'search_query')[0]

        if self.db_provider == 'oracle':
            if self.retrieval_mode == 'freshness_cache':
                return retrieval_modes.search_oracle_freshness_cache(
                    self,
                    query,
                    query_embeddings,
                    max_results,
                    max_local,
                    max_foreign,
                    save_foreign,
                    **kwargs
                )
            if self.retrieval_mode == 'cache_then_memory':
                return retrieval_modes.search_oracle_cache_then_memory(
                    self,
                    query,
                    query_embeddings,
                    max_results,
                    max_local,
                    max_foreign,
                    save_foreign,
                    **kwargs
                )
        local_results = self.database_provider.search_provider(
            self,
            query_embeddings,
            max_local,
            query=query
        )

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

        foreign_results = self._select_foreign_results_for_persistence(foreign_results)
        if not foreign_results:
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
                        oracle_database.build_persistence_metadata(
                            self,
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

        self.database_provider.insert_provider(self, documents)

    def _select_foreign_results_for_persistence(self, foreign_results):
        candidates = []
        for result in foreign_results:
            if self.persist_score_threshold is not None:
                score = result.get('score')
                if score is None or score < self.persist_score_threshold:
                    continue
            candidates.append(result)

        if self.max_persisted_foreign is not None:
            return candidates[:self.max_persisted_foreign]

        return candidates

    def ensure_oracle_vector_index(self, index_name=None):
        return oracle_database.ensure_vector_index(self, index_name=index_name)

    def ensure_oracle_text_index(self, index_name=None):
        return oracle_database.ensure_text_index(self, index_name=index_name)

    def cleanup_cache(self, cache_ttl_seconds=None):
        return oracle_database.delete_expired_cache_rows(
            self,
            cache_ttl_seconds=cache_ttl_seconds
        )

    def _maybe_cleanup_cache(self):
        if not (self.db_provider == 'oracle' and self.auto_cleanup_cache):
            return

        now = monotonic()
        if (
            self._last_cache_cleanup_at is not None
            and now - self._last_cache_cleanup_at < self.cache_cleanup_interval_seconds
        ):
            return

        self.cleanup_cache()
        self._last_cache_cleanup_at = now

    def close(self):
        if hasattr(self.tavily, "close"):
            self.tavily.close()
        if self._managed_oracle_connection is not None:
            self._managed_oracle_connection.close()
            self._managed_oracle_connection = None
        if self._managed_mongo_client is not None:
            self._managed_mongo_client.close()
            self._managed_mongo_client = None
