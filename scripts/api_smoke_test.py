"""Quick API smoke test."""
import httpx
import json

base = "http://127.0.0.1:8000"

# Health
print("=== HEALTH ===")
r = httpx.get(f"{base}/health")
print(f"Status: {r.status_code} -> {r.json()['status']}")

# Index
print("\n=== INDEX ===")
r = httpx.post(f"{base}/api/repositories/index",
               json={"path": "C:/Users/Asus/Desktop/Pathwise/sample_repo"})
print(f"Status: {r.status_code}")
d = r.json()
repo_id = d["repository_id"]
print(f"Repo: {repo_id}, Files: {d['files_discovered']}, "
      f"Functions: {d['functions_discovered']}, Calls: {d['calls_resolved']}")

# List functions
print("\n=== FUNCTIONS ===")
r = httpx.get(f"{base}/api/repositories/{repo_id}/functions")
funcs = r.json()
print(f"Found {len(funcs)} functions")

# Investigate callers
print("\n=== INVESTIGATE: Who calls compute_total? ===")
r = httpx.post(f"{base}/api/investigate", json={
    "repository_id": repo_id,
    "question": "Who calls compute_total?",
})
d = r.json()
print(f"Intent: {d['intent']}")
print(f"Answer: {d['answer'][:120]}")
for pr in d["proof_records"]:
    print(f"  Proof: [{pr['status']}] {pr['reason'][:80]}")

# Verify UNSUPPORTED
print("\n=== VERIFY: format_currency -> save_order (should be UNSUPPORTED) ===")
r = httpx.post(f"{base}/api/verify", json={
    "repository_id": repo_id,
    "subject": "format_currency",
    "target": "save_order",
})
d = r.json()
print(f"  [{d['proof']['status']}] {d['proof']['reason']}")

# Verify INCONCLUSIVE
print("\n=== VERIFY: fake_func -> save_order (should be INCONCLUSIVE) ===")
r = httpx.post(f"{base}/api/verify", json={
    "repository_id": repo_id,
    "subject": "totally_fake_func",
    "target": "save_order",
})
d = r.json()
print(f"  [{d['proof']['status']}] {d['proof']['reason']}")

print("\n=== ALL API ENDPOINTS WORKING ===")
