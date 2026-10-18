"""Unit tests for the Proof Mode verifier (mocked graph store)."""

from unittest.mock import MagicMock

import pytest

from app.schemas import Claim, ClaimCategory, EvidencePath, VerificationStatus
from app.verifier import verify_claim, make_claim_id
from app.errors import DatabaseConnectionError


@pytest.fixture
def mock_gs():
    """Create a mock GraphStore."""
    return MagicMock()


def _make_claim(subject="func_a", target="func_b", predicate="CALLS", repo_id="testrepo"):
    return Claim(
        claim_id=make_claim_id(),
        subject=subject,
        predicate=predicate,
        target=target,
        repository_id=repo_id,
        category=ClaimCategory.GRAPH_FACT,
    )


class TestVerifyClaim:
    def test_supported_direct_call(self, mock_gs):
        """SUPPORTED when both nodes exist and edge exists."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.return_value = True
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.SUPPORTED

    def test_supported_indirect_path(self, mock_gs):
        """SUPPORTED when direct edge missing but indirect path found."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.return_value = False
        mock_gs.get_call_chain.return_value = [[{"function_id": "a"}, {"function_id": "b"}, {"function_id": "c"}]]
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.SUPPORTED

    def test_unsupported_no_path(self, mock_gs):
        """UNSUPPORTED when both nodes exist but no relationship."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.return_value = False
        mock_gs.get_call_chain.return_value = []
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.UNSUPPORTED

    def test_inconclusive_subject_missing(self, mock_gs):
        """INCONCLUSIVE when subject node doesn't exist."""
        mock_gs.node_exists.side_effect = lambda repo_id, fid: fid != "func_a"
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_inconclusive_target_missing(self, mock_gs):
        """INCONCLUSIVE when target node doesn't exist."""
        mock_gs.node_exists.side_effect = lambda repo_id, fid: fid != "func_b"
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_inconclusive_both_missing(self, mock_gs):
        """INCONCLUSIVE when both nodes are missing."""
        mock_gs.node_exists.return_value = False
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_inconclusive_db_unavailable(self, mock_gs):
        """INCONCLUSIVE when database is unavailable."""
        mock_gs.node_exists.side_effect = DatabaseConnectionError("down")
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_inconclusive_unknown_predicate(self, mock_gs):
        """INCONCLUSIVE for unsupported predicates."""
        mock_gs.node_exists.return_value = True
        claim = _make_claim(predicate="IMPORTS")
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_chain_claim_supported(self, mock_gs):
        """SUPPORTED for CALLS_CHAIN when all edges exist."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.return_value = True
        claim = _make_claim(predicate="CALLS_CHAIN")
        claim.evidence_path = EvidencePath(
            nodes=["func_a", "func_mid", "func_b"]
        )
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.SUPPORTED

    def test_chain_claim_unsupported_missing_edge(self, mock_gs):
        """UNSUPPORTED for CALLS_CHAIN when an edge is missing."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.side_effect = [
            True,   # func_a -> func_mid exists
            False,  # func_mid -> func_b missing
        ]
        claim = _make_claim(predicate="CALLS_CHAIN")
        claim.evidence_path = EvidencePath(
            nodes=["func_a", "func_mid", "func_b"]
        )
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.UNSUPPORTED

    def test_wrong_repository_id(self, mock_gs):
        """INCONCLUSIVE for wrong repo — nodes not found."""
        mock_gs.node_exists.return_value = False
        claim = _make_claim(repo_id="wrong_repo")
        proof = verify_claim(claim, mock_gs)
        assert proof.status == VerificationStatus.INCONCLUSIVE

    def test_proof_record_has_evidence(self, mock_gs):
        """ProofRecord includes evidence_inspected details."""
        mock_gs.node_exists.return_value = True
        mock_gs.edge_exists.return_value = True
        claim = _make_claim()
        proof = verify_claim(claim, mock_gs)
        assert len(proof.evidence_inspected) > 0
        assert proof.reason
