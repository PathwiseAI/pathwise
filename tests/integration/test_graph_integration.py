"""Integration tests against a real FalkorDB instance.

These tests require FalkorDB running on localhost:6379.
Run with: pytest tests/integration/ -m integration
"""

import os
import pytest

from app.config import get_settings, reset_settings
from app.graph_store import GraphStore
from app.parser import parse_repository
from app.investigator import investigate
from app.verifier import verify_claim, make_claim_id
from app.schemas import Claim, ClaimCategory, VerificationStatus


# Skip all tests in this module if FalkorDB isn't available
def _falkordb_available() -> bool:
    try:
        gs = GraphStore()
        return gs.health_check()
    except Exception:
        return False


pytestmark = pytest.mark.integration
skip_if_no_db = pytest.mark.skipif(
    not _falkordb_available(),
    reason="FalkorDB not available on localhost:6379",
)


@pytest.fixture(scope="module")
def graph_store():
    """Module-scoped graph store for integration tests."""
    gs = GraphStore()
    yield gs
    gs.close()


@pytest.fixture(scope="module")
def indexed_repo(graph_store):
    """Parse and ingest the sample_repo, return (repo_id, parse_result)."""
    sample_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "sample_repo",
    )
    parse_result = parse_repository(sample_path)
    graph_store.ingest(parse_result)
    return parse_result.repository_id, parse_result


# ── Node creation ──────────────────────────────────────────────────────────────

@skip_if_no_db
class TestNodeCreation:
    def test_functions_created(self, graph_store, indexed_repo):
        repo_id, pr = indexed_repo
        functions = graph_store.list_functions(repo_id)
        assert len(functions) >= 10
        names = [f["name"] for f in functions]
        assert "handle_request" in names
        assert "process_order" in names
        assert "compute_total" in names
        assert "save_order" in names
        assert "format_currency" in names

    def test_repo_info(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        info = graph_store.get_repository_info(repo_id)
        assert info is not None
        assert info["repository_id"] == repo_id
        assert info["file_count"] >= 5


# ── Relationship creation ─────────────────────────────────────────────────────

@skip_if_no_db
class TestRelationships:
    def test_direct_call_edge(self, graph_store, indexed_repo):
        repo_id, pr = indexed_repo
        # process_order calls compute_total
        po = graph_store.find_functions_by_name(repo_id, "process_order")
        ct = graph_store.find_functions_by_name(repo_id, "compute_total")
        assert po and ct
        assert graph_store.edge_exists(repo_id, po[0]["function_id"], ct[0]["function_id"])

    def test_no_false_edge(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        # format_currency should NOT call save_order
        fc = graph_store.find_functions_by_name(repo_id, "format_currency")
        so = graph_store.find_functions_by_name(repo_id, "save_order")
        assert fc and so
        assert not graph_store.edge_exists(repo_id, fc[0]["function_id"], so[0]["function_id"])


# ── Idempotent ingestion ──────────────────────────────────────────────────────

@skip_if_no_db
class TestIdempotentIngestion:
    def test_reindex_same_counts(self, graph_store, indexed_repo):
        repo_id, pr = indexed_repo
        before = len(graph_store.list_functions(repo_id))
        graph_store.ingest(pr)
        after = len(graph_store.list_functions(repo_id))
        assert before == after


# ── Direct callers ─────────────────────────────────────────────────────────────

@skip_if_no_db
class TestDirectCallers:
    def test_callers_of_compute_total(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        ct = graph_store.find_functions_by_name(repo_id, "compute_total")
        callers = graph_store.get_direct_callers(repo_id, ct[0]["function_id"])
        caller_names = [c["name"] for c in callers]
        assert "process_order" in caller_names

    def test_callers_of_isolated_function(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        fc = graph_store.find_functions_by_name(repo_id, "format_currency")
        callers = graph_store.get_direct_callers(repo_id, fc[0]["function_id"])
        assert len(callers) == 0


# ── Multi-hop callers ─────────────────────────────────────────────────────────

@skip_if_no_db
class TestMultiHopCallers:
    def test_multi_hop_to_save_order(self, graph_store, indexed_repo):
        """handle_request -> process_order -> save_order (2 hops)."""
        repo_id, _ = indexed_repo
        so = graph_store.find_functions_by_name(repo_id, "save_order")
        paths = graph_store.get_multi_hop_callers(repo_id, so[0]["function_id"], max_depth=5)
        assert len(paths) >= 1
        # At least one path should include handle_request
        all_names = set()
        for path in paths:
            for node in path:
                all_names.add(node["name"])
        assert "process_order" in all_names


# ── Call chain ─────────────────────────────────────────────────────────────────

@skip_if_no_db
class TestCallChain:
    def test_chain_handle_request_to_save_order(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        hr = graph_store.find_functions_by_name(repo_id, "handle_request")
        so = graph_store.find_functions_by_name(repo_id, "save_order")
        paths = graph_store.get_call_chain(
            repo_id, hr[0]["function_id"], so[0]["function_id"], max_depth=5,
        )
        assert len(paths) >= 1
        # Check path goes through process_order
        for path in paths:
            names = [n["name"] for n in path]
            assert names[0] == "handle_request"
            assert names[-1] == "save_order"


# ── Evidence path metadata ─────────────────────────────────────────────────────

@skip_if_no_db
class TestEvidenceMetadata:
    def test_paths_have_file_info(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        so = graph_store.find_functions_by_name(repo_id, "save_order")
        paths = graph_store.get_multi_hop_callers(repo_id, so[0]["function_id"])
        for path in paths:
            for node in path:
                assert "file_path" in node
                assert "name" in node


# ── Repository isolation ──────────────────────────────────────────────────────

@skip_if_no_db
class TestRepositoryIsolation:
    def test_different_repo_id_returns_nothing(self, graph_store):
        funcs = graph_store.list_functions("nonexistent_repo_id")
        assert len(funcs) == 0


# ── Verification with real DB ─────────────────────────────────────────────────

@skip_if_no_db
class TestVerificationIntegration:
    def test_verify_valid_direct_call(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        po = graph_store.find_functions_by_name(repo_id, "process_order")
        ct = graph_store.find_functions_by_name(repo_id, "compute_total")
        claim = Claim(
            claim_id=make_claim_id(),
            subject=po[0]["function_id"],
            predicate="CALLS",
            target=ct[0]["function_id"],
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof = verify_claim(claim, graph_store)
        assert proof.status == VerificationStatus.SUPPORTED

    def test_verify_invalid_relationship(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        fc = graph_store.find_functions_by_name(repo_id, "format_currency")
        so = graph_store.find_functions_by_name(repo_id, "save_order")
        claim = Claim(
            claim_id=make_claim_id(),
            subject=fc[0]["function_id"],
            predicate="CALLS",
            target=so[0]["function_id"],
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof = verify_claim(claim, graph_store)
        assert proof.status == VerificationStatus.UNSUPPORTED

    def test_verify_nonexistent_function(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        claim = Claim(
            claim_id=make_claim_id(),
            subject="nonexistent_id",
            predicate="CALLS",
            target="also_nonexistent",
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof = verify_claim(claim, graph_store)
        assert proof.status == VerificationStatus.INCONCLUSIVE


# ── Investigation integration ─────────────────────────────────────────────────

@skip_if_no_db
class TestInvestigationIntegration:
    def test_investigate_callers(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        result = investigate(repo_id, "Who calls compute_total?", graph_store)
        assert result.intent == "find_callers"
        assert result.answer
        assert len(result.claims) > 0
        assert len(result.proof_records) > 0

    def test_investigate_path(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        result = investigate(
            repo_id, "path from handle_request to save_order", graph_store,
        )
        assert result.intent == "find_path"
        assert len(result.evidence_paths) > 0

    def test_investigate_unknown_function(self, graph_store, indexed_repo):
        repo_id, _ = indexed_repo
        result = investigate(repo_id, "Who calls nonexistent_xyz?", graph_store)
        assert "not found" in result.answer.lower()
