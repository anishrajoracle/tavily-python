from typing import Callable, Literal, Optional, Sequence, Union

import requests
from tavily import TavilyClient
from tavily.databases import get_provider
from tavily.databases.base import DatabaseProvider
from tavily.databases import oracledb as oracle_database
from tavily.databases.config import RETRIEVAL_MODES
from tavily.databases.oracle_config import ORACLE_CACHE_TIMESTAMP_FIELD
from tavily.hybrid_rag.embeddings import cohere_embed, cohere_rerank


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
            cache_timestamp_field: str = ORACLE_CACHE_TIMESTAMP_FIELD,
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

        self.database_provider: DatabaseProvider = get_provider(db_provider)
        if retrieval_mode not in RETRIEVAL_MODES:
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
            self.table_name = oracle_database.validate_identifier(table_name, "table_name")
            self.embeddings_field = oracle_database.validate_identifier(embeddings_field, "embeddings_field")
            self.content_field = oracle_database.validate_identifier(content_field, "content_field")
            self.cache_timestamp_field = oracle_database.validate_identifier(
                cache_timestamp_field,
                "cache_timestamp_field"
            )
            if vector_index_name is not None:
                self.vector_index_name = oracle_database.validate_identifier(vector_index_name, "vector_index_name")
            self.vector_index_type = oracle_database.validate_vector_index_type(vector_index_type)
            self.vector_index_distance = oracle_database.validate_vector_distance(vector_index_distance)
            if dedup_similarity_threshold is not None:
                try:
                    self.dedup_similarity_threshold = float(dedup_similarity_threshold)
                except (TypeError, ValueError) as exc:
                    raise ValueError("dedup_similarity_threshold must be a number.") from exc

        self.embedding_function = cohere_embed if embedding_function is None else embedding_function
        self.ranking_function = cohere_rerank if ranking_function is None else ranking_function

        if not callable(self.embedding_function):
            raise TypeError("embedding_function must be callable.")
        if not callable(self.ranking_function):
            raise TypeError("ranking_function must be callable.")

        self.database_provider.validate_client(self)

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

        if self.db_provider == 'oracle':
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

    def _search_oracle_freshness_cache(self, query, query_embeddings, max_results,
                                       max_local, max_foreign, save_foreign,
                                       **kwargs):
        local_results = self.database_provider.search_provider(
            self,
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

    def ensure_oracle_vector_index(self, index_name=None):
        return oracle_database.ensure_vector_index(self, index_name=index_name)
