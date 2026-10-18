# Pathwise Graph Model

## Overview

Pathwise models Python codebases as a labeled property graph in FalkorDB.
The graph captures three entity types (repositories, files, functions) and
three relationship types (containment and call dependencies).

## Node Labels

### Repository
Represents an indexed Python repository.

| Property  | Type   | Description                        |
|-----------|--------|------------------------------------|
| `repo_id` | String | 12-char deterministic hash of path |
| `path`    | String | Absolute filesystem path           |

### File
Represents a discovered `.py` source file.

| Property    | Type   | Description                        |
|-------------|--------|------------------------------------|
| `file_path` | String | Relative path within the repository |
| `repo_id`   | String | Parent repository ID               |

### Function
Represents a discovered function, method, or async function.

| Property         | Type    | Description                                      |
|------------------|---------|--------------------------------------------------|
| `function_id`    | String  | Globally unique: `{repo_id}::{path}::{qname}`   |
| `name`           | String  | Simple function name                              |
| `qualified_name` | String  | Class-qualified name (e.g., `MyClass.method`)    |
| `file_path`      | String  | Relative file path                                |
| `start_line`     | Integer | First line of the function definition             |
| `end_line`       | Integer | Last line of the function definition              |
| `is_method`      | Boolean | True if defined inside a class                    |
| `is_async`       | Boolean | True if `async def`                               |
| `repo_id`        | String  | Parent repository ID                              |

## Relationship Types

### CONTAINS (Repository → File)
Links a repository to its discovered source files.

```
(:Repository {repo_id})-[:CONTAINS]->(:File {file_path, repo_id})
```

### CONTAINS (File → Function)
Links a file to the functions defined within it.

```
(:File {file_path, repo_id})-[:CONTAINS]->(:Function {function_id, repo_id})
```

### CALLS (Function → Function)
Represents a statically-resolved function call.

| Property    | Type    | Description              |
|-------------|---------|--------------------------|
| `call_line` | Integer | Line number of the call  |

```
(:Function {function_id})-[:CALLS {call_line}]->(:Function {function_id})
```

## Function ID Format

Function IDs follow the pattern:

```
{repo_id}::{relative/path.py}::{qualified_name}
```

Examples:
- `a1b2c3d4e5f6::service.py::process_order`
- `a1b2c3d4e5f6::calculator.py::Calculator.compute`
- `a1b2c3d4e5f6::nested.py::outer.inner`

This format prevents collisions between:
- Functions with the same name in different files
- Methods with the same name in different classes
- Nested functions with the same name at different scopes

## Repository Isolation

All nodes carry a `repo_id` property. Queries always filter by `repo_id`,
ensuring that functions from different repositories never interfere with
each other even when stored in the same FalkorDB instance.

## Idempotent Ingestion

Re-indexing a repository:
1. Deletes all existing nodes with the matching `repo_id`
2. Re-creates nodes and relationships from the fresh parse
3. Ensures no stale data persists from previous indexing runs

## Sample Graph (from sample_repo/)

```
handle_request ──CALLS──> validate_input
handle_request ──CALLS──> process_order
handle_status_request ──CALLS──> get_order_status
process_order ──CALLS──> compute_total
process_order ──CALLS──> apply_discount
process_order ──CALLS──> save_order
compute_total ──CALLS──> get_unit_price
save_order ──CALLS──> generate_id
get_order_status ──CALLS──> load_order
```

Isolated functions (no CALLS edges): `format_currency`, `sanitize_string`
