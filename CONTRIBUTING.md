# Contributing Guide

Thank you for improving the Tavily Python SDK. This repository includes the core Tavily clients plus an Oracle-enabled hybrid RAG path, so backward compatibility is the first rule for contributions.

## Compatibility Expectations

Do not remove, rename, or change existing public APIs, imports, examples, or workflows without an explicit compatibility plan. In particular, preserve the existing behavior for:

- `TavilyClient`
- `AsyncTavilyClient`
- `TavilyHybridClient`
- MongoDB hybrid RAG
- Oracle hybrid search
- Oracle freshness cache
- Oracle persistence
- Oracle JSON/provenance options
- Oracle semantic deduplication
- Tavily API request behavior
- Existing examples and notebooks

When a requirement can be satisfied through documentation, prefer documentation over code changes.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[oracle,mongodb]" pytest
```

Optional quality tools:

```bash
python -m pip install ruff mypy
```

The default hybrid RAG embedding and reranking helpers require Cohere unless you pass custom `embedding_function` and `ranking_function` callables.

## Running Tests

Run the full test suite:

```bash
python -m pytest
```

Run targeted Oracle and hybrid RAG tests:

```bash
python -m pytest tests/test_hybrid_rag_oracle.py tests/test_hybrid_rag_safety.py
```

Run the configured quality tools:

```bash
ruff check .
mypy
```

The Ruff and Mypy configurations are intentionally conservative so contributors can get useful signal without needing large refactors.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `tavily/tavily.py` | Synchronous Tavily API client. |
| `tavily/async_tavily.py` | Asynchronous Tavily API client. |
| `tavily/hybrid_rag/hybrid_rag.py` | MongoDB and Oracle hybrid RAG implementation. |
| `tavily/errors.py` | SDK error classes. |
| `tavily/utils.py` | Shared token/context helpers. |
| `examples/` | User-facing examples and Oracle smoke test scripts. |
| `tests/` | Unit and regression tests. |
| `docs/` | Architecture and audit-visibility documentation. |

## Coding Standards

- Prefer small, additive changes.
- Preserve result shapes and request payload behavior.
- Reuse existing helpers instead of duplicating Tavily, Oracle, cache, persistence, or ranking logic.
- Keep optional features opt-in.
- Validate user-controlled Oracle identifiers before placing them in SQL.
- Keep tests deterministic by using mocks/interceptors for Tavily network behavior.
- Add focused tests when behavior changes or when a bug fix needs a regression guard.
- Avoid broad formatting-only changes in unrelated files.

## Pull Request Process

Before opening a pull request:

1. Run `python -m pytest`.
2. Run `ruff check .` if Ruff is installed.
3. Run `mypy` if Mypy is installed.
4. Update README or supporting docs when behavior, setup, or workflows become easier to understand with documentation.
5. Note any manual Oracle validation performed, including Oracle version, DSN pattern, and enabled feature flags.

Pull requests should include:

- A concise description of the user-facing change.
- Compatibility notes.
- Test evidence.
- Documentation updates when relevant.
- Any known follow-up work.
