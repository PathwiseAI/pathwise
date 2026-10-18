"""Custom error types for Pathwise."""

from __future__ import annotations


class PathwiseError(Exception):
    """Base error for all Pathwise exceptions."""


class DatabaseConnectionError(PathwiseError):
    """FalkorDB is unreachable or returned an error."""


class RepositoryNotFoundError(PathwiseError):
    """The requested repository path does not exist or is not accessible."""


class RepositoryNotIndexedError(PathwiseError):
    """The repository has not been indexed yet."""


class FunctionNotFoundError(PathwiseError):
    """A referenced function was not found in the graph."""


class PathTraversalError(PathwiseError):
    """An attempt to access a path outside the allowed root."""


class IndexingError(PathwiseError):
    """An error during repository indexing."""


class ValidationError(PathwiseError):
    """Input validation failure."""
