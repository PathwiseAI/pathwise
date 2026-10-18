"""Repository indexing orchestration."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import get_settings
from app.errors import PathTraversalError, RepositoryNotFoundError, IndexingError
from app.parser import parse_repository, ParseResult
from app.graph_store import GraphStore
from app.schemas import IndexSummary

logger = logging.getLogger(__name__)


def validate_repo_path(path: str) -> Path:
    """Validate and resolve a repository path.

    Ensures the path exists, is a directory, and is within the allowed root.

    Raises:
        RepositoryNotFoundError: if the path doesn't exist or isn't a directory.
        PathTraversalError: if the path escapes the allowed root.
    """
    settings = get_settings()
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise RepositoryNotFoundError(f"Path does not exist: {path}")
    if not resolved.is_dir():
        raise RepositoryNotFoundError(f"Path is not a directory: {path}")

    allowed_root = settings.allowed_root_path
    # Check that resolved path is under allowed root
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        raise PathTraversalError(
            f"Path '{path}' is outside the allowed root '{allowed_root}'"
        )

    return resolved


def index_repository(path: str, graph_store: GraphStore) -> IndexSummary:
    """Parse and index a repository into FalkorDB.

    Args:
        path: Path to the repository to index.
        graph_store: The graph store instance.

    Returns:
        IndexSummary with counts and warnings.
    """
    settings = get_settings()
    resolved = validate_repo_path(path)

    # Parse the repository
    try:
        parse_result = parse_repository(
            str(resolved),
            max_file_size_kb=settings.max_file_size_kb,
            max_file_count=settings.max_file_count,
        )
    except Exception as e:
        raise IndexingError(f"Failed to parse repository: {e}") from e

    # Ingest into FalkorDB
    try:
        counts = graph_store.ingest(parse_result)
    except Exception as e:
        raise IndexingError(f"Failed to ingest into graph: {e}") from e

    return IndexSummary(
        repository_id=parse_result.repository_id,
        path=str(resolved),
        files_discovered=len(parse_result.files),
        functions_discovered=len(parse_result.functions),
        calls_resolved=len(parse_result.calls),
        calls_unresolved=len(parse_result.unresolved_calls),
        files_skipped=len(parse_result.skipped_files),
        parse_errors=len(parse_result.parse_errors),
        warnings=(
            parse_result.warnings
            + [f"Parse error: {e}" for e in parse_result.parse_errors]
            + [f"Unresolved call: {u.call_text} at line {u.call_line}" for u in parse_result.unresolved_calls]
        ),
    )
