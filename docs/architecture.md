# Pathwise Architecture

## Overview

Pathwise is structured as a modular Python application with clear separation between
parsing, storage, investigation, verification, and HTTP layers.

```
┌──────────────┐     ┌───────────┐     ┌──────────────┐
│  Python Repo │────>│  Parser   │────>│  Graph Store  │
│  (.py files) │     │  (AST)    │     │  (FalkorDB)   │
└──────────────┘     └───────────┘     └──────┬────────┘
                                              │
                     ┌───────────┐     ┌──────▼────────┐
                     │  Verifier │<────│  Investigator │
                     │(Proof Mode)│    │(Query Engine) │
                     └─────┬─────┘     └──────┬────────┘
                           │                  │
                     ┌─────▼──────────────────▼──────┐
                     │        FastAPI Server          │
                     │   /health /investigate /verify │
                     └────────────────────────────────┘
```

## Module Responsibilities

### `app/config.py`
Validated configuration using pydantic-settings. Reads from environment variables
and `.env` files. Provides a cached `get_settings()` singleton.

### `app/schemas.py`
All Pydantic request/response models. Defines the `VerificationStatus` enum
(`SUPPORTED`, `UNSUPPORTED`, `INCONCLUSIVE`), `Claim`, `ProofRecord`,
`InvestigationResult`, `IndexSummary`, and API request bodies.

### `app/parser.py`
Static Python source analysis using the `ast` module. Key capabilities:
- Recursive `.py` file discovery (excludes `.git`, `venv`, `__pycache__`, etc.)
- Function discovery: module-level, class methods, nested, async
- Call resolution: same-file, import-resolved, unique bare name across repo
- Produces `ParseResult` with typed `FileInfo`, `FunctionInfo`, `CallInfo`, `UnresolvedCall`
- Never imports or executes analyzed code

### `app/graph_store.py`
FalkorDB connection management and all graph operations:
- `ingest()` — Idempotent graph creation from `ParseResult`
- `get_direct_callers()` / `get_direct_callees()` — 1-hop queries
- `get_multi_hop_callers()` — Variable-length path traversal (`[:CALLS*1..N]`)
- `get_call_chain()` — Path finding between two functions
- `node_exists()` / `edge_exists()` — Verification primitives
- All queries use parameterized Cypher

### `app/repository_service.py`
Orchestrates indexing: path validation (allowed-root enforcement, symlink safety),
parser invocation, graph ingestion, and summary reporting.

### `app/investigator.py`
Deterministic question interpretation using regex-based intent detection.
Five supported intents: `find_callers`, `find_callees`, `find_impact`,
`find_path`, `verify_relationship`. Resolves function names to graph IDs,
executes appropriate Cypher queries, and constructs evidence-backed answers.

### `app/verifier.py`
Independent Proof Mode verification. Re-queries FalkorDB to validate claims.
Supports `CALLS` (direct edge + fallback indirect path check) and `CALLS_CHAIN`
(validates each edge in a claimed path) predicates.

### `app/main.py`
FastAPI application with endpoints:
- `GET /health` — Health check with FalkorDB connectivity status
- `POST /api/repositories/index` — Index a repository
- `GET /api/repositories` — List indexed repositories
- `GET /api/repositories/{id}/functions` — List functions in a repository
- `POST /api/investigate` — Natural-language investigation
- `POST /api/verify` — Proof Mode claim verification

### `app/errors.py`
Custom exception hierarchy: `PathwiseError` base class with
`RepositoryNotFoundError`, `PathTraversalError`, `IndexingError`,
`DatabaseConnectionError`, `QueryError`, `InvestigationError`,
`VerificationError`.

## Design Principles

1. **FalkorDB is the source of truth** — All dependency answers come from graph queries
2. **No code execution** — Static analysis only via `ast.parse()`
3. **Conservative resolution** — Better to report "unresolved" than invent a wrong target
4. **Evidence-backed** — Every claim includes file paths, line numbers, and traversal details
5. **Independent verification** — Proof Mode re-queries the graph; never trusts cached results
6. **Deterministic fallback** — Works without an LLM API key
