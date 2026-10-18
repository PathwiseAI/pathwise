# Pathwise Cypher Queries

All queries use **parameterized Cypher** (parameter syntax: `$param`).
No user input is interpolated into query strings.

## Graph Ingestion

### Create Repository Node
```cypher
MERGE (r:Repository {repo_id: $repo_id})
SET r.path = $path
```

### Create File Node
```cypher
MERGE (f:File {file_path: $file_path, repo_id: $repo_id})
```

### Create Function Node
```cypher
MERGE (f:Function {function_id: $fid, repo_id: $repo_id})
SET f.name = $name,
    f.qualified_name = $qname,
    f.file_path = $file_path,
    f.start_line = $start_line,
    f.end_line = $end_line,
    f.is_method = $is_method,
    f.is_async = $is_async
```

### Create CALLS Relationship
```cypher
MATCH (caller:Function {function_id: $caller_id, repo_id: $repo_id})
MATCH (callee:Function {function_id: $callee_id, repo_id: $repo_id})
MERGE (caller)-[c:CALLS]->(callee)
SET c.call_line = $call_line
```

### Create CONTAINS Relationships
```cypher
MATCH (r:Repository {repo_id: $repo_id})
MATCH (f:File {file_path: $file_path, repo_id: $repo_id})
MERGE (r)-[:CONTAINS]->(f)

MATCH (f:File {file_path: $file_path, repo_id: $repo_id})
MATCH (fn:Function {function_id: $fid, repo_id: $repo_id})
MERGE (f)-[:CONTAINS]->(fn)
```

## Investigation Queries

### Direct Callers
Find all functions that directly call a target function.
```cypher
MATCH (caller:Function)-[c:CALLS]->(target:Function {function_id: $fid, repo_id: $repo_id})
RETURN caller.function_id, caller.name, caller.qualified_name,
       caller.file_path, caller.start_line, c.call_line
```

### Direct Callees
Find all functions that a source function directly calls.
```cypher
MATCH (source:Function {function_id: $fid, repo_id: $repo_id})-[c:CALLS]->(callee:Function)
RETURN callee.function_id, callee.name, callee.qualified_name,
       callee.file_path, callee.start_line, c.call_line
```

### Multi-Hop Caller Traversal
Find all functions that transitively call a target (up to N hops).
```cypher
MATCH path = (root:Function)-[:CALLS*1..5]->(target:Function {function_id: $fid, repo_id: $repo_id})
WHERE root.repo_id = $repo_id
RETURN [n IN nodes(path) | [n.function_id, n.name, n.qualified_name, n.file_path, n.start_line]]
```

### Call Chain Between Two Functions
Find paths from a source to a destination function.
```cypher
MATCH path = (src:Function {function_id: $src_id, repo_id: $repo_id})
             -[:CALLS*1..5]->
             (dst:Function {function_id: $dst_id, repo_id: $repo_id})
RETURN [n IN nodes(path) | [n.function_id, n.name, n.qualified_name, n.file_path, n.start_line]]
```

## Verification Queries

### Node Existence
Check if a function exists in the graph for a given repository.
```cypher
MATCH (f:Function {function_id: $fid, repo_id: $repo_id})
RETURN count(f) AS cnt
```

### Edge Existence
Check if a direct CALLS relationship exists.
```cypher
MATCH (a:Function {function_id: $caller_id, repo_id: $repo_id})
      -[:CALLS]->
      (b:Function {function_id: $callee_id, repo_id: $repo_id})
RETURN count(*) AS cnt
```

## Administrative Queries

### List Repositories
```cypher
MATCH (r:Repository) RETURN r.repo_id, r.path
```

### List Functions in a Repository
```cypher
MATCH (f:Function {repo_id: $repo_id})
RETURN f.function_id, f.name, f.qualified_name,
       f.file_path, f.start_line, f.end_line
ORDER BY f.file_path, f.start_line
```

### Delete Repository Data (for re-indexing)
```cypher
MATCH (n {repo_id: $repo_id}) DETACH DELETE n
```
