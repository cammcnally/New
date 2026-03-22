# Execution Plans

## Unified Codex Control Plane Convergence

- Classification: `policy_changing`
- Objective: finish the protected-infrastructure convergence onto one canonical control plane, with `AGENTS.md` as the sole policy source, the Python Agents SDK as the single orchestrator runtime, the local Codex MCP server as the single coding backend, and OpenAI Traces as the single observability surface.
- Scope boundaries:
  - in scope: `AGENTS.md` parity, runtime enforcement, durable task artifacts, `.cursor` compatibility shims, control-plane tests/evals, env-first secret loading with legacy repo-local fallback
  - out of scope: changing frozen Phase 1 research semantics in `Pipeline.py`
- Required approvals and gates:
  - verifier review is mandatory after edits
  - read-only audit review is mandatory before closure
  - protected infrastructure changes require human approval; this workstream is proceeding under the current user-approved implementation request
- Key risks:
  - runtime behavior lagging behind canonical policy
  - stale `.cursor` shims misleading local workflows
  - task-state artifacts missing required recovery context
  - trace and MCP enforcement existing in docs but not in code
  - secret-loading docs drifting away from the env-first runtime contract
- Ordered steps:
  1. lock the protected change path in `AGENTS.md` and this plan
  2. close runtime-policy gaps in `control_plane/*` and `tools/control_plane.py`
  3. expand task artifacts and manifest integrity checks
  4. validate Codex MCP expected tools and deny undeclared runtime paths
  5. reduce `.cursor/*` to thin compatibility shims with parity checks
  6. harden env-first secret loading with legacy repo-local fallback
  7. add verifier/audit/eval coverage for the control-plane behaviors
  8. trust the updated policy fingerprint locally after edits are complete
- Expected artifacts:
  - updated canonical `AGENTS.md`
  - updated `control_plane/*` runtime and registries
  - updated `tools/control_plane.py`
  - new repo-tracked helper scripts for projection/secret migration as needed
  - updated tests covering runtime parity, task artifacts, and shim drift
- Restart point: task scaffolding, manifest integrity, and `.cursor` projection generation are the minimum durable checkpoint.
- Completion criteria:
  - the runtime consumes the canonical policy directly from `AGENTS.md`
  - `DependencyAgent`, internal actions, terminal states, trace security, and governance registries are enforced in code
  - task folders include the required durable artifacts and fail validation when stale or mismatched
  - `.cursor/*` can be regenerated as compatibility shims and no longer define authoritative behavior
  - secret loading is env-first, with the legacy repo-local file retained only as a fallback path
  - verifier evidence and audit findings exist for this protected-infrastructure change
