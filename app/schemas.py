"""Pydantic request/response schemas for the Pathwise API."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class VerificationStatus(str, Enum):
    """Proof Mode verification status."""
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ClaimCategory(str, Enum):
    """Category of a dependency claim."""
    GRAPH_FACT = "graph_fact"
    INFERRED_IMPACT = "inferred_impact"
    GENERAL = "general"


# ── Shared Models ──────────────────────────────────────────────────────────────

class FunctionInfo(BaseModel):
    """A discovered function."""
    function_id: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    is_method: bool = False
    is_async: bool = False


class CallRelationship(BaseModel):
    """A function-to-function call relationship."""
    caller_id: str
    callee_id: str
    call_line: int | None = None


class UnresolvedCall(BaseModel):
    """A call expression that could not be resolved to a known function."""
    caller_id: str
    call_text: str
    call_line: int


# ── Indexing ───────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    """Request to index a repository."""
    path: str = Field(..., description="Path to the repository to index")


class IndexSummary(BaseModel):
    """Summary of an indexing operation."""
    repository_id: str
    path: str
    files_discovered: int = 0
    functions_discovered: int = 0
    calls_resolved: int = 0
    calls_unresolved: int = 0
    files_skipped: int = 0
    parse_errors: int = 0
    warnings: list[str] = Field(default_factory=list)


# ── Investigation ─────────────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    """Request to investigate a codebase question."""
    repository_id: str
    question: str = Field(..., max_length=2000)
    max_depth: int = Field(default=5, ge=1, le=20)


class EvidencePath(BaseModel):
    """A single evidence path from the graph."""
    nodes: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    node_details: list[dict[str, Any]] = Field(default_factory=list)


class Claim(BaseModel):
    """A structured dependency claim."""
    claim_id: str
    subject: str
    predicate: str
    target: str
    repository_id: str
    category: ClaimCategory = ClaimCategory.GRAPH_FACT
    evidence_path: EvidencePath | None = None
    source_location: str | None = None
    target_location: str | None = None


class ProofRecord(BaseModel):
    """The result of verifying a single claim."""
    claim_id: str
    status: VerificationStatus
    evidence_inspected: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason: str = ""


class InvestigationResult(BaseModel):
    """Complete investigation response."""
    repository_id: str
    question: str
    intent: str = ""
    answer: str = ""
    claims: list[Claim] = Field(default_factory=list)
    proof_records: list[ProofRecord] = Field(default_factory=list)
    evidence_paths: list[EvidencePath] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disambiguation: list[FunctionInfo] | None = None


# ── Verification ──────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    """Request to verify a specific claim."""
    repository_id: str
    subject: str
    predicate: str = "CALLS"
    target: str


class VerifyResponse(BaseModel):
    """Verification response."""
    claim: Claim
    proof: ProofRecord


# ── Health ─────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    falkordb_connected: bool
    version: str = "0.1.0"
    detail: str = ""


# ── Repository listing ─────────────────────────────────────────────────────────

class RepositoryInfo(BaseModel):
    """Info about an indexed repository."""
    repository_id: str
    path: str
    file_count: int = 0
    function_count: int = 0
