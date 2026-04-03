---
name: systematic-debugging
description: Root-cause debugging for failing tests, broken commands, inconsistent behavior, environment issues, flaky runs, and suspicious outputs. Reproduce, isolate, prove cause, fix narrowly, validate, and report.
---

# Systematic debugging

## Use this skill when

- a test fails
- a command fails
- behavior is inconsistent
- output looks wrong
- a dependency or environment issue appears
- a nearby defect is discovered during another task

## Iron law

No fixes without root-cause investigation first.

## Workflow

1. **Reproduce** — Run the smallest command or test that shows the problem; capture the exact symptom.
2. **Isolate** — Narrow the failing surface to the smallest component, file, or assumption.
3. **Prove cause** — Form hypotheses, test with direct evidence, identify the true root cause (not the nearest visible break).
4. **Fix narrowly** — Change the smallest correct layer; avoid speculative rewrites; do not use retries, skips, or silent fallbacks as substitutes for a real fix.
5. **Validate** — Rerun the smallest relevant check first, then broader checks as needed for regressions.
6. **Report** — Symptom, root cause, fix, validations, residual risk.

## Scope

If you hit a real blocker or integrity issue outside the narrow task, do not work around it silently. Fix the root cause when needed for correctness, or make the dependency explicit and unblock it properly.

## After the fix

Add or update a regression test or verifier when the issue warrants it.

## Forbidden

- Speculative patching
- Quick fixes that hide the real cause
- Multiple simultaneous fixes that destroy attribution
- Declaring success without verification
