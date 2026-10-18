"""Proof Mode — Independent evidence verification against FalkorDB.

Verifies claims by re-querying the authoritative graph.
Never trusts client-supplied evidence or LLM output as proof.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.errors import DatabaseConnectionError
from app.graph_store import GraphStore
from app.schemas import (
    Claim, ClaimCategory, EvidencePath,
    ProofRecord, VerificationStatus,
)

logger = logging.getLogger(__name__)

VERIFIER_VERSION = "0.1.0"


def make_claim_id() -> str:
    """Generate a unique claim ID."""
    return str(uuid.uuid4())[:8]


def verify_claim(claim: Claim, graph_store: GraphStore) -> ProofRecord:
    """Independently verify a single claim against the authoritative graph.

    Rules:
    - SUPPORTED: The graph contains the required nodes and relationships.
    - UNSUPPORTED: The nodes exist but the claimed relationship does not.
    - INCONCLUSIVE: A node cannot be found, or the system cannot safely decide.

    Args:
        claim: The structured claim to verify.
        graph_store: The graph store to query.

    Returns:
        ProofRecord with status, evidence inspected, and reasoning.
    """
    evidence_inspected: list[str] = []
    missing_evidence: list[str] = []

    try:
        # Check if both subject and target nodes exist
        subject_exists = graph_store.node_exists(claim.repository_id, claim.subject)
        evidence_inspected.append(f"node_check:{claim.subject}")

        target_exists = graph_store.node_exists(claim.repository_id, claim.target)
        evidence_inspected.append(f"node_check:{claim.target}")

        if not subject_exists and not target_exists:
            missing_evidence.extend([claim.subject, claim.target])
            return ProofRecord(
                claim_id=claim.claim_id,
                status=VerificationStatus.INCONCLUSIVE,
                evidence_inspected=evidence_inspected,
                missing_evidence=missing_evidence,
                reason=(
                    f"Neither subject '{claim.subject}' nor target '{claim.target}' "
                    f"found in the graph. Indexing may be incomplete."
                ),
            )

        if not subject_exists:
            missing_evidence.append(claim.subject)
            return ProofRecord(
                claim_id=claim.claim_id,
                status=VerificationStatus.INCONCLUSIVE,
                evidence_inspected=evidence_inspected,
                missing_evidence=missing_evidence,
                reason=(
                    f"Subject function '{claim.subject}' not found in graph. "
                    f"It may not have been indexed or the identifier is incorrect."
                ),
            )

        if not target_exists:
            missing_evidence.append(claim.target)
            return ProofRecord(
                claim_id=claim.claim_id,
                status=VerificationStatus.INCONCLUSIVE,
                evidence_inspected=evidence_inspected,
                missing_evidence=missing_evidence,
                reason=(
                    f"Target function '{claim.target}' not found in graph. "
                    f"It may not have been indexed or the identifier is incorrect."
                ),
            )

        # Both nodes exist — check the relationship
        if claim.predicate == "CALLS":
            edge = graph_store.edge_exists(
                claim.repository_id, claim.subject, claim.target,
            )
            evidence_inspected.append(f"edge_check:CALLS:{claim.subject}->{claim.target}")

            if edge:
                return ProofRecord(
                    claim_id=claim.claim_id,
                    status=VerificationStatus.SUPPORTED,
                    evidence_inspected=evidence_inspected,
                    missing_evidence=missing_evidence,
                    reason=(
                        f"Direct CALLS relationship confirmed: "
                        f"'{claim.subject}' -> '{claim.target}'"
                    ),
                )
            else:
                # Check for indirect path
                paths = graph_store.get_call_chain(
                    claim.repository_id, claim.subject, claim.target, max_depth=5,
                )
                evidence_inspected.append(
                    f"path_check:CALLS*1..5:{claim.subject}->{claim.target}"
                )
                if paths:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.SUPPORTED,
                        evidence_inspected=evidence_inspected,
                        missing_evidence=missing_evidence,
                        reason=(
                            f"No direct CALLS edge, but an indirect path exists "
                            f"({len(paths)} path(s) found through graph traversal)."
                        ),
                    )
                else:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.UNSUPPORTED,
                        evidence_inspected=evidence_inspected,
                        missing_evidence=[f"CALLS:{claim.subject}->{claim.target}"],
                        reason=(
                            f"Both functions exist in the graph but no CALLS "
                            f"relationship (direct or indirect up to 5 hops) was found."
                        ),
                    )

        elif claim.predicate == "CALLS_CHAIN":
            # Multi-hop path claim — verify each edge in the path
            if claim.evidence_path and len(claim.evidence_path.nodes) >= 2:
                all_edges_valid = True
                for i in range(len(claim.evidence_path.nodes) - 1):
                    src = claim.evidence_path.nodes[i]
                    dst = claim.evidence_path.nodes[i + 1]
                    edge = graph_store.edge_exists(claim.repository_id, src, dst)
                    evidence_inspected.append(f"edge_check:CALLS:{src}->{dst}")
                    if not edge:
                        all_edges_valid = False
                        missing_evidence.append(f"CALLS:{src}->{dst}")

                if all_edges_valid:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.SUPPORTED,
                        evidence_inspected=evidence_inspected,
                        missing_evidence=missing_evidence,
                        reason="All edges in the claimed call chain are verified.",
                    )
                else:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.UNSUPPORTED,
                        evidence_inspected=evidence_inspected,
                        missing_evidence=missing_evidence,
                        reason="One or more edges in the claimed call chain are missing.",
                    )
            else:
                # No path details — try to find one
                paths = graph_store.get_call_chain(
                    claim.repository_id, claim.subject, claim.target, max_depth=5,
                )
                evidence_inspected.append(
                    f"path_check:CALLS*1..5:{claim.subject}->{claim.target}"
                )
                if paths:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.SUPPORTED,
                        evidence_inspected=evidence_inspected,
                        reason=f"Call chain verified: {len(paths)} path(s) found.",
                    )
                else:
                    return ProofRecord(
                        claim_id=claim.claim_id,
                        status=VerificationStatus.UNSUPPORTED,
                        evidence_inspected=evidence_inspected,
                        reason="No call chain found between subject and target.",
                    )

        # Unknown predicate
        return ProofRecord(
            claim_id=claim.claim_id,
            status=VerificationStatus.INCONCLUSIVE,
            evidence_inspected=evidence_inspected,
            reason=f"Unsupported predicate '{claim.predicate}'. Cannot verify.",
        )

    except DatabaseConnectionError:
        return ProofRecord(
            claim_id=claim.claim_id,
            status=VerificationStatus.INCONCLUSIVE,
            evidence_inspected=evidence_inspected,
            reason="Database unavailable. Cannot verify claim.",
        )
    except Exception as e:
        logger.exception("Unexpected error during verification")
        return ProofRecord(
            claim_id=claim.claim_id,
            status=VerificationStatus.INCONCLUSIVE,
            evidence_inspected=evidence_inspected,
            reason=f"Verification error: {e}",
        )


def verify_claims(
    claims: list[Claim], graph_store: GraphStore,
) -> list[ProofRecord]:
    """Verify a list of claims."""
    return [verify_claim(claim, graph_store) for claim in claims]
