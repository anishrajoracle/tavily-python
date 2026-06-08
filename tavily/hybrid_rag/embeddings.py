try:
    import cohere
except ImportError:
    cohere = None

co = None


def get_cohere_client():
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


def cohere_embed(texts, input_type):
    client = get_cohere_client()
    return client.embed(
        model="embed-english-v3.0",
        texts=texts,
        input_type=input_type
    ).embeddings


def cohere_rerank(query, documents, top_n):
    client = get_cohere_client()
    response = client.rerank(
        model="rerank-english-v3.0",
        query=query,
        documents=[doc["content"] for doc in documents],
        top_n=top_n
    )

    return [
        documents[result.index] | {"score": result.relevance_score}
        for result in response.results
    ]
