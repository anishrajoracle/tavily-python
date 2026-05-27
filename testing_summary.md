# Testing Summary

## Date

May 26, 2026

## Environment

- Repository: `tavily-python`
- Working directory: your local `tavily-python` project directory
- Python environment: `.venv`
- Oracle container used for manual integration testing: `oracle-23ai-free`
- Oracle service used: `localhost:1521/FREEPDB1`

## Targeted Oracle and Safety Tests

Command:

```bash
.venv/bin/python -m pytest tests/test_errors.py tests/test_hybrid_rag_oracle.py tests/test_hybrid_rag_safety.py
```

Result:

```text
9 passed in 0.06s
```

Summary:

| Test group | Passed | Failed | Notes |
| --- | ---: | ---: | --- |
| Error handling tests | 3 | 0 | Verified missing-key and invalid-key behavior without depending on a live network call. |
| Oracle hybrid RAG tests | 4 | 0 | Verified Oracle search SQL, Oracle insert behavior, Oracle `save_foreign=True`, and Oracle identifier validation. |
| Hybrid RAG safety tests | 2 | 0 | Verified empty save handling and callable validation. |
| Total | 9 | 0 | All targeted error, Oracle, and safety tests passed. |

## Full Test Suite

Command:

```bash
.venv/bin/python -m pytest
```

Result:

```text
80 passed in 0.49s
```

Summary:

| Test suite | Passed | Failed |
| --- | ---: | ---: |
| Full pytest suite | 80 | 0 |

## Previously Failing Test

```text
tests/test_errors.py::test_invalid_api_key
```

Previous failure reason:

The test expected an `InvalidAPIKeyError`, but it made a live request and failed earlier because the configured proxy host could not be resolved:

```text
requests.exceptions.ProxyError:
HTTPSConnectionPool(host='api.tavily.com', port=443): Max retries exceeded with url: /search
Caused by ProxyError:
Failed to resolve 'www-proxy.us.oracle.com'
```

Fix:

The test now uses the repository's request interceptor to return a deterministic fake `401` response for both the synchronous and asynchronous clients. This keeps the test focused on SDK error handling and removes dependence on proxy/DNS availability.

Result after fix:

```text
tests/test_errors.py::test_invalid_api_key passed
```

## Manual Oracle Integration Test

Manual live Oracle testing was also completed against the local Oracle container.

Result:

```text
dropped old test user
created test user
created vector table
inserted test vectors
results:
local 1.0 Oracle Database vector search is working
local 0.0 MongoDB Atlas vector search existing path
row_count= 2
```

What this verified:

- The Python Oracle driver can connect to the local Oracle container.
- `TavilyHybridClient(db_provider="oracle")` can be constructed with a real Oracle connection.
- Oracle vector rows can be inserted through the Oracle insert path.
- Oracle vector search runs through the client search path.
- Local Oracle search results are returned with `origin="local"`.

## Manual Tavily + Oracle Test

A manual test was also run with a real `TAVILY_API_KEY`.

Observed output:

```text
local 1.0 Oracle Database vector search is working
local 0.0 MongoDB Atlas vector search existing path
foreign 0.86108357 The Oracle Database update 23.4.0, which features vector search capabilities...
foreign 0.8335554 Oracle unveiled plans to add vector search capabilities in September 2023...
foreign 0.7598145 NEW VECTOR data type for storing vector embeddings...
```

What this verified:

- Oracle local results were returned from the database.
- Tavily foreign results were returned from the Tavily API.
- The hybrid result path can combine Oracle local results and Tavily foreign results.
- With `save_foreign=True`, the Tavily results are passed through the Oracle save path.

## Repeatable Smoke Test Script

A repo-level smoke test script was added so the manual Tavily + Oracle flow can be run without pasting a temporary heredoc into the terminal.

File:

```text
examples/hybrid_rag_oracle_smoke_test.py
```

Run from your local `tavily-python` project directory:

```bash
export TAVILY_API_KEY="your-real-key"
.venv/bin/python examples/hybrid_rag_oracle_smoke_test.py
```

The script:

- Connects to Oracle.
- Creates a small vector table if needed.
- Seeds local Oracle rows if the table is empty.
- Runs `TavilyHybridClient(db_provider="oracle")`.
- Fetches Tavily foreign results.
- Saves Tavily foreign results into Oracle with `save_foreign=True`.
- Prints local/foreign results and `row_count`.

## Final Status

| Area | Status |
| --- | --- |
| Targeted Oracle/safety unit tests | Passed |
| Manual Oracle integration test | Passed |
| Manual Tavily + Oracle hybrid test | Passed |
| Full pytest suite | 80 passed, 0 failed |
| Previous full-suite failure | Fixed by replacing live invalid-key request with an intercepted `401` response |
