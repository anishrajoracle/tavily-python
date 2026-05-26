import pytest
import os
import asyncio

import tavily.tavily as sync_tavily
import tavily.async_tavily as async_tavily
from tavily.errors import MissingAPIKeyError, InvalidAPIKeyError
from tests.request_intercept import clear_interceptor, intercept_requests

@pytest.fixture
def set_api_key():
    old_key = os.getenv("TAVILY_API_KEY")
    os.environ["TAVILY_API_KEY"] = "test_api_key"
    yield
    if old_key is not None:
        os.environ["TAVILY_API_KEY"] = old_key
    elif "TAVILY_API_KEY" in os.environ:
        del os.environ["TAVILY_API_KEY"]

@pytest.fixture
def clear_api_key():
    old_key = os.getenv("TAVILY_API_KEY")
    if old_key:
        del os.environ["TAVILY_API_KEY"]
    yield
    if old_key:
        os.environ["TAVILY_API_KEY"] = old_key

def test_load_key_from_env(set_api_key):
    sync_tavily.TavilyClient()
    async_tavily.AsyncTavilyClient()

    # No error should be raised

def test_missing_api_key(clear_api_key):
    with pytest.raises(MissingAPIKeyError):
        sync_tavily.TavilyClient(api_key='')

    with pytest.raises(MissingAPIKeyError):
        async_tavily.AsyncTavilyClient(api_key='')

    with pytest.raises(MissingAPIKeyError):
        sync_tavily.TavilyClient()

    with pytest.raises(MissingAPIKeyError):
        async_tavily.AsyncTavilyClient()

def test_invalid_api_key():
    sync_interceptor = intercept_requests(sync_tavily)
    async_interceptor = intercept_requests(async_tavily)
    sync_interceptor.set_response(
        401,
        json={"detail": {"error": "Invalid API key"}},
    )
    async_interceptor.set_response(
        401,
        json={"detail": {"error": "Invalid API key"}},
    )

    try:
        with pytest.raises(InvalidAPIKeyError):
            sync_tavily.TavilyClient(api_key="invalid_api_key").search("What is Tavily?")

        with pytest.raises(InvalidAPIKeyError):
            asyncio.run(async_tavily.AsyncTavilyClient(api_key="invalid_api_key").search("What is Tavily?"))
    finally:
        clear_interceptor(sync_tavily)
        clear_interceptor(async_tavily)
