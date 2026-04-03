# Repository Authority Policy

## Binding Sentence

No repository rule is valid unless it is enforced by canonical files, machine-readable registry, verifier scripts, tests, runtime loaders, or CI failure gates.

## Registry Of Record

Use `config/canonical/repo_authority.yaml` as the machine-readable source of truth for repo authority status.

Do not create a second machine-readable authority registry.
Do not leave authority status implied by prose alone.

The `AGENTS.md` protected-authorities bullets define the mandatory core human policy list.
`config/canonical/repo_authority.yaml` governs path classification and may protect additional enforcement surfaces beyond that core list.

## Repository Authority Enforcement

The repository operates under one-authority-per-concern.

Protected authorities must not be superseded, contradicted, or semantically replaced by plans, checklists, generated shims, or secondary documents.

Frozen-boundary surfaces must not receive broad semantic rewrites.
Frozen-boundary surfaces may receive only narrow compatibility-safe changes allowed by verifier policy.

Generated surfaces are non-authoritative outputs.
Generated surfaces must be regenerated from canonical sources.
Generated surfaces must not define policy.

Plans, checklists, work notes, and secondary architecture documents do not govern the repo.
Normative content found in those surfaces must be migrated upward into the correct canonical file.
Retained duplicates must be explicitly demoted.

Deletion is prohibited unless repository authority verification allows it.

## Registry Classes

`protected_authorities`
: Protected governing surfaces.

`frozen_boundary_only`
: Compatibility-critical frozen runtime surfaces.

`generated_shims`
: Generated compatibility layers such as `.cursor/*` and tracked lock artifacts.

`generated_outputs`
: Generated exports, manifests, and projection outputs.

`live_runtime`
: Active runtime, verifier, and CI surfaces that remain in direct repo execution paths.

`compatibility_only`
: Transitional bridge surfaces still required by active consumers.

`optional_secondary`
: Non-primary supporting systems and explanatory documents.

`merge_demote_candidates`
: Plan, checklist, workplan, and archive-candidate surfaces that must not retain hidden authority.

## Separate-Approval Prohibitions

The following work is outside the scope of this enforcement program and is prohibited unless the user grants separate explicit approval:

- package-manager replacement, including Poetry adoption or lockfile migration
- repo-structure migration, including moving `Pipeline.py` into a new package layout or replacing the `market_data/` plus top-level `Pipeline.py` structure
- broad cleanup, refactoring, modernization, or semantic replacement of `Pipeline.py` or any other frozen-boundary surface
- target-state alpha-stack implementation that rewrites frozen Phase 1 semantics
- deletion of protected, frozen, or live-runtime surfaces outside verifier-approved generated-output cleanup

These are scope prohibitions, not suggestions.
Do not perform them as a side effect, cleanup refactor, opportunistic simplification, or architecture-alignment follow-up while implementing this directive.

Repo-structure migration remains prohibited until all of the following are true:

1. the user explicitly approves that migration by name
2. the replacement path and compatibility bridge are defined in canonical files first
3. any affected frozen authorities are updated first where policy requires doc-first change
4. verifier coverage and CI gates are extended to the new structure before runtime cutover

This prohibition overrides any inferred cleanup, modernization, simplification, or architecture-alignment opportunity.

## Enforced Scripts

Use these enforcement scripts:

- `tools/verify_repo_authority.py`
- `tools/verify_generated_surfaces.py`
- `tools/verify_frozen_boundaries.py`
- `tools/render_cursor_projection.py --check`
- `tools/verify_plan_demotions.py`

Use these acceptance tests:

- `tests/acceptance/test_repo_authority.py`
- `tests/acceptance/test_generated_surfaces.py`
- `tests/acceptance/test_frozen_boundaries.py`

Use `.github/workflows/repo-governance.yml` as the CI failure gate for repository authority enforcement.
Use `.github/workflows/ci.yml` to invoke that governance workflow on push and pull request.

## Demotion Banner

Every demoted plan or checklist file must start with this exact banner:

```md
Status: Non-authoritative work artifact
Canonical authority:
- AGENTS.md
- docs/data_contract.md
- docs/phase1-research-spec.md
- docs/phase1-execution-roadmap.md
```
