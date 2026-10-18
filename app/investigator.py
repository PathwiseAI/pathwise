"""Investigation engine — deterministic question routing and evidence retrieval.

Converts natural-language questions into controlled graph operations.
No LLM required for core functionality.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.errors import FunctionNotFoundError, DatabaseConnectionError
from app.graph_store import GraphStore
from app.schemas import (
    Claim, ClaimCategory, EvidencePath, FunctionInfo,
    InvestigationResult, ProofRecord, VerificationStatus,
)
from app.verifier import verify_claims, make_claim_id

logger = logging.getLogger(__name__)


# ── Intent Detection ───────────────────────────────────────────────────────────

INTENT_PATTERNS = [
    # "who/what calls X" — find callers
    (r"(?:who|what)\s+calls?\s+(.+)", "find_callers"),
    (r"(?:callers?\s+of|called\s+by)\s+(.+)", "find_callers"),
    # "what does X call" — find callees
    (r"what\s+does\s+(.+?)\s+call", "find_callees"),
    (r"(?:callees?\s+of|functions?\s+called\s+by)\s+(.+)", "find_callees"),
    # "impact/affected by change to X"
    (r"what\s+(?:is|would\s+be)\s+(?:the\s+)?(?:impact|effect)\s+.*?(?:changing|modifying)\s+(.+)", "find_impact"),
    (r"(?:impact|affected|dependencies|depends)\s+.*?(?:of|by|on|to)\s+(.+)", "find_impact"),
    # "path/chain/connection from X to Y"
    (r"(?:path|chain|route|connection)\s+(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+)", "find_path"),
    (r"(?:does|can|is)\s+(.+?)\s+(?:call|reach|connect\s+to|lead\s+to)\s+(.+)", "find_path"),
    # "verify/prove X calls Y"
    (r"(?:verify|prove|check|confirm)\s+(?:that\s+)?(.+?)\s+calls?\s+(.+)", "verify_relationship"),
]


def detect_intent(question: str) -> tuple[str, list[str]]:
    """Detect the investigation intent and extract function references.

    Returns:
        Tuple of (intent_name, [extracted_function_names]).
    """
    q = question.strip().rstrip("?").lower()

    for pattern, intent in INTENT_PATTERNS:
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            groups = [g.strip().strip("'\"`") for g in match.groups() if g]
            return intent, groups

    # Fallback: try to find any function name mentioned
    # Look for patterns like "function_name" or `function_name`
    backtick_refs = re.findall(r"`([^`]+)`", question)
    quoted_refs = re.findall(r"['\"]([^'\"]+)['\"]", question)
    refs = backtick_refs + quoted_refs

    if refs:
        if len(refs) >= 2:
            return "find_path", refs[:2]
        return "find_callers", refs[:1]

    return "unknown", []


def _clean_function_ref(ref: str) -> str:
    """Clean a function reference extracted from a question."""
    ref = ref.strip().strip("'\"` ")
    # Remove common prefixes
    for prefix in ["function ", "method ", "the ", "a ", "changing ", "modifying "]:
        if ref.lower().startswith(prefix):
            ref = ref[len(prefix):]
    return ref.strip()


# ── Function Resolution ────────────────────────────────────────────────────────

def resolve_function(
    repo_id: str, name: str, graph_store: GraphStore,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Resolve a function name to a graph node.

    Returns:
        Tuple of (resolved_function_or_None, list_of_candidates_for_disambiguation).
    """
    clean = _clean_function_ref(name)
    candidates = graph_store.find_functions_by_name(repo_id, clean)

    if len(candidates) == 1:
        return candidates[0], candidates
    if len(candidates) > 1:
        # Try exact qualified_name match
        for c in candidates:
            if c["qualified_name"] == clean:
                return c, candidates
        return None, candidates  # Ambiguous
    return None, []


def _func_info_from_dict(d: dict[str, Any]) -> FunctionInfo:
    """Convert a dict to a FunctionInfo schema."""
    return FunctionInfo(
        function_id=d["function_id"],
        name=d["name"],
        qualified_name=d.get("qualified_name", d["name"]),
        file_path=d.get("file_path", ""),
        start_line=d.get("start_line", 0),
        end_line=d.get("end_line", 0),
        is_method=d.get("is_method", False),
        is_async=d.get("is_async", False),
    )


def _format_location(func: dict[str, Any]) -> str:
    """Format a function location string."""
    return f"{func.get('file_path', '?')}:{func.get('start_line', '?')}"


# ── Investigation Handlers ─────────────────────────────────────────────────────

def _investigate_callers(
    repo_id: str, func_name: str, graph_store: GraphStore, max_depth: int,
) -> InvestigationResult:
    """Find all direct and indirect callers of a function."""
    resolved, candidates = resolve_function(repo_id, func_name, graph_store)

    if resolved is None and candidates:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"Who calls {func_name}?",
            intent="find_callers",
            answer=f"Ambiguous function name '{func_name}'. Multiple matches found.",
            disambiguation=[_func_info_from_dict(c) for c in candidates],
        )

    if resolved is None:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"Who calls {func_name}?",
            intent="find_callers",
            answer=f"Function '{func_name}' not found in the indexed repository.",
            warnings=[f"Function '{func_name}' not found. Check the name or re-index."],
        )

    fid = resolved["function_id"]

    # Direct callers
    direct = graph_store.get_direct_callers(repo_id, fid)

    # Multi-hop callers
    multi_hop = graph_store.get_multi_hop_callers(repo_id, fid, max_depth=max_depth)

    # Build claims and evidence
    claims: list[Claim] = []
    evidence_paths: list[EvidencePath] = []

    for caller in direct:
        claim = Claim(
            claim_id=make_claim_id(),
            subject=caller["function_id"],
            predicate="CALLS",
            target=fid,
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
            source_location=_format_location(caller),
            target_location=_format_location(resolved),
        )
        claims.append(claim)

    for path in multi_hop:
        if len(path) > 2:  # Only add multi-hop paths (not direct)
            ep = EvidencePath(
                nodes=[n["function_id"] for n in path],
                node_details=[
                    {"name": n["name"], "file": n.get("file_path", ""), "line": n.get("start_line", 0)}
                    for n in path
                ],
            )
            evidence_paths.append(ep)

    # Verify claims
    proof_records = verify_claims(claims, graph_store)

    # Build answer
    if direct:
        caller_names = [f"`{c['qualified_name']}` ({c.get('file_path', '?')}:{c.get('start_line', '?')})" for c in direct]
        answer = (
            f"Function `{resolved['qualified_name']}` is directly called by: "
            + ", ".join(caller_names) + "."
        )
        if multi_hop:
            answer += f"\n\n{len(multi_hop)} call path(s) found (up to {max_depth} hops)."
    else:
        answer = f"No callers found for `{resolved['qualified_name']}` in the indexed repository."

    return InvestigationResult(
        repository_id=repo_id,
        question=f"Who calls {func_name}?",
        intent="find_callers",
        answer=answer,
        claims=claims,
        proof_records=proof_records,
        evidence_paths=evidence_paths,
    )


def _investigate_callees(
    repo_id: str, func_name: str, graph_store: GraphStore, max_depth: int,
) -> InvestigationResult:
    """Find all functions called by a given function."""
    resolved, candidates = resolve_function(repo_id, func_name, graph_store)

    if resolved is None and candidates:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"What does {func_name} call?",
            intent="find_callees",
            answer=f"Ambiguous function name '{func_name}'. Multiple matches found.",
            disambiguation=[_func_info_from_dict(c) for c in candidates],
        )

    if resolved is None:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"What does {func_name} call?",
            intent="find_callees",
            answer=f"Function '{func_name}' not found in the indexed repository.",
            warnings=[f"Function '{func_name}' not found."],
        )

    fid = resolved["function_id"]
    callees = graph_store.get_direct_callees(repo_id, fid)

    claims: list[Claim] = []
    for callee in callees:
        claim = Claim(
            claim_id=make_claim_id(),
            subject=fid,
            predicate="CALLS",
            target=callee["function_id"],
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
            source_location=_format_location(resolved),
            target_location=_format_location(callee),
        )
        claims.append(claim)

    proof_records = verify_claims(claims, graph_store)

    if callees:
        callee_names = [f"`{c['qualified_name']}` ({c.get('file_path', '?')}:{c.get('start_line', '?')})" for c in callees]
        answer = (
            f"Function `{resolved['qualified_name']}` directly calls: "
            + ", ".join(callee_names) + "."
        )
    else:
        answer = f"Function `{resolved['qualified_name']}` does not call any other indexed functions."

    return InvestigationResult(
        repository_id=repo_id,
        question=f"What does {func_name} call?",
        intent="find_callees",
        answer=answer,
        claims=claims,
        proof_records=proof_records,
    )


def _investigate_impact(
    repo_id: str, func_name: str, graph_store: GraphStore, max_depth: int,
) -> InvestigationResult:
    """Find functions that could be affected by changes to a function."""
    resolved, candidates = resolve_function(repo_id, func_name, graph_store)

    if resolved is None and candidates:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"Impact of changes to {func_name}?",
            intent="find_impact",
            answer=f"Ambiguous function name '{func_name}'. Multiple matches found.",
            disambiguation=[_func_info_from_dict(c) for c in candidates],
        )

    if resolved is None:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"Impact of changes to {func_name}?",
            intent="find_impact",
            answer=f"Function '{func_name}' not found.",
            warnings=[f"Function '{func_name}' not found."],
        )

    fid = resolved["function_id"]
    paths = graph_store.get_impact(repo_id, fid, max_depth=max_depth)

    claims: list[Claim] = []
    evidence_paths: list[EvidencePath] = []

    # Collect unique impacted functions and unique edges
    impacted: dict[str, dict] = {}
    # Track unique edges (caller_id, callee_id) to avoid duplicate claims
    seen_edges: set[tuple[str, str]] = set()

    for path in paths:
        for node in path:
            if node["function_id"] != fid:
                impacted[node["function_id"]] = node

        ep = EvidencePath(
            nodes=[n["function_id"] for n in path],
            node_details=[
                {"name": n["name"], "file": n.get("file_path", ""), "line": n.get("start_line", 0)}
                for n in path
            ],
        )
        evidence_paths.append(ep)

        # Emit one claim per edge in this path
        for i in range(len(path) - 1):
            caller_node = path[i]
            callee_node = path[i + 1]
            edge_key = (caller_node["function_id"], callee_node["function_id"])
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                claim = Claim(
                    claim_id=make_claim_id(),
                    subject=caller_node["function_id"],
                    predicate="CALLS",
                    target=callee_node["function_id"],
                    repository_id=repo_id,
                    category=ClaimCategory.GRAPH_FACT,
                    source_location=_format_location(caller_node),
                    target_location=_format_location(callee_node),
                )
                claims.append(claim)

    proof_records = verify_claims(claims, graph_store)

    if impacted:
        names = [f"`{v['qualified_name']}` ({v.get('file_path', '?')})" for v in impacted.values()]
        answer = (
            f"Changes to `{resolved['qualified_name']}` may affect {len(impacted)} function(s): "
            + ", ".join(names) + ".\n\n"
            f"Note: Impact is inferred from call graph relationships. "
            f"A caller relationship does not guarantee a runtime failure."
        )
    else:
        answer = f"No upstream callers found for `{resolved['qualified_name']}`. Changes are unlikely to affect other indexed functions."

    return InvestigationResult(
        repository_id=repo_id,
        question=f"Impact of changes to {func_name}?",
        intent="find_impact",
        answer=answer,
        claims=claims,
        proof_records=proof_records,
        evidence_paths=evidence_paths,
    )


def _investigate_path(
    repo_id: str, source_name: str, target_name: str,
    graph_store: GraphStore, max_depth: int,
) -> InvestigationResult:
    """Find call paths between two functions."""
    src_resolved, src_candidates = resolve_function(repo_id, source_name, graph_store)
    tgt_resolved, tgt_candidates = resolve_function(repo_id, target_name, graph_store)

    warnings: list[str] = []

    if src_resolved is None:
        if src_candidates:
            return InvestigationResult(
                repository_id=repo_id,
                question=f"Path from {source_name} to {target_name}?",
                intent="find_path",
                answer=f"Ambiguous source function '{source_name}'.",
                disambiguation=[_func_info_from_dict(c) for c in src_candidates],
            )
        warnings.append(f"Source function '{source_name}' not found.")

    if tgt_resolved is None:
        if tgt_candidates:
            return InvestigationResult(
                repository_id=repo_id,
                question=f"Path from {source_name} to {target_name}?",
                intent="find_path",
                answer=f"Ambiguous target function '{target_name}'.",
                disambiguation=[_func_info_from_dict(c) for c in tgt_candidates],
            )
        warnings.append(f"Target function '{target_name}' not found.")

    if warnings:
        return InvestigationResult(
            repository_id=repo_id,
            question=f"Path from {source_name} to {target_name}?",
            intent="find_path",
            answer="Could not find one or both functions.",
            warnings=warnings,
        )

    src_id = src_resolved["function_id"]
    tgt_id = tgt_resolved["function_id"]

    paths = graph_store.get_call_chain(repo_id, src_id, tgt_id, max_depth=max_depth)

    claims: list[Claim] = []
    evidence_paths: list[EvidencePath] = []

    if paths:
        for path in paths:
            ep = EvidencePath(
                nodes=[n["function_id"] for n in path],
                node_details=[
                    {"name": n["name"], "file": n.get("file_path", ""), "line": n.get("start_line", 0)}
                    for n in path
                ],
            )
            evidence_paths.append(ep)

            # Create a chain claim
            claim = Claim(
                claim_id=make_claim_id(),
                subject=src_id,
                predicate="CALLS_CHAIN",
                target=tgt_id,
                repository_id=repo_id,
                category=ClaimCategory.GRAPH_FACT,
                evidence_path=ep,
                source_location=_format_location(src_resolved),
                target_location=_format_location(tgt_resolved),
            )
            claims.append(claim)

        proof_records = verify_claims(claims, graph_store)

        path_desc = []
        for p in paths:
            chain = " → ".join(f"`{n['name']}`" for n in p)
            path_desc.append(chain)

        answer = (
            f"Found {len(paths)} call path(s) from "
            f"`{src_resolved['qualified_name']}` to `{tgt_resolved['qualified_name']}`:\n\n"
            + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(path_desc))
        )
    else:
        answer = (
            f"No call path found from `{src_resolved['qualified_name']}` "
            f"to `{tgt_resolved['qualified_name']}` within {max_depth} hops."
        )
        proof_records = []

    return InvestigationResult(
        repository_id=repo_id,
        question=f"Path from {source_name} to {target_name}?",
        intent="find_path",
        answer=answer,
        claims=claims,
        proof_records=proof_records,
        evidence_paths=evidence_paths,
    )


def _investigate_verify(
    repo_id: str, source_name: str, target_name: str,
    graph_store: GraphStore,
) -> InvestigationResult:
    """Verify a specific dependency relationship."""
    src_resolved, _ = resolve_function(repo_id, source_name, graph_store)
    tgt_resolved, _ = resolve_function(repo_id, target_name, graph_store)

    src_id = src_resolved["function_id"] if src_resolved else source_name
    tgt_id = tgt_resolved["function_id"] if tgt_resolved else target_name

    claim = Claim(
        claim_id=make_claim_id(),
        subject=src_id,
        predicate="CALLS",
        target=tgt_id,
        repository_id=repo_id,
        category=ClaimCategory.GRAPH_FACT,
    )

    from app.verifier import verify_claim as _verify
    proof = _verify(claim, graph_store)

    answer = f"Verification of `{source_name}` → `{target_name}`: **{proof.status.value}**\n\n{proof.reason}"

    return InvestigationResult(
        repository_id=repo_id,
        question=f"Does {source_name} call {target_name}?",
        intent="verify_relationship",
        answer=answer,
        claims=[claim],
        proof_records=[proof],
    )


# ── Main Investigation Entry Point ────────────────────────────────────────────

def investigate(
    repo_id: str,
    question: str,
    graph_store: GraphStore,
    max_depth: int = 5,
) -> InvestigationResult:
    """Run an investigation based on a natural-language question.

    Uses deterministic intent detection and graph queries.
    No LLM required.
    """
    intent, refs = detect_intent(question)
    refs = [_clean_function_ref(r) for r in refs]

    try:
        if intent == "find_callers" and refs:
            return _investigate_callers(repo_id, refs[0], graph_store, max_depth)

        if intent == "find_callees" and refs:
            return _investigate_callees(repo_id, refs[0], graph_store, max_depth)

        if intent == "find_impact" and refs:
            return _investigate_impact(repo_id, refs[0], graph_store, max_depth)

        if intent == "find_path" and len(refs) >= 2:
            return _investigate_path(repo_id, refs[0], refs[1], graph_store, max_depth)

        if intent == "verify_relationship" and len(refs) >= 2:
            return _investigate_verify(repo_id, refs[0], refs[1], graph_store)

        # Fallback: try to treat the question as a function name search
        if refs:
            return _investigate_callers(repo_id, refs[0], graph_store, max_depth)

        return InvestigationResult(
            repository_id=repo_id,
            question=question,
            intent="unknown",
            answer=(
                "Could not understand the question. Try one of these patterns:\n"
                "- Who calls `function_name`?\n"
                "- What does `function_name` call?\n"
                "- What is the impact of changes to `function_name`?\n"
                "- Path from `source` to `target`?\n"
                "- Verify that `source` calls `target`\n"
            ),
            warnings=["Could not parse investigation intent from the question."],
        )

    except DatabaseConnectionError as e:
        return InvestigationResult(
            repository_id=repo_id,
            question=question,
            intent=intent,
            answer=f"Database unavailable: {e}",
            warnings=["FalkorDB connection failed during investigation."],
        )
    except Exception as e:
        logger.exception("Unexpected error during investigation")
        return InvestigationResult(
            repository_id=repo_id,
            question=question,
            intent=intent,
            answer=f"Investigation failed: {e}",
            warnings=[f"Unexpected error: {e}"],
        )
