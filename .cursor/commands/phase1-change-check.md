# phase1-change-check

This command is a local compatibility shim.
Canonical behavior lives in `AGENTS.md` and `python tools/control_plane.py phase1-change-check`.

Protected-path matching is slash-normalized so Windows and repo-relative paths classify the same way.

Supported classifications:

- `behavior_preserving`
- `spec_implementing`
- `spec_changing`
- `policy_changing`
- `operational_only`
- `test_only`
- `docs_only`

Example:

```powershell
.\.venv\Scripts\python.exe tools/control_plane.py phase1-change-check --classification policy_changing --justification "Touches control_plane/orchestrator.py" --expected-file control_plane/orchestrator.py
```
