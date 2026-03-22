# Subagents, Rules, and Commands

> **This master file supersedes both prior versions. On conflict, Section A governs.**

**Canonical location:** Subagents and rules live in `.cursor/` (agents in `.cursor/agents/`, rules in `.cursor/rules/`). This document specifies their content; the Blueprint does not duplicate those files.

Keep the Cursor-native set minimal and aligned with the canonical docs.

## Required subagents

### 1. pipeline-builder (`.cursor/agents/pipeline-builder.md`)
Purpose:
- implement and refactor the real pipeline in place
- preserve single-file discipline where possible
- avoid unnecessary file creation
- focus on correctness, chronology, staged discovery, and output hygiene

Non-negotiable builder rules:
- no placeholders
- no mocked metrics
- no random stand-ins
- no commented-out core stages
- no scaffold-only outputs presented as complete
- do not replace a working pipeline with a toy skeleton
- preserve and upgrade the real pipeline in place
- any learned pruning, ranking, clustering, ablation, or subset-search step must respect train-only fitting

### 2. pipeline-auditor (`.cursor/agents/pipeline-auditor.md`)
Purpose:
- audit chronology integrity, leakage, calibration, threshold lineage, IC lineage, portfolio logic, seed sensitivity, and output hygiene
- write `docs/assessments/pipeline-auditor-latest.md`

Required auditor behaviors:
- chronology-first
- lineage-first
- counter-check required
- no severity inflation
- separate model layer from policy layer
- separate methodology from engineering
- record **concerns checked and not confirmed**
- explicitly test train-only transform compliance
- explicitly test for placeholder logic, mocked outputs, or fake completeness

## Required rules

### pipeline-research-standards (`.cursor/rules/pipeline-research-standards.mdc`)
This rule should state, in substance:
- this repo is a time-series trading research pipeline
- chronology integrity, leakage prevention, evaluation integrity, and train-only transforms are first-class concerns
- feature discovery must be staged, not brute-forced
- orthogonal feature mixes are required
- family and redundancy controls must be explicit
- volatility clustering, Spearman IC, and seed robustness are canonical parts of the design
- portfolio metrics drive final selection
- outputs must remain clean and overwrite-oriented
- implementation must stay centered on `Pipeline.py`

### pipeline-auditor-behavior (`.cursor/rules/pipeline-auditor-behavior.mdc`)
This rule should state, in substance:
- audit chronology and lineage before findings
- threshold-selection lineage and calibration lineage must always be traced
- distinguish confirmed defects from design tradeoffs and engineering weaknesses
- write report to `docs/assessments/pipeline-auditor-latest.md`
- archive the previous latest copy under `docs/archive/assessments/pipeline-auditor/` before overwriting
- include concerns checked and not confirmed
- explicitly check seed robustness, IC logic, and train-only transformation compliance

## Commands

### build-feature-discovery-pipeline
This command should tell Cursor to:
1. implement the institutional blueprint
2. upgrade `Pipeline.py`
3. keep file creation tight and overwrite-oriented
4. reject placeholders and scaffolds
5. summarize changed files and run instructions

### audit-pipeline
This command should tell Cursor to:
1. invoke `pipeline-auditor`
2. regenerate `docs/assessments/pipeline-auditor-latest.md`
3. fully overwrite prior contents
4. verify the file exists
5. fail loudly if the audit output was not written

## Audit report overwrite instruction

The audit subagent must be told explicitly:
- always write the final report to exactly: `docs/assessments/pipeline-auditor-latest.md`
- if it exists, archive the previous latest copy before overwriting
- do not append
- do not create versioned variants unless explicitly asked

## Minimal recommended Cursor set

Keep it to:
- 2 subagents
- 2 rules
- 2 commands

No elaborate hook system is required.

---

## Section B — Legacy clarifications & context

**Output-overwrite instruction for audit report** (updated): The audit subagent must always write the final report to exactly `docs/assessments/pipeline-auditor-latest.md`; archive the previous latest copy under `docs/archive/assessments/pipeline-auditor/`; do not append; do not create `assessment_v2.md` or similar unless explicitly asked.
