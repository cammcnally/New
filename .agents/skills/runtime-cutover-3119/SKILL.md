---
name: runtime-cutover-3119
description: Exact Python 3.11.9 cutover workflow for this repository.
---

Use this skill only after the current control-plane state is green and committed.

Required order:
1. patch `.python-version`
2. patch `pyproject.toml`
3. patch runtime guards in `Pipeline.py`
4. patch runtime guards in control-plane code/tests
5. rebuild `.venv` under Python 3.11.9
6. reinstall dependencies
7. run scoped tests
8. run full pytest
9. rerender cursor projection
10. refresh tracked locks
11. run smoke Tier 1
12. run deterministic verification
13. stop if any blocker remains
