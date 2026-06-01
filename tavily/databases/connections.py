def connect_mongodb(mongo_uri, mongo_database, mongo_collection, mongo_client_kwargs=None):
    if not mongo_uri or not mongo_database or not mongo_collection:
        raise ValueError(
            "mongo_uri, mongo_database, and mongo_collection are required "
            "when collection is not provided."
        )

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise ImportError(
            "The MongoDB convenience connection parameters require the "
            "'pymongo' package. Install it with the mongodb extra or pass "
            "an existing collection object."
        ) from exc

    client = MongoClient(mongo_uri, **(mongo_client_kwargs or {}))
    return client, client[mongo_database][mongo_collection]


def connect_oracle(oracle_user, oracle_password, oracle_dsn, oracle_connection_kwargs=None):
    if not oracle_user or not oracle_password or not oracle_dsn:
        raise ValueError(
            "oracle_user, oracle_password, and oracle_dsn are required "
            "when connection is not provided."
        )

    try:
        import oracledb
    except ImportError as exc:
        raise ImportError(
            "The Oracle convenience connection parameters require the "
            "'oracledb' package. Install it with the oracle extra or pass "
            "an existing connection object."
        ) from exc

    connection_kwargs = {
        "user": oracle_user,
        "password": oracle_password,
        "dsn": oracle_dsn,
    }
    connection_kwargs.update(oracle_connection_kwargs or {})
    return oracledb.connect(**connection_kwargs)
