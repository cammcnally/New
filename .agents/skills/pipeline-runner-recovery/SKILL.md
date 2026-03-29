---
name: pipeline-runner-recovery
description: Operational run, resume, and recovery workflow for the research pipeline.
---

Use this skill when a run fails after launch or a resume decision is required.

Rules:
- do not change research semantics during operational recovery
- diagnose first using authoritative logs and state
- preserve identical args for resume
- if recovery requires semantic change, stop and reclassify the task

Recovery order:
1. inspect `00_logs/pipeline.log`
2. inspect `06_state/resume_state.json`
3. inspect `06_state/verification.json`
4. determine whether the failure is:
   - environment/runtime
   - missing artifact
   - schema mismatch
   - resume fingerprint mismatch
   - policy/bootstrap mismatch
5. apply operational fix only if it does not change research semantics
6. rerun or resume
7. hand off to verifier
