"""Application configuration with validated environment settings."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pathwise application settings loaded from environment / .env."""

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: str = ""

    # Application
    pathwise_host: str = "0.0.0.0"
    pathwise_port: int = 8000
    pathwise_debug: bool = False

    # Repository indexing limits
    allowed_root: str = "."
    max_file_size_kb: int = 500
    max_file_count: int = 1000
    max_repo_size_mb: int = 50
    max_traversal_depth: int = 10
    query_timeout_ms: int = 5000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def allowed_root_path(self) -> Path:
        """Resolve the allowed root to an absolute path."""
        return Path(self.allowed_root).resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings — used in testing."""
    global _settings
    _settings = None
