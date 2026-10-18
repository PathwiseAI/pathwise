"""FastAPI application — Pathwise API routes and lifecycle."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.config import get_settings
from app.errors import (
    DatabaseConnectionError,
    IndexingError,
    PathTraversalError,
    RepositoryNotFoundError,
)
from app.graph_store import GraphStore
from app.investigator import investigate
from app.repository_service import index_repository
from app.schemas import (
    Claim,
    ClaimCategory,
    FunctionInfo,
    HealthResponse,
    IndexRequest,
    IndexSummary,
    InvestigateRequest,
    InvestigationResult,
    RepositoryInfo,
    VerifyRequest,
    VerifyResponse,
)
from app.verifier import make_claim_id, verify_claim

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Application lifecycle ──────────────────────────────────────────────────────

_graph_store: GraphStore | None = None


def get_graph_store() -> GraphStore:
    """Return the singleton GraphStore."""
    global _graph_store
    if _graph_store is None:
        _graph_store = GraphStore()
    return _graph_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — connect/disconnect graph store."""
    global _graph_store
    _graph_store = GraphStore()
    logger.info("Pathwise starting up")
    yield
    if _graph_store:
        _graph_store.close()
    logger.info("Pathwise shut down")


app = FastAPI(
    title="Pathwise",
    description="Intelligent Code Investigation Through Connected Paths",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    """Application and FalkorDB health check."""
    gs = get_graph_store()
    try:
        connected = gs.health_check()
    except Exception:
        connected = False

    return HealthResponse(
        status="healthy" if connected else "degraded",
        falkordb_connected=connected,
        detail="" if connected else "FalkorDB is not reachable",
    )


@app.post(
    "/api/repositories/index",
    response_model=IndexSummary,
    status_code=status.HTTP_201_CREATED,
)
async def api_index_repository(req: IndexRequest):
    """Index a Python repository."""
    gs = get_graph_store()
    try:
        summary = index_repository(req.path, gs)
        return summary
    except RepositoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PathTraversalError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except IndexingError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/repositories", response_model=list[RepositoryInfo])
async def api_list_repositories():
    """List all indexed repositories."""
    gs = get_graph_store()
    try:
        repos = gs.list_repositories()
        return [
            RepositoryInfo(
                repository_id=r["repository_id"],
                path=r["path"],
                file_count=r.get("file_count", 0),
                function_count=r.get("function_count", 0),
            )
            for r in repos
        ]
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/repositories/{repository_id}/functions", response_model=list[FunctionInfo])
async def api_list_functions(repository_id: str):
    """List all functions in an indexed repository."""
    gs = get_graph_store()
    try:
        functions = gs.list_functions(repository_id)
        if not functions:
            raise HTTPException(
                status_code=404,
                detail=f"No functions found for repository '{repository_id}'. "
                       f"It may not be indexed.",
            )
        return [
            FunctionInfo(
                function_id=f["function_id"],
                name=f["name"],
                qualified_name=f.get("qualified_name", f["name"]),
                file_path=f.get("file_path", ""),
                start_line=f.get("start_line", 0),
                end_line=f.get("end_line", 0),
                is_method=f.get("is_method", False),
                is_async=f.get("is_async", False),
            )
            for f in functions
        ]
    except HTTPException:
        raise
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/investigate", response_model=InvestigationResult)
async def api_investigate(req: InvestigateRequest):
    """Investigate a codebase question."""
    gs = get_graph_store()
    try:
        result = investigate(
            repo_id=req.repository_id,
            question=req.question,
            graph_store=gs,
            max_depth=req.max_depth,
        )
        return result
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/verify", response_model=VerifyResponse)
async def api_verify(req: VerifyRequest):
    """Verify a specific dependency claim."""
    gs = get_graph_store()
    try:
        # Resolve function names to IDs
        subject_id = req.subject
        target_id = req.target
        subject_matches = gs.find_functions_by_name(req.repository_id, req.subject)
        if subject_matches:
            subject_id = subject_matches[0]["function_id"]
        target_matches = gs.find_functions_by_name(req.repository_id, req.target)
        if target_matches:
            target_id = target_matches[0]["function_id"]

        claim = Claim(
            claim_id=make_claim_id(),
            subject=subject_id,
            predicate=req.predicate,
            target=target_id,
            repository_id=req.repository_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof = verify_claim(claim, gs)
        return VerifyResponse(claim=claim, proof=proof)
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.pathwise_host,
        port=settings.pathwise_port,
        reload=settings.pathwise_debug,
    )
