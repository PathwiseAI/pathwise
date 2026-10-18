"""FalkorDB graph store — connection, ingestion, and query operations.

This is the authoritative source of dependency relationships.
All investigation and verification queries go through this module.
"""

from __future__ import annotations

import logging
from typing import Any

from falkordb import FalkorDB

from app.config import get_settings
from app.errors import DatabaseConnectionError, FunctionNotFoundError
from app.parser import ParseResult, ParsedFunction, ParsedCall

logger = logging.getLogger(__name__)

GRAPH_NAME_PREFIX = "pathwise_"


def _graph_name(repo_id: str) -> str:
    """Return the FalkorDB graph name for a given repository."""
    return f"{GRAPH_NAME_PREFIX}{repo_id}"


class GraphStore:
    """Manages FalkorDB connections and graph operations."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        password: str | None = None,
    ):
        settings = get_settings()
        self._host = host or settings.falkordb_host
        self._port = port or settings.falkordb_port
        self._password = password or settings.falkordb_password or None
        self._db: FalkorDB | None = None

    # ── Connection management ──────────────────────────────────────────────

    def _connect(self) -> FalkorDB:
        """Establish a connection to FalkorDB."""
        try:
            db = FalkorDB(
                host=self._host,
                port=self._port,
                password=self._password,
            )
            return db
        except Exception as e:
            raise DatabaseConnectionError(f"Cannot connect to FalkorDB: {e}") from e

    @property
    def db(self) -> FalkorDB:
        """Return the FalkorDB connection, creating it if needed."""
        if self._db is None:
            self._db = self._connect()
        return self._db

    def _graph(self, repo_id: str):
        """Get the graph handle for a repository."""
        return self.db.select_graph(_graph_name(repo_id))

    def health_check(self) -> bool:
        """Check if FalkorDB is reachable."""
        try:
            self.db.list_graphs()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    # ── Ingestion ──────────────────────────────────────────────────────────

    def ingest(self, parse_result: ParseResult) -> dict[str, int]:
        """Ingest parsed repository data into FalkorDB.

        Performs idempotent upsert: clears existing data for the repo and
        re-creates all nodes and relationships.

        Returns:
            Dict with counts of created nodes and relationships.
        """
        repo_id = parse_result.repository_id
        graph = self._graph(repo_id)

        # Clear existing data for idempotent re-indexing
        try:
            graph.query("MATCH (n) DETACH DELETE n")
        except Exception:
            pass  # Graph may not exist yet

        counts = {"files": 0, "functions": 0, "calls": 0}

        # Create Repository node
        graph.query(
            "CREATE (:Repository {repo_id: $repo_id, path: $path})",
            params={"repo_id": repo_id, "path": parse_result.root_path},
        )

        # Create File nodes and CONTAINS relationships
        seen_files: set[str] = set()
        for f in parse_result.files:
            if f.file_path in seen_files:
                continue
            seen_files.add(f.file_path)
            graph.query(
                """
                MATCH (r:Repository {repo_id: $repo_id})
                CREATE (f:File {file_path: $file_path, repo_id: $repo_id})
                CREATE (r)-[:CONTAINS]->(f)
                """,
                params={"repo_id": repo_id, "file_path": f.file_path},
            )
            counts["files"] += 1

        # Create Function nodes and CONTAINS relationships
        for func in parse_result.functions:
            graph.query(
                """
                MATCH (f:File {file_path: $file_path, repo_id: $repo_id})
                CREATE (fn:Function {
                    function_id: $function_id,
                    name: $name,
                    qualified_name: $qualified_name,
                    file_path: $file_path,
                    start_line: $start_line,
                    end_line: $end_line,
                    is_method: $is_method,
                    is_async: $is_async,
                    repo_id: $repo_id
                })
                CREATE (f)-[:CONTAINS]->(fn)
                """,
                params={
                    "function_id": func.function_id,
                    "name": func.name,
                    "qualified_name": func.qualified_name,
                    "file_path": func.file_path,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                    "is_method": func.is_method,
                    "is_async": func.is_async,
                    "repo_id": repo_id,
                },
            )
            counts["functions"] += 1

        # Create CALLS relationships
        for call in parse_result.calls:
            graph.query(
                """
                MATCH (caller:Function {function_id: $caller_id})
                MATCH (callee:Function {function_id: $callee_id})
                CREATE (caller)-[:CALLS {call_line: $call_line}]->(callee)
                """,
                params={
                    "caller_id": call.caller_id,
                    "callee_id": call.callee_id,
                    "call_line": call.call_line or 0,
                },
            )
            counts["calls"] += 1

        logger.info(
            "Ingested repo %s: %d files, %d functions, %d calls",
            repo_id, counts["files"], counts["functions"], counts["calls"],
        )
        return counts

    # ── Query Operations ───────────────────────────────────────────────────

    def get_function(self, repo_id: str, function_id: str) -> dict[str, Any] | None:
        """Look up a single function by its ID."""
        graph = self._graph(repo_id)
        try:
            result = graph.query(
                """
                MATCH (fn:Function {function_id: $fid, repo_id: $repo_id})
                RETURN fn.function_id AS function_id,
                       fn.name AS name,
                       fn.qualified_name AS qualified_name,
                       fn.file_path AS file_path,
                       fn.start_line AS start_line,
                       fn.end_line AS end_line,
                       fn.is_method AS is_method,
                       fn.is_async AS is_async
                """,
                params={"fid": function_id, "repo_id": repo_id},
            )
            if result.result_set:
                row = result.result_set[0]
                return {
                    "function_id": row[0],
                    "name": row[1],
                    "qualified_name": row[2],
                    "file_path": row[3],
                    "start_line": row[4],
                    "end_line": row[5],
                    "is_method": row[6],
                    "is_async": row[7],
                }
        except Exception as e:
            logger.warning("get_function query failed: %s", e)
        return None

    def find_functions_by_name(self, repo_id: str, name: str) -> list[dict[str, Any]]:
        """Find functions by name (may return multiple for disambiguation)."""
        graph = self._graph(repo_id)
        try:
            result = graph.query(
                """
                MATCH (fn:Function {repo_id: $repo_id})
                WHERE fn.name = $name OR fn.qualified_name = $name
                RETURN fn.function_id AS function_id,
                       fn.name AS name,
                       fn.qualified_name AS qualified_name,
                       fn.file_path AS file_path,
                       fn.start_line AS start_line,
                       fn.end_line AS end_line
                """,
                params={"repo_id": repo_id, "name": name},
            )
            return [
                {
                    "function_id": row[0],
                    "name": row[1],
                    "qualified_name": row[2],
                    "file_path": row[3],
                    "start_line": row[4],
                    "end_line": row[5],
                }
                for row in result.result_set
            ]
        except Exception as e:
            logger.warning("find_functions_by_name query failed: %s", e)
            return []

    def list_functions(self, repo_id: str) -> list[dict[str, Any]]:
        """List all functions in a repository."""
        graph = self._graph(repo_id)
        try:
            result = graph.query(
                """
                MATCH (fn:Function {repo_id: $repo_id})
                RETURN fn.function_id, fn.name, fn.qualified_name,
                       fn.file_path, fn.start_line, fn.end_line,
                       fn.is_method, fn.is_async
                ORDER BY fn.file_path, fn.start_line
                """,
                params={"repo_id": repo_id},
            )
            return [
                {
                    "function_id": row[0],
                    "name": row[1],
                    "qualified_name": row[2],
                    "file_path": row[3],
                    "start_line": row[4],
                    "end_line": row[5],
                    "is_method": row[6],
                    "is_async": row[7],
                }
                for row in result.result_set
            ]
        except Exception as e:
            logger.warning("list_functions query failed: %s", e)
            return []

    def get_direct_callers(self, repo_id: str, function_id: str) -> list[dict[str, Any]]:
        """Find all functions that directly call the given function.

        Cypher: MATCH (caller)-[:CALLS]->(target) WHERE target.function_id = $fid
        """
        graph = self._graph(repo_id)
        result = graph.query(
            """
            MATCH (caller:Function)-[c:CALLS]->(target:Function {function_id: $fid, repo_id: $repo_id})
            RETURN caller.function_id, caller.name, caller.qualified_name,
                   caller.file_path, caller.start_line, c.call_line
            """,
            params={"fid": function_id, "repo_id": repo_id},
        )
        return [
            {
                "function_id": row[0],
                "name": row[1],
                "qualified_name": row[2],
                "file_path": row[3],
                "start_line": row[4],
                "call_line": row[5],
            }
            for row in result.result_set
        ]

    def get_direct_callees(self, repo_id: str, function_id: str) -> list[dict[str, Any]]:
        """Find all functions directly called by the given function.

        Cypher: MATCH (source)-[:CALLS]->(callee) WHERE source.function_id = $fid
        """
        graph = self._graph(repo_id)
        result = graph.query(
            """
            MATCH (source:Function {function_id: $fid, repo_id: $repo_id})-[c:CALLS]->(callee:Function)
            RETURN callee.function_id, callee.name, callee.qualified_name,
                   callee.file_path, callee.start_line, c.call_line
            """,
            params={"fid": function_id, "repo_id": repo_id},
        )
        return [
            {
                "function_id": row[0],
                "name": row[1],
                "qualified_name": row[2],
                "file_path": row[3],
                "start_line": row[4],
                "call_line": row[5],
            }
            for row in result.result_set
        ]

    def get_multi_hop_callers(
        self, repo_id: str, function_id: str, max_depth: int = 5,
    ) -> list[list[dict[str, Any]]]:
        """Bounded multi-hop caller traversal using variable-length paths.

        Returns all paths leading TO the given function, up to max_depth hops.
        Each path is a list of function dicts from root caller to target.

        Cypher: MATCH path = (root)-[:CALLS*1..N]->(target)
        """
        graph = self._graph(repo_id)
        depth = min(max_depth, 10)  # hard cap
        result = graph.query(
            f"""
            MATCH path = (root:Function)-[:CALLS*1..{depth}]->(target:Function {{function_id: $fid, repo_id: $repo_id}})
            WHERE root.repo_id = $repo_id
            RETURN [n IN nodes(path) | [n.function_id, n.name, n.qualified_name, n.file_path, n.start_line]]
            """,
            params={"fid": function_id, "repo_id": repo_id},
        )
        paths = []
        for row in result.result_set:
            node_list = row[0]
            path = [
                {
                    "function_id": n[0],
                    "name": n[1],
                    "qualified_name": n[2],
                    "file_path": n[3],
                    "start_line": n[4],
                }
                for n in node_list
            ]
            paths.append(path)
        return paths

    def get_call_chain(
        self, repo_id: str, source_id: str, target_id: str, max_depth: int = 5,
    ) -> list[list[dict[str, Any]]]:
        """Find call paths from source to target function.

        Uses bounded variable-length path matching.

        Cypher: MATCH path = (src)-[:CALLS*1..N]->(dst)
        """
        graph = self._graph(repo_id)
        depth = min(max_depth, 10)
        result = graph.query(
            f"""
            MATCH path = (src:Function {{function_id: $src_id, repo_id: $repo_id}})-[:CALLS*1..{depth}]->(dst:Function {{function_id: $dst_id, repo_id: $repo_id}})
            RETURN [n IN nodes(path) | [n.function_id, n.name, n.qualified_name, n.file_path, n.start_line]]
            """,
            params={"src_id": source_id, "dst_id": target_id, "repo_id": repo_id},
        )
        paths = []
        for row in result.result_set:
            node_list = row[0]
            path = [
                {
                    "function_id": n[0],
                    "name": n[1],
                    "qualified_name": n[2],
                    "file_path": n[3],
                    "start_line": n[4],
                }
                for n in node_list
            ]
            paths.append(path)
        return paths

    def get_impact(
        self, repo_id: str, function_id: str, max_depth: int = 5,
    ) -> list[list[dict[str, Any]]]:
        """Find all functions that could be impacted by changes to the given function.

        Traverses callers (upstream) to find what depends on this function.

        Cypher: MATCH path = (root)-[:CALLS*1..N]->(target)
        """
        return self.get_multi_hop_callers(repo_id, function_id, max_depth)

    def edge_exists(self, repo_id: str, caller_id: str, callee_id: str) -> bool:
        """Check if a direct CALLS relationship exists between two functions."""
        graph = self._graph(repo_id)
        result = graph.query(
            """
            MATCH (a:Function {function_id: $caller_id, repo_id: $repo_id})
                  -[:CALLS]->
                  (b:Function {function_id: $callee_id, repo_id: $repo_id})
            RETURN count(*) AS cnt
            """,
            params={"caller_id": caller_id, "callee_id": callee_id, "repo_id": repo_id},
        )
        return result.result_set[0][0] > 0

    def node_exists(self, repo_id: str, function_id: str) -> bool:
        """Check if a function node exists in the graph."""
        graph = self._graph(repo_id)
        result = graph.query(
            """
            MATCH (fn:Function {function_id: $fid, repo_id: $repo_id})
            RETURN count(*) AS cnt
            """,
            params={"fid": function_id, "repo_id": repo_id},
        )
        return result.result_set[0][0] > 0

    def get_repository_info(self, repo_id: str) -> dict[str, Any] | None:
        """Get repository metadata from the graph."""
        graph = self._graph(repo_id)
        try:
            result = graph.query(
                """
                MATCH (r:Repository {repo_id: $repo_id})
                OPTIONAL MATCH (r)-[:CONTAINS]->(f:File)
                WITH r, count(f) AS file_count
                OPTIONAL MATCH (:File {repo_id: $repo_id})-[:CONTAINS]->(fn:Function)
                RETURN r.repo_id, r.path, file_count, count(fn)
                """,
                params={"repo_id": repo_id},
            )
            if result.result_set:
                row = result.result_set[0]
                return {
                    "repository_id": row[0],
                    "path": row[1],
                    "file_count": row[2],
                    "function_count": row[3],
                }
        except Exception:
            pass
        return None

    def list_repositories(self) -> list[dict[str, Any]]:
        """List all indexed repositories."""
        try:
            graph_names = self.db.list_graphs()
        except Exception as e:
            raise DatabaseConnectionError(f"Cannot list graphs: {e}") from e

        repos = []
        for name in graph_names:
            if not name.startswith(GRAPH_NAME_PREFIX):
                continue
            repo_id = name[len(GRAPH_NAME_PREFIX):]
            info = self.get_repository_info(repo_id)
            if info:
                repos.append(info)
        return repos
