def validate_index(client):
    """
    Check that the configured MongoDB Atlas Search index is a cosine vector index.

    Raises:
        ValueError: If the index does not exist, is not a vectorSearch index, or
                    does not expose the configured embedding vector field.
    """
    if not hasattr(client.collection, "list_search_indexes"):
        raise ValueError("MongoDB collection must provide list_search_indexes().")

    index_exists = False
    for index in client.collection.list_search_indexes():
        if index.get("name") != client.index:
            continue

        if index.get("type") != "vectorSearch":
            raise ValueError(f"Index '{client.index}' exists but is not of type "
                             "'vectorSearch'.")

        field_exists = False
        fields = index.get("latestDefinition", {}).get("fields", [])
        for field in fields:
            if field.get("path") != client.embeddings_field:
                continue

            if field.get("type") != "vector":
                raise ValueError(f"Field '{client.embeddings_field}' exists "
                                 "but is not of type 'vector'.")
            elif field.get("similarity") != "cosine":
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


def search(collection, index, embeddings_field, content_field, query_embeddings, max_local):
    return list(collection.aggregate([
        {
            "$vectorSearch": {
                "index": index,
                "path": embeddings_field,
                "queryVector": query_embeddings,
                "numCandidates": max_local + 3,
                "limit": max_local
            }
        },
        {
            "$project": {
                "_id": 0,
                "content": f"${content_field}",
                "score": {
                    "$meta": "vectorSearchScore"
                },
                "origin": "local"
            }
        }
    ]))


def insert_documents(collection, documents):
    collection.insert_many(documents)
