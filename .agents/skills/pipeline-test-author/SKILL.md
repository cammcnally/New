---
name: pipeline-test-author
description: Targeted test authoring workflow for control-plane, pipeline, and artifact regressions.
---

Use this skill when adding or repairing tests.

Rules:
- preserve existing semantics unless the task explicitly changes them
- prefer the narrowest relevant test first
- for runtime changes, write both success-path and fail-closed tests
- for contract changes, test schema, behavior, and stop conditions
- for tool or projection changes, test generation and canonical lock alignment

Required test categories:
- helper/unit
- regression
- control-plane/bootstrap
- artifact schema
- smoke path
- deterministic replay when applicable
