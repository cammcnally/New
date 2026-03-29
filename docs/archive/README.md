# Archive

Everything under `docs/archive/` is **read-only evidence** with no runtime authority.

These files preserve historical assessments, migration artifacts, and retired governance
contracts for audit trail purposes. No Python module in `control_plane/` or `tools/`
may import from or reference `docs/archive/` as a canonical source.

Live authority lives exclusively in:

- `AGENTS.md` (canonical policy)
- `docs/phase1-research-spec.md` (Phase 1 research spec)
- `docs/phase1-execution-roadmap.md` (Phase 1 execution roadmap)
- `README.md` (human operational guide)
- `contracts/` (enforced lock files and manifests only)
