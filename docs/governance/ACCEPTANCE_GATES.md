# Deferred Target-State Spec Acceptance Gates

## Required Surfaces

A deferred target-state spec change is incomplete unless all of these remain true.

These gates apply to the deferred spec surfaces under `docs/specs/`, `docs/governance/`, and `config/canonical/`.
Repo-wide authority enforcement lives in `docs/governance/REPO_AUTHORITY_POLICY.md`, `config/canonical/repo_authority.yaml`, and the `repo-governance` CI lane.

- `docs/specs/CANONICAL_INSTALLATION_DIRECTIVE.md` exists and contains the
  non-supersession boundary
- `docs/specs/CANONICAL_DAILY_CROSS_SECTIONAL_EQUITY_ALPHA_SPEC.md` exists and
  is clearly marked as target-state-only
- every file under `config/canonical/` exists, parses, and reflects either the
  effective current canon or an explicitly deferred target state
- lower-precedence docs defer to the deferred target-state specs instead of presenting
  competing installation, layout, or runtime canon
- `AGENTS.md`, the frozen Phase 1 docs, and current `Pipeline.py` behavior
  remain the higher-priority authorities

## Required Commands

Run these checks for a deferred target-state spec change:

- `uv run python tools/verify_scoped_canon.py`
- `uv run python tools/verify_frozen_surfaces.py`
- `uv run python tools/verify_tracked_locks.py`
- `uv run python -m pytest tests/test_scoped_canon.py tests/test_control_plane_policy.py tests/test_cursor_projection.py -q`

## Automatic Failure Conditions

The change must fail closed if any deferred target-state spec surface:

- claims Poetry is the active package-management authority
- claims a `pipeline/`-first layout is already the implemented runtime
- claims the target daily cross-sectional equity alpha runtime already replaced
  current `Pipeline.py`
- removes the explicit authority of `AGENTS.md`
- removes the explicit authority of `docs/phase1-research-spec.md` or
  `docs/phase1-execution-roadmap.md`
- causes a generated projection or tracked lock to stop pointing at `AGENTS.md`
  as the control-plane source of truth
