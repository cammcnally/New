# Path Consistency Assessment

**Date:** 2026-03-10  
**Scope:** Pipeline output paths, log locations, and file references repo-wide

---

## Single source of truth

**Authority:** `.cursor/rules/output-and-resume-contract.mdc`

| Path | Location |
|------|----------|
| Log (authoritative) | `{output_dir}/00_logs/pipeline.log` |
| Resume state | `{output_dir}/06_state/resume_state.json` |
| Panel regularity | `{output_dir}/00_logs/panel_timestamp_regularity_by_ticker.csv` |

**Common `output_dir` values:** `pipeline_outputs` (all runs), `pipeline_outputs_optuna` (Optuna tuning). Determine from user context.

---

## Changes made

1. **run-pipeline.md** — Already had path authority; uses `{output_dir}` placeholders and lists pipeline_outputs.
2. **output-and-resume-contract.mdc** — Already had path authority table; no hardcoded output dir names.
3. **pipeline-runner-recovery SKILL** — Added output_dir section, path authority reference; fixed `{output_dir}` in diagnostic paths; consolidated to pipeline_outputs (smoke removed).
4. **pipeline-watcher.md** — Added pipeline_outputs example; path authority reference; clarified restart example.
5. **invoke-watcher-on-pipeline-failure.mdc** — Added pipeline_outputs; `{output_dir}` in paths.
6. **README.md** — Consolidated to pipeline_outputs; clarified output_dir determines all paths; log path note.
7. **pipeline-auditor_assessment.md** — Corrected EW2: Pipeline writes only to `00_logs/pipeline.log` (no dual log).

---

## Pipeline.py behavior

- Writes log only to `paths.logs_dir / "pipeline.log"` (L476) = `{output_dir}/00_logs/pipeline.log`
- No root-level or dual log file
- All paths derived from `config.output_dir` via `build_output_paths()`

---

## Recommendations

- When running or diagnosing, always use the `output_dir` from the current run context (e.g. pipeline_outputs).
- Never hardcode `pipeline_outputs` in commands when the user runs with a different output_dir.
- Reference `.cursor/rules/output-and-resume-contract.mdc` when path semantics are unclear.
