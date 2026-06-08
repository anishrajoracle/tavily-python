from tavily.databases.mongodb import mongodb
from tavily.databases.oracledb import oracledb

PROVIDERS = {
    "mongodb": mongodb,
    "oracle": oracledb,
}


def get_provider(name):
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(
            "Supported database providers are 'mongodb' and 'oracle'."
        ) from exc


__all__ = ["get_provider", "mongodb", "oracledb"]
