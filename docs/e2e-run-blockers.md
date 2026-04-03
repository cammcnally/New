# E2E run blockers log

Operator reference for conditions that commonly stop the **authoritative local end-to-end path**: dependency sync, canonical market-data build, verification guards, compatibility export (including bridge checks), `Pipeline.py`, and final status. Stage order and commands live in [implementation_runbook.md](implementation_runbook.md); stages are defined in [`market_data/orchestration/e2e.py`](../market_data/orchestration/e2e.py) (`STAGES`).

**Scope:** A full `uv run python tools/run_repo_e2e.py` completion is the bar here. Bounded reruns (`--stop-after export_panel`, smoke panels, shorter walk-forward flags) are valid workflows but do not substitute for full validation.

**How to use this doc:** This is a **triage aid** (symptoms → causes → mitigations). It does **not** replace fixing problems. While working the repo, **remediate** blockers you encounter at the root when you can; only park an item with a written blocker if it is external, non-reproducible, or needs human approval.

---

## `dependency_sync`

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| Import errors for ingestion or market-data test deps | Dependency groups not installed | Run `make sync` or `uv sync --group dev --group control-plane --group ingestion --group ingestion-test` (same as canonical `env_sync_command` in `AGENTS.md`) | [Makefile](../Makefile), [AGENTS.md](../AGENTS.md) |
| Wrong interpreter or resolution failures | Python not 3.11.9, broken `.venv` | Use repo-prescribed Python; recreate venv and re-sync per [README.md](../README.md) setup | [AGENTS.md](../AGENTS.md) `runtime_environment` |
| `dependency_sync` stage exits non-zero in e2e | `uv` subprocess failure | Inspect `data_lake/manifests/e2e_logs/dependency_sync.log` | [`e2e.py`](../market_data/orchestration/e2e.py) |

---

## `canonical_market_data`

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| Bootstrap/sync errors, missing lake paths | `data_lake` not writable or misconfigured | Point `--data-lake` / settings at a valid root; ensure disk space and permissions | [IngestionSettings](../market_data/common/settings.py) |
| Ingest cannot reach sources | Missing vendor credentials, network, or local raw inputs | Configure secrets and raw layout per data contract; fix upstream availability | [data_contract.md](data_contract.md) |
| Export later refuses with `canonical_export_ready=false` or QA blockers | Required-core datasets/reports failing | Fix silver/gold/QA pipeline until dataset manifest reports readiness; inspect `run_all` blocking semantics | [`run_all.py`](../market_data/orchestration/run_all.py) |

---

## `verify_market_data`

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| `[docs-sync] git command failed` | No `git`, or `origin/main` missing / not fetched | Install git; `git fetch origin`; use a full clone (not shallow without main) | [`verify_market_data_docs_sync.py`](../tools/verify_market_data_docs_sync.py), [`e2e.py`](../market_data/orchestration/e2e.py) `_DOCS_SYNC_BASE_REF` |
| Contract / schema guard failure | Drift vs `docs/data_contract.md` or code contracts | Run `uv run python tools/verify_market_data_contracts.py`; align implementation to contract | [implementation_runbook.md](implementation_runbook.md) |
| PIT guard failure | Point-in-time contract violation | Run `uv run python tools/verify_market_data_pit.py`; fix join/as-of semantics | Same |
| Compat guard failure | Identity / compatibility surface mismatch | Run compat guard from Makefile / runbook | Same |

---

## `export_panel` and bridge verification

Export runs inside the `export_panel` stage; the bridge verifier runs immediately after export in e2e.

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| `Required dataset manifest not found` | No build at `dataset_manifest.json` | Complete `canonical_market_data` / manifest write path first | [`export_pipeline_panel.py`](../market_data/bridge/export_pipeline_panel.py) |
| `canonical_export_ready=false` or `compatibility_fallback_used=true` | Dataset not canonically ready | Repair QA/build until manifest flags allow export | Same |
| `no rows after joining` / missing prerequisite for `universe_membership` | Empty or missing silver `universe_membership` for the window | Rebuild universe membership (`market_data.cli` silver path); align dates with prices | Same |
| `[bridge] export panel is a Git LFS pointer` | Panel file is an LFS stub, not real CSV | `git lfs pull`; in CI use `actions/checkout@v4` with `lfs: true` | [`verify_market_data_bridge.py`](../tools/verify_market_data_bridge.py), [`.github/workflows/_test.yml`](../.github/workflows/_test.yml) |
| `universe_filter_applied=false` from verifier | Emergency export used `--skip-universe-filter` | Re-export with default filtering for research, or pass `--allow-relaxed-universe-export` to the bridge CLI only when intentional (`make bridge-guard` matches e2e: no relaxed flag) | [`verify_market_data_bridge.py`](../tools/verify_market_data_bridge.py), [Makefile](../Makefile) `bridge-guard` |

---

## `pipeline_run`

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| Path errors on Linux / cloud | Default Windows pipeline paths | Set `PIPELINE_BASE_PATH=/workspace` (or appropriate root) before `Pipeline.py` | [AGENTS.md](../AGENTS.md) Human Notes |
| Run fails or is impractical with small panel | Default long outer train/test windows | For `panel_ohlcv_smoke_tier1.csv`, use shorter windows (e.g. `--outer_train_months 6 --outer_test_months 3`) | [AGENTS.md](../AGENTS.md), [README.md](../README.md) |
| Subprocess non-zero exit | Phase 1 logic, data, or config error | Inspect `data_lake/manifests/e2e_logs/pipeline_run.log` | [`e2e.py`](../market_data/orchestration/e2e.py) |

---

## `finalize_status`

| Symptom | Typical cause | Mitigation | Reference |
| -------- | -------------- | ----------- | ---------- |
| `phase1_sanity_check.py` failure | Downstream artifacts or invariants failed | Read log; fix reported issues under `pipeline_output_dir` | [`e2e.py`](../market_data/orchestration/e2e.py) |
| Final verification bundle runs instead of reuse | Pre-export guard evidence incomplete | Ensure `verify_market_data` completes all pre-export guards | Same, `_has_complete_pre_export_guard_evidence` |

---

## Repo-wide verification and CI (not always E2E)

These often surface under `make verify` or targeted `pytest`, and may fail on `main` independently of a single e2e stage:

| Issue | Notes |
| ----- | ----- |
| Loader-manifest hash mismatches | Documented as known test failures until repaired |
| Missing generated `.cursor/` files | Regenerate with `python tools/render_cursor_projection.py` |
| Missing `subagent/` directory | Breaks a small set of tests per Human Notes |
| `tools/verify_tracked_locks.py` bootstrap-lock / loader-manifest mismatch | May be pre-existing; fix only when intentionally repairing bootstrap integrity |
| `tools/verify_runtime.py` false negative under `uv` | Interpreter path outside repo root despite correct Python 3.11.9 |

Source: [AGENTS.md](../AGENTS.md) Human Notes.

---

## Control plane and secrets

`CODEX_API_KEY` and `OPENAI_API_KEY` are required for the **control-plane orchestrator** per [AGENTS.md](../AGENTS.md). They are **not** required for the local `tools/run_repo_e2e.py` path unless you explicitly invoke orchestrator or Codex tooling that enforces that policy.

---

## Meta: validation maturity vs mechanical blockers

Per [phase1-execution-roadmap.md](phase1-execution-roadmap.md) (current status snapshot): a **full decision-grade end-to-end validation run has not yet been completed**, and some guardrails still need end-to-end smoke and final-run validation. That is a **product and governance maturity** gap, distinct from a single mechanical error (missing file, failed guard, etc.).

---

## Maintenance

When adding fail-closed checks, new e2e stages, or new verification entrypoints, update **this log** and [implementation_runbook.md](implementation_runbook.md) so operators keep a single triage path.
