# Contract Inventory

This document inventories every contract file in the repository, its canonical purpose,
enforcement path, and consuming code.

## Enforced contracts (live runtime or verification authority)

| File | Purpose | Enforcement path | Consuming code | Release impact |
|------|---------|-----------------|----------------|----------------|
| `contracts/bootstrap_pin.lock.json` | Pins loader-manifest hash and policy fingerprint for fail-closed bootstrap | Bootstrap validation at orchestrator startup | `control_plane/policy_loader.py` (`load_bootstrap_pin`), `tools/verify_tracked_locks.py` | Orchestrator refuses to start if mismatched |
| `contracts/policy_fingerprint.lock.json` | Legacy policy fingerprint pin (fallback when bootstrap pin absent) | Bootstrap validation (legacy path) | `control_plane/policy_loader.py` (`load_bootstrap_pin`, `write_policy_fingerprint_lock`), `tools/verify_tracked_locks.py` | Orchestrator refuses to start if mismatched |
| `contracts/projection_manifest.lock.json` | Tracks Cursor projection generation metadata | Lock verification | `tools/verify_tracked_locks.py`, `tools/refresh_projection_lock.py` | Lock verification fails if drift detected |
| `contracts/frozen_surfaces_manifest.json` | Lists files whose existence is required for repo integrity | Frozen-surface verification | `tools/verify_frozen_surfaces.py` | Verification fails if any listed file is missing |

## Evidence-only contracts (archived)

These files documented governance decisions during the Phase 1 migration.
They were tracked in `frozen_surfaces_manifest.json` for existence-checking only --
no Python code parsed their contents at runtime. They have been moved to
`docs/archive/contracts/` and are retained as read-only evidence.

| File (archived) | Original purpose | Why archived |
|-----------------|-----------------|--------------|
| `semantic_precedence_contract.json` | Documented promotion hierarchy / composite score policy | No code consumer; governance documentation only |
| `threshold_compatibility_contract.json` | Documented threshold family and admission engine constraints | No code consumer; governance documentation only |
| `determinism_contract.json` | Documented seed values and tolerances for canonical reruns | No code consumer; Pipeline.py has its own seed logic |
| `migration_sequence.json` | Documented ordered migration steps for Python cutover | No code consumer; migration process documentation |
| `current_mission_priority.json` | Documented mission ordering and prerequisites | No code consumer; process documentation only |
| `mcp_permissions.json` | Documented per-role MCP server/tool access | No code consumer; duplicates `AGENTS.md` mcp_policy |
| `self_heal_contract.json` | Documented allowed/forbidden automatic recovery actions | No code consumer; governance documentation only |
| `issue_taxonomy.json` | Documented issue classification labels | No code consumer; taxonomy documentation only |

## Non-contract governance files (other locations)

| File | Purpose | Enforcement path |
|------|---------|-----------------|
| `control_plane/phase1_contract.json` | Phase 1 artifact schema and validation rules | `tools/phase1_sanity_check.py` |
| `control_plane/governance_registries.json` | Agent/tool/grader metadata for orchestrator prompts | `control_plane/policy_loader.py` (required at bootstrap) |
| `control_plane/loader_manifest.json` | SHA256 integrity hashes for control-plane files | `control_plane/policy_loader.py` (`verify_loader_manifest`) |
| `repo_control/file_registry.yaml` | Authoritative file vitality and cleanup registry | `tools/audit_file_registry.py`, `tools/report_cleanup_candidates.py`, `tools/verify_frozen_surfaces.py` (existence + non-empty registry) |
| `docs/repo_cleanup_policy.md` | Human-readable explanation of cleanup classes and rules | `tools/verify_frozen_surfaces.py` (existence via frozen surfaces manifest) |
| `docs/end_to_end_trading_system_architecture.md` | Consolidated future-state downstream trading-system architecture; merges the expanded three-part system brief without changing frozen Phase 1 semantics by itself | Human-governed documentation surface referenced by `README.md`, `docs/PROJECT_OUTCOME.md`, and `docs/phase1-execution-roadmap.md` |
