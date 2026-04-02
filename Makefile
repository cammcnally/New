.PHONY: sync sync-market-data test test-market-data verify verify-market-data cleanup-audit e2e schema-guard docs-sync-guard pit-guard compat-guard bridge-guard verification-guard regenerate check-generated lint all

sync:
	uv sync --group dev --group control-plane --group ingestion --group ingestion-test

sync-market-data: sync

test:
	uv run python -m pytest -q

test-market-data:
	uv run python -m pytest tests/market_data -q

verify:
	uv run python tools/verify_runtime.py
	uv run python tools/verify_tracked_locks.py
	uv run python tools/verify_frozen_surfaces.py
	uv run python tools/audit_file_registry.py

cleanup-audit:
	uv run python tools/audit_file_registry.py
	uv run python tools/report_cleanup_candidates.py

schema-guard:
	uv run python tools/verify_market_data_contracts.py

docs-sync-guard:
	uv run python tools/verify_market_data_docs_sync.py

pit-guard:
	uv run python tools/verify_market_data_pit.py

compat-guard:
	uv run python -c "from tools.verify_market_data import run_compat_guard; run_compat_guard()"

bridge-guard:
	uv run python tools/verify_market_data_bridge.py --panel-path panel_ohlcv_clean.csv --require-manifest

verification-guard:
	uv run python tools/verify_market_data.py

verify-market-data: verification-guard

e2e:
	uv run python tools/run_repo_e2e.py

regenerate:
	uv run python tools/render_cursor_projection.py
	uv run python tools/refresh_loader_manifest.py
	uv run python tools/refresh_bootstrap_locks.py

check-generated:
	uv run python tools/render_cursor_projection.py --check

all: sync test verify check-generated
