from typing import Protocol


class DatabaseProvider(Protocol):
    def validate_client(self, client):
        ...

    def search_provider(self, client, query_embeddings, max_local,
                        query=None, cache_ttl_seconds=None):
        ...

    def insert_provider(self, client, documents):
        ...
