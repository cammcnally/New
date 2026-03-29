---
name: artifact-schema-inspector
description: Artifact schema and completeness inspection for pipeline outputs and verifier evidence.
---

Use this skill when artifacts must be checked for completeness or schema drift.

Minimum checks:
- required file exists
- required columns/keys exist
- semantic version fields are present
- implementation_status and verification_stage_reached are populated
- no legacy root-level log/resume artifacts were reintroduced
- stitched daily returns and strategy scorecards align with Phase 1 definitions
