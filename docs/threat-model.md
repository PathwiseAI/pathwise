# Pathwise Threat Model

## Scope

This document describes the security threats relevant to Pathwise when used as
a local development tool or hackathon demo. Pathwise is **not** designed for
internet-facing production deployment.

## Assets

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| Source code being analyzed | High | User's proprietary Python source files |
| FalkorDB graph data | Medium | Parsed function names, file paths, call relationships |
| Environment configuration | Medium | Database credentials, allowed paths |
| API server | Low | Local-only FastAPI instance |

## Threat Analysis

### T1: Code Execution via Analyzed Repository
**Risk:** HIGH → **Mitigated**

An attacker could craft a malicious `.py` file that executes code when analyzed.

**Mitigation:**
- Parser uses `ast.parse()` only — this parses syntax but never imports or executes code
- No `exec()`, `eval()`, `importlib.import_module()`, or `__import__()` calls on analyzed code
- Repository contents are treated as untrusted input

### T2: Path Traversal
**Risk:** HIGH → **Mitigated**

An attacker could submit a path like `../../../etc/passwd` to read files outside
the allowed repository root.

**Mitigation:**
- All repository paths are resolved with `Path.resolve()` and checked against `ALLOWED_ROOT`
- Symlinks that escape the repository root are rejected
- `PathTraversalError` is raised for violations

### T3: Cypher Injection
**Risk:** HIGH → **Mitigated**

An attacker could inject malicious Cypher through function names or questions.

**Mitigation:**
- All Cypher queries use parameterized queries (`$param` syntax)
- No string interpolation or concatenation of user input into query strings
- Users cannot execute raw Cypher queries through the API

### T4: Arbitrary Cypher Execution
**Risk:** MEDIUM → **Mitigated**

A user could attempt to run arbitrary graph queries via the API.

**Mitigation:**
- No endpoint accepts raw Cypher strings
- All queries are predefined in `graph_store.py`
- Investigation engine maps intents to fixed query templates

### T5: Denial of Service via Large Repositories
**Risk:** MEDIUM → **Mitigated**

A user could point Pathwise at a very large repository to exhaust resources.

**Mitigation:**
- Configurable `MAX_FILE_SIZE_KB` (default: 500 KB per file)
- Configurable `MAX_FILE_COUNT` (default: 1000 files)
- Configurable `MAX_REPO_SIZE_MB` (default: 50 MB)
- Multi-hop traversal bounded to 5 hops maximum
- Files exceeding limits are skipped with warnings

### T6: Secrets in Environment Variables
**Risk:** MEDIUM → **Partially mitigated**

Database passwords or API keys could leak through logs or error messages.

**Mitigation:**
- `.env` is in `.gitignore`
- `.env.example` contains placeholder values only
- Error messages do not include connection strings or passwords
- **Residual risk:** Secrets in environment variables could be exposed through
  process inspection on a shared system

### T7: Cross-Repository Data Leakage
**Risk:** LOW → **Mitigated**

Functions from one indexed repository could appear in queries for another.

**Mitigation:**
- All nodes carry a `repo_id` property
- All queries filter by `repo_id`
- Re-indexing deletes all previous data for that `repo_id`

### T8: No Authentication
**Risk:** LOW (local-only deployment)

The API has no authentication or authorization.

**Mitigation:**
- Pathwise is intended for local development use
- Server binds to `localhost` by default in development
- **Residual risk:** Any process on the same machine can call the API

## Out of Scope

- Network-level attacks (TLS, MITM) — local-only deployment
- Multi-tenant isolation — single-user tool
- Supply chain attacks on dependencies — standard Python packaging
- Physical access attacks
