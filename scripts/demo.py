"""Pathwise CLI demo script.

Usage:
    python scripts/demo.py                    # Full demo with FalkorDB
    python scripts/demo.py --api              # Run against the REST API
    python scripts/demo.py --help             # Show help

Requires FalkorDB running on localhost:6379.
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_direct_demo():
    """Run the demo using direct Python calls (no API server needed)."""
    from app.config import get_settings
    from app.graph_store import GraphStore
    from app.parser import parse_repository
    from app.investigator import investigate
    from app.verifier import verify_claim, make_claim_id
    from app.schemas import Claim, ClaimCategory

    print("=" * 70)
    print("  PATHWISE — Intelligent Code Investigation Demo")
    print("=" * 70)

    # Step 1: Connect to FalkorDB
    print("\n[1] Connecting to FalkorDB...")
    gs = GraphStore()
    if not gs.health_check():
        print("ERROR: Cannot connect to FalkorDB. Is it running on localhost:6379?")
        print("Start it with: docker-compose up -d")
        sys.exit(1)
    print("    ✓ Connected to FalkorDB")

    # Step 2: Parse the sample repository
    sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_repo")
    print(f"\n[2] Parsing sample repository: {sample_path}")
    parse_result = parse_repository(sample_path)
    print(f"    ✓ Found {len(parse_result.files)} files")
    print(f"    ✓ Found {len(parse_result.functions)} functions")
    print(f"    ✓ Resolved {len(parse_result.calls)} call relationships")
    print(f"    ✓ {len(parse_result.unresolved_calls)} unresolved calls")

    # Step 3: Ingest into FalkorDB
    print(f"\n[3] Ingesting into FalkorDB (graph: pathwise_{parse_result.repository_id})...")
    counts = gs.ingest(parse_result)
    print(f"    ✓ Created {counts['files']} file nodes")
    print(f"    ✓ Created {counts['functions']} function nodes")
    print(f"    ✓ Created {counts['calls']} CALLS relationships")

    repo_id = parse_result.repository_id

    # Step 4: List discovered functions
    print("\n[4] Discovered functions:")
    functions = gs.list_functions(repo_id)
    for f in functions:
        loc = f"{f['file_path']}:{f['start_line']}-{f['end_line']}"
        print(f"    • {f['qualified_name']:30s}  {loc}")

    # Step 5: Investigation — Who calls compute_total?
    print("\n" + "=" * 70)
    print("  INVESTIGATION: Who calls compute_total?")
    print("=" * 70)
    result = investigate(repo_id, "Who calls compute_total?", gs)
    print(f"\n  Intent: {result.intent}")
    print(f"  Answer: {result.answer}")
    if result.claims:
        print(f"\n  Claims ({len(result.claims)}):")
        for claim in result.claims:
            print(f"    • {claim.subject} → {claim.target}")
    if result.proof_records:
        print(f"\n  Proof Mode Results:")
        for proof in result.proof_records:
            print(f"    • [{proof.status.value}] {proof.reason}")

    # Step 6: Investigation — Path from handle_request to save_order
    print("\n" + "=" * 70)
    print("  INVESTIGATION: Path from handle_request to save_order")
    print("=" * 70)
    result2 = investigate(repo_id, "path from handle_request to save_order", gs)
    print(f"\n  Intent: {result2.intent}")
    print(f"  Answer: {result2.answer}")
    if result2.evidence_paths:
        print(f"\n  Evidence Paths ({len(result2.evidence_paths)}):")
        for i, ep in enumerate(result2.evidence_paths):
            print(f"    Path {i+1}:")
            for j, detail in enumerate(ep.node_details):
                prefix = "    → " if j > 0 else "      "
                print(f"      {prefix}{detail.get('name', '?')} ({detail.get('file', '?')}:{detail.get('line', '?')})")
    if result2.proof_records:
        print(f"\n  Proof Mode Results:")
        for proof in result2.proof_records:
            print(f"    • [{proof.status.value}] {proof.reason}")

    # Step 7: Investigation — Impact of changes to get_unit_price
    print("\n" + "=" * 70)
    print("  INVESTIGATION: Impact of changes to get_unit_price")
    print("=" * 70)
    result3 = investigate(repo_id, "what is the impact of changing get_unit_price?", gs)
    print(f"\n  Intent: {result3.intent}")
    print(f"  Answer: {result3.answer}")

    # Step 8: Proof Mode — Verify a valid claim
    print("\n" + "=" * 70)
    print("  PROOF MODE: Verify process_order CALLS compute_total (SHOULD BE SUPPORTED)")
    print("=" * 70)
    process_order_funcs = gs.find_functions_by_name(repo_id, "process_order")
    compute_total_funcs = gs.find_functions_by_name(repo_id, "compute_total")
    if process_order_funcs and compute_total_funcs:
        claim_valid = Claim(
            claim_id=make_claim_id(),
            subject=process_order_funcs[0]["function_id"],
            predicate="CALLS",
            target=compute_total_funcs[0]["function_id"],
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof_valid = verify_claim(claim_valid, gs)
        print(f"\n  Status: {proof_valid.status.value}")
        print(f"  Reason: {proof_valid.reason}")
        print(f"  Evidence: {proof_valid.evidence_inspected}")

    # Step 9: Proof Mode — Verify an UNSUPPORTED claim
    print("\n" + "=" * 70)
    print("  PROOF MODE: Verify format_currency CALLS save_order (SHOULD BE UNSUPPORTED)")
    print("=" * 70)
    format_funcs = gs.find_functions_by_name(repo_id, "format_currency")
    save_funcs = gs.find_functions_by_name(repo_id, "save_order")
    if format_funcs and save_funcs:
        claim_invalid = Claim(
            claim_id=make_claim_id(),
            subject=format_funcs[0]["function_id"],
            predicate="CALLS",
            target=save_funcs[0]["function_id"],
            repository_id=repo_id,
            category=ClaimCategory.GRAPH_FACT,
        )
        proof_invalid = verify_claim(claim_invalid, gs)
        print(f"\n  Status: {proof_invalid.status.value}")
        print(f"  Reason: {proof_invalid.reason}")

    # Step 10: Proof Mode — Verify an INCONCLUSIVE claim (nonexistent function)
    print("\n" + "=" * 70)
    print("  PROOF MODE: Verify nonexistent_func CALLS save_order (SHOULD BE INCONCLUSIVE)")
    print("=" * 70)
    claim_missing = Claim(
        claim_id=make_claim_id(),
        subject="nonexistent_function_id",
        predicate="CALLS",
        target=save_funcs[0]["function_id"] if save_funcs else "also_missing",
        repository_id=repo_id,
        category=ClaimCategory.GRAPH_FACT,
    )
    proof_missing = verify_claim(claim_missing, gs)
    print(f"\n  Status: {proof_missing.status.value}")
    print(f"  Reason: {proof_missing.reason}")

    # Summary
    print("\n" + "=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)
    print("\n  What the graph verifies:")
    print("    • Direct function call relationships found by static analysis")
    print("    • Multi-hop dependency paths through the call graph")
    print("    • Presence or absence of specific call edges")
    print("\n  What the graph CANNOT prove:")
    print("    • Runtime behavior (dynamic dispatch, monkey-patching)")
    print("    • That a code change WILL cause a failure")
    print("    • Relationships involving unresolved calls or dynamic imports")
    print("    • Completeness — unindexed code may contain additional relationships")

    gs.close()


def run_api_demo():
    """Run the demo against the REST API."""
    import httpx

    base = "http://localhost:8000"
    print("=" * 70)
    print("  PATHWISE — API Demo")
    print("=" * 70)

    # Health check
    print("\n[1] Health check...")
    r = httpx.get(f"{base}/health")
    print(f"    Status: {r.status_code}")
    print(f"    Response: {r.json()}")

    # Index
    sample_path = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_repo")
    )
    print(f"\n[2] Indexing {sample_path}...")
    r = httpx.post(f"{base}/api/repositories/index", json={"path": sample_path})
    print(f"    Status: {r.status_code}")
    data = r.json()
    print(f"    Response: {json.dumps(data, indent=2)}")
    repo_id = data.get("repository_id", "")

    if not repo_id:
        print("ERROR: Failed to index. Aborting.")
        sys.exit(1)

    # List functions
    print(f"\n[3] Listing functions...")
    r = httpx.get(f"{base}/api/repositories/{repo_id}/functions")
    funcs = r.json()
    for f in funcs:
        print(f"    • {f['qualified_name']} ({f['file_path']}:{f['start_line']})")

    # Investigate
    print(f"\n[4] Investigating: 'Who calls compute_total?'")
    r = httpx.post(f"{base}/api/investigate", json={
        "repository_id": repo_id,
        "question": "Who calls compute_total?",
    })
    result = r.json()
    print(f"    Answer: {result['answer']}")
    for p in result.get("proof_records", []):
        print(f"    [{p['status']}] {p['reason']}")

    # Verify
    print(f"\n[5] Verifying: format_currency CALLS save_order")
    r = httpx.post(f"{base}/api/verify", json={
        "repository_id": repo_id,
        "subject": "format_currency",
        "predicate": "CALLS",
        "target": "save_order",
    })
    vr = r.json()
    print(f"    Status: {vr['proof']['status']}")
    print(f"    Reason: {vr['proof']['reason']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pathwise Demo")
    parser.add_argument("--api", action="store_true", help="Run against the REST API")
    args = parser.parse_args()

    if args.api:
        run_api_demo()
    else:
        run_direct_demo()
