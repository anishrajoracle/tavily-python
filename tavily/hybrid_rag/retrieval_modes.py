def search_oracle_freshness_cache(client, query, query_embeddings, max_results,
                                  max_local, max_foreign, save_foreign,
                                  **kwargs):
    local_results = client.database_provider.search_provider(
        client,
        query_embeddings,
        max_local,
        query=query,
        cache_ttl_seconds=client.cache_ttl_seconds
    )
    cache_results = [
        result
        for result in local_results
        if result['score'] >= client.cache_score_threshold
    ]

    if cache_results:
        return cache_results[:max_results]

    foreign_results = client._search_tavily(query, max_foreign, **kwargs)
    results = client._project_foreign_results(foreign_results)

    if len(results) == 0:
        return []

    client._save_foreign_results(
        foreign_results,
        save_foreign,
        max_foreign,
        query,
        cache_hit=False
    )
    return results[:max_results]


def search_oracle_cache_then_memory(client, query, query_embeddings, max_results,
                                    max_local, max_foreign, save_foreign,
                                    **kwargs):
    cache_scopes = None
    if client.enable_oracle_memory_metadata:
        cache_scopes = ("cache_only", "cache_plus_memory")

    local_results = client.database_provider.search_provider(
        client,
        query_embeddings,
        max_local,
        query=query,
        cache_ttl_seconds=client.cache_ttl_seconds,
        memory_scopes=cache_scopes
    )
    cache_results = [
        result
        for result in local_results
        if result['score'] >= client.cache_score_threshold
    ]

    if cache_results:
        return cache_results[:max_results]

    memory_max_results = client.memory_max_results or max_local
    memory_scopes = None
    if client.enable_oracle_memory_metadata:
        memory_scopes = ("cache_plus_memory",)

    memory_results = client.database_provider.search_provider(
        client,
        query_embeddings,
        memory_max_results,
        query=query,
        memory_scopes=memory_scopes
    )
    memory_hits = [
        result
        for result in memory_results
        if result['score'] >= client.memory_score_threshold
    ]

    if memory_hits:
        return memory_hits[:max_results]

    foreign_results = client._search_tavily(query, max_foreign, **kwargs)
    results = client._project_foreign_results(foreign_results)

    if len(results) == 0:
        return []

    client._save_foreign_results(
        foreign_results,
        save_foreign,
        max_foreign,
        query,
        cache_hit=False
    )
    return results[:max_results]
