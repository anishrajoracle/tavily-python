import array
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
            db_provider: Literal['oracle', 'mongodb'],
            collection=None,
            index: Optional[str] = None,
            embeddings_field: str = 'embeddings',
            content_field: str = 'content',
            connection=None,
            table_name: Optional[str] = None,
            embedding_function: Optional[Callable[[Sequence[str], str], Sequence[Sequence[float]]]] = None,
            ranking_function: Optional[Callable[[str, list, int], list]] = None,
            session: Optional[requests.Session] = None
        ):
        '''
        A client for performing hybrid RAG using both the Tavily API and a local database.

        Parameters:
        api_key (str): The Tavily API key. If this is set to None, it will be loaded from the environment variable TAVILY_API_KEY.
        db_provider (str): The database provider. Supported values are 'oracle' and 'mongodb'.
        connection: A python-oracledb connection. Required when db_provider='oracle'.
        table_name (str): The Oracle table that stores content and vector embeddings. Required when db_provider='oracle'.
        collection: The MongoDB collection object that will be used for local search. Required when db_provider='mongodb'.
        index (str): The MongoDB collection's vector search index. Required when db_provider='mongodb'.
        embeddings_field (str): The name of the field in the database that contains the embeddings.
        content_field (str): The name of the field in the database that contains the content.
        embedding_function (callable): If provided, this function will be used to generate embeddings for the search query and documents.
        ranking_function (callable): If provided, this function will be used to rerank the combined results.
        session (requests.Session): If provided, this pre-configured session will be used for HTTP requests. When set, api_key is optional.
        '''

        self.tavily = TavilyClient(api_key, session=session)

        if db_provider not in ('oracle', 'mongodb'):
            raise ValueError("Supported database providers are 'oracle' and 'mongodb'.")
        self.db_provider = db_provider
        self.collection = collection
        self.index = index
        self.connection = connection
        self.table_name = table_name

        if db_provider == 'oracle':
            if connection is None:
                raise ValueError("connection is required when db_provider='oracle'.")
            if table_name is None:
                raise ValueError("table_name is required when db_provider='oracle'.")
            self.table_name = _validate_oracle_identifier(table_name, "table_name")
            self.embeddings_field = _validate_oracle_identifier(embeddings_field, "embeddings_field")
            self.content_field = _validate_oracle_identifier(content_field, "content_field")
        elif db_provider == 'mongodb':
            if collection is None:
                raise ValueError("collection is required when db_provider='mongodb'.")
            if index is None:
                raise ValueError("index is required when db_provider='mongodb'.")
            self.embeddings_field = embeddings_field
            self.content_field = content_field

        self.embedding_function = _cohere_embed if embedding_function is None else embedding_function
        self.ranking_function = _cohere_rerank if ranking_function is None else ranking_function

        if not callable(self.embedding_function):
            raise TypeError("embedding_function must be callable.")
        if not callable(self.ranking_function):
            raise TypeError("ranking_function must be callable.")

        if db_provider == 'oracle':
            # Oracle config is validated above when identifiers are normalized.
            pass
        elif db_provider == 'mongodb':
            _validate_index(self)

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
            local_results = self._search_oracle(query_embeddings, max_local)
        elif self.db_provider == 'mongodb':
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
        else:
            raise ValueError(f"Unsupported database provider: {self.db_provider}")

        # Search using tavily
        if max_foreign > 0:
            foreign_results = self.tavily.search(query, max_results=max_foreign, **kwargs)['results']
        else:
            foreign_results = []

        # Combine the results
        projected_foreign_results = [
            {
                'content': result['content'],
                'score': result['score'],
                'origin': 'foreign'
            }
            for result in foreign_results
        ]

        combined_results = local_results + projected_foreign_results

        if len(combined_results) == 0:
            return []

        # Sort the combined results
        combined_results = self.ranking_function(query, combined_results, max_results)

        if len(combined_results) > max_results:
            combined_results = combined_results[:max_results]

        # Can't use 'not save_foreign' because save_foreign is not necessarily a boolean
        if max_foreign > 0 and save_foreign != False:
            documents = []
            embeddings = self.embedding_function([result['content'] for result in foreign_results], 'search_document')
            for i, result in enumerate(foreign_results):
                result['embeddings'] = embeddings[i]

                if save_foreign == True:
                    # No custom function provided, save the searchable fields.
                    documents.append({
                        self.content_field: result['content'],
                        self.embeddings_field: result['embeddings']
                    })
                else:
                    # save_foreign is a custom function
                    result = save_foreign(result)
                    if result:
                        documents.append(result)

            if not documents:
                return combined_results

            if self.db_provider == 'oracle':
                self._insert_oracle_documents(documents)
            elif self.db_provider == 'mongodb':
                # Add all in one call to make the operation atomic
                self.collection.insert_many(documents)
            else:
                raise ValueError(f"Unsupported database provider: {self.db_provider}")

        return combined_results

    def _search_oracle(self, query_embeddings, max_local):
        limit = int(max_local)
        if limit < 1:
            return []

        sql = f"""
            SELECT {self.content_field},
                   1 - VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE) AS score,
                   'local' AS origin
            FROM {self.table_name}
            WHERE {self.embeddings_field} IS NOT NULL
            ORDER BY VECTOR_DISTANCE({self.embeddings_field}, :query_vector, COSINE)
            FETCH FIRST {limit} ROWS ONLY
        """

        with self.connection.cursor() as cursor:
            cursor.execute(sql, query_vector=_to_oracle_vector(query_embeddings))
            return [
                {
                    'content': _read_lob(row[0]),
                    'score': row[1],
                    'origin': row[2]
                }
                for row in cursor.fetchall()
            ]

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
