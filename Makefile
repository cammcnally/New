.PHONY: sync test verify regenerate check-generated lint all

sync:
	uv sync --group dev --group control-plane

test:
	uv run python -m pytest -q

verify:
	uv run python tools/verify_runtime.py
	uv run python tools/verify_tracked_locks.py
	uv run python tools/verify_frozen_surfaces.py

regenerate:
	uv run python tools/render_cursor_projection.py
	uv run python tools/refresh_loader_manifest.py
	uv run python tools/refresh_bootstrap_locks.py

check-generated:
	uv run python tools/render_cursor_projection.py --check

all: sync test verify check-generated
