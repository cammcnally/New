---
name: control-plane-bootstrap-repair
description: Repair loader-manifest and bootstrap-lock mismatches, then rerun control-plane validation.
---

Use this skill when policy/bootstrap tests fail or `validate-bootstrap` fails.

Required workflow:
1. inspect `control_plane/loader_manifest.json`
2. compare tracked hashes against protected files
3. refresh the loader manifest from the current committed workspace
4. refresh tracked bootstrap locks
5. rerun:
   - `python -m pytest -q tests/test_control_plane_policy.py tests/test_control_plane_runtime.py tests/test_cursor_projection.py`
   - `python tools/control_plane.py trust-policy`
   - `python tools/control_plane.py validate-bootstrap`
6. stop if any control-plane test still fails
7. produce a concise verifier-ready summary with:
   - files changed
   - old/new manifest hash
   - old/new policy fingerprint
   - old/new tracked lock paths
   - remaining blockers
