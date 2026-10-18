# Pathwise Limitations

## Language Support

- **Python only.** The parser uses Python's `ast` module and cannot analyze
  other languages. Mixed-language projects will have incomplete graphs.

## Static Analysis Boundaries

The parser performs conservative static analysis. It will **not** resolve:

| Pattern | Example | Why |
|---------|---------|-----|
| Dynamic dispatch | `getattr(obj, name)()` | Target unknown at parse time |
| Monkey-patching | `module.func = other_func` | Requires runtime tracking |
| Decorators that replace functions | `@lru_cache` wrapping | Returns wrapper, not original |
| Higher-order calls | `map(func, items)` | `func` is a variable, not a call |
| `eval` / `exec` | `exec("func()")` | Arbitrary runtime code |
| String-based imports | `importlib.import_module(name)` | Target is a runtime string |
| Conditional imports | `if sys.platform: import X` | Branch not evaluated |
| Star imports | `from module import *` | Namespace pollution, ambiguous |
| Third-party library calls | `requests.get()` | External code not indexed |
| C extensions | `numpy.array()` | No Python source to parse |

**Design choice:** It is better to report a call as "unresolved" than to
guess incorrectly. Unresolved calls are logged in indexing warnings.

## Graph Completeness

- The graph only contains functions discovered by static analysis.
  Dynamically generated functions, lambdas used as callbacks, and functions
  defined in non-`.py` files are not represented.
- Re-indexing replaces the previous graph entirely. There is no incremental
  update or diff-based re-index.

## Proof Mode Scope

Proof Mode verifies that the **graph** supports a claim. It does **not** verify:

| What it can prove | What it cannot prove |
|---|---|
| A CALLS edge exists in the graph | The call will execute at runtime |
| A multi-hop path exists | The path is reachable under all conditions |
| Both functions are indexed | The graph is complete |
| No relationship exists between two indexed functions | That no relationship exists in the actual code (unresolved calls may be missing) |

An `UNSUPPORTED` result means "the graph does not contain this relationship,"
not "the relationship is impossible in the code."

An `INCONCLUSIVE` result means "the system cannot safely decide" — typically
because a function was not found in the graph.

## Natural Language Understanding

- Intent detection is regex-based, not LLM-powered (in deterministic mode).
- Only 5 question patterns are recognized: callers, callees, impact, path, verify.
- Questions that don't match any pattern receive a generic response.
- Function names must appear in the question for resolution.

## Scale

- Tested with repositories up to ~1000 files. Very large repositories may
  experience slower indexing or memory pressure.
- Multi-hop traversal is bounded to 5 hops. Deeper chains are not discovered.
- No pagination on function lists or investigation results.

## Deployment

- Single-user, single-machine. No authentication or multi-tenant isolation.
- No persistent storage beyond FalkorDB. If the database is cleared,
  re-indexing is required.
- No TLS on the API server. Intended for localhost only.

## Platform Notes

- **Windows:** Path case normalization uses `Path.resolve()`. Console output
  requires `PYTHONIOENCODING=utf-8` for Unicode characters in some terminals.
- **Docker:** FalkorDB runs in Docker. Docker Desktop must be running.
