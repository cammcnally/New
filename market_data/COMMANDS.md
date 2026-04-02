# Market Data Command Reference

This is the operator-facing command guide for the canonical `market_data` layer.

Use this file together with:

- `README.md`
- `docs/data_contract.md`
- `docs/market_data_roadmap.md`

## Primary Flow

### 1. Run The Authoritative Local E2E Flow

```powershell
make e2e
uv run python tools/run_repo_e2e.py
uv run python tools/run_repo_e2e.py --resume
uv run python tools/run_repo_e2e.py --from-stage verify_market_data
uv run python tools/run_repo_e2e.py --stop-after export_panel
```

Use this path for the fail-closed repo run that:

- syncs required dependency groups
- refreshes canonical market data through the shared raw -> bronze -> silver -> gold -> QA path
- writes `data_lake/manifests/dataset_manifest.json`
- writes coverage, unresolved-identity, quarantine, and final-status reports
- verifies contracts, docs sync, PIT, and bridge integrity
- exports `panel_ohlcv_clean.csv` plus sidecar manifest
- runs `Pipeline.py`
- writes e2e state and status summaries under `data_lake/manifests/`

### 2. Bootstrap The Canonical Data Lake

```powershell
uv run python -m market_data.cli bootstrap --start-date 2010-01-01
```

Use for first-time historical backfill.

Current canonical path:

- raw multi-source ingest
- bronze normalization
- canonical identity build
- canonical prices / enrichments / benchmarks / calendar
- gold marts and QA
- canonical build manifest plus report inventory

### 3. Sync Incremental Updates

```powershell
uv run python -m market_data.cli sync
```

Uses the stored watermark and rebuilds affected downstream tables.

### 4. Check Current State

```powershell
uv run python -m market_data.cli status
```

Reports:

- watermark state
- canonical and compatibility silver row counts
- coverage summary when available

### 5. Run Market-Data Verification

```powershell
uv run python tools/verify_market_data_contracts.py
uv run python tools/verify_market_data_pit.py
uv run python tools/verify_market_data_docs_sync.py
uv run python tools/verify_market_data_bridge.py --panel-path panel_ohlcv_clean.csv --require-manifest
uv run python tools/verify_market_data_bridge.py --panel-path panel_ohlcv_clean.csv --require-manifest --require-benchmark-artifacts
uv run python tools/verify_market_data.py
```

### 6. DVC (narrow export spine)

`dvc.yaml` versions only the exported panel CSV and its sidecar manifest. Recreate tracked outputs with a lake that already passes verification:

```powershell
uv run python tools/run_repo_e2e.py --stop-after export_panel
dvc repro
```

Lake paths under `data_lake/` remain gitignored; they are not DVC outputs. Populate macro PIT silver tables with a valid `FRED_API_KEY` and the FRED vintage ingest → bronze → silver chain (`macro_series.yaml` marks `use_vintages: true` for configured series).

These commands validate:

- required-core identity and schema contracts
- PIT-sensitive daily price and enrichment behavior
- Pandera contracts
- PIT-sensitive macro surfaces
- README, `docs/data_contract.md`, and `market_data/COMMANDS.md` synchronization
- bridge and manifest integrity, including dataset-manifest linkage to the exported sidecar

### 6. Export The Downstream Compatibility Surface

```powershell
uv run python -m market_data.cli export-latest --output panel_ohlcv_clean.csv
Get-ChildItem .\panel_ohlcv_clean_benchmark_surface_daily.parquet
uv run python -m market_data.cli export-asof --asof-date 2026-01-15 --output panel_ohlcv_clean.csv
```

Exports the compatibility panel consumed by `Pipeline.py`.

The export writes or expects:

- `panel_ohlcv_clean.csv`
- `panel_ohlcv_clean.csv.manifest.json`
- non-empty `dataset_build_id`, `export_panel_version_id`, and date range fields in the sidecar
- `dataset_manifest.json` to report `canonical_export_ready = true` and `compatibility_fallback_used = false`
- required-core rows to have survived canonical identity, PIT, and quarantine gates before compatibility labeling

### 7. Run The Downstream Research Pipeline

```powershell
uv run python Pipeline.py --input_panel_csv panel_ohlcv_clean.csv --output_dir pipeline_outputs --strategy_report_template strategy-report.qmd
uv run python Pipeline.py --input_panel_csv panel_ohlcv_clean.csv --output_dir pipeline_outputs --strategy_report_template strategy-report.qmd --resume
```

The input panel sidecar manifest is mandatory. `Pipeline.py` now fails closed when the exported CSV does not have a matching `.manifest.json` with non-empty `dataset_build_id` and `export_panel_version_id`.

When the optional `lineage` dependency group is installed and file-backed lineage emission succeeds, downstream runs also write `pipeline_outputs/06_state/lineage_summary.json` plus file-backed OpenLineage events under `pipeline_outputs/06_state/lineage_events/`.

The canonical Quarto report template path is recorded in downstream artifacts as `strategy_report_template_path` and defaults to `strategy-report.qmd`.

## Manifest Surfaces

Canonical runtime manifests live under `data_lake/manifests/`.

Important files:

- `sync_watermark.json`
- `dataset_manifest.json`
- `final_pass_fail_summary.json`
- `source_coverage_report.json`
- `unresolved_identity_prices_1d.json`
- `quarantine_report.json`

Compatibility export manifests live next to the exported CSV:

- `<panel>.manifest.json`

## Granular Debug Commands

These are useful when working one layer at a time.

### Raw

```powershell
uv run python -m market_data.cli raw --source all --start-date 2024-01-01 --end-date 2024-03-31
```

### Bronze

```powershell
uv run python -m market_data.cli bronze --dataset all --start-date 2024-01-01 --end-date 2024-03-31
```

### Silver

```powershell
uv run python -m market_data.cli silver --dataset all --start-date 2024-01-01 --end-date 2024-03-31
```

### QA

```powershell
uv run python -m market_data.cli qa --all
```

### DuckDB Views

```powershell
uv run python -m market_data.cli register-views
```

Registers canonical and compatibility Parquet datasets as DuckDB views.

## Notes

- `instrument_master` and `instrument_symbol_history` are canonical.
- `security_master` is generated compatibility output.
- required-core data determines export safety.
- optional enrichments may be absent without failing canonical export if manifests report that truthfully.
- `Pipeline.py` remains a downstream compatibility consumer.
- If a material build, bridge, schema, or command surface changes, update `README.md`, `docs/data_contract.md`, and `market_data/COMMANDS.md`.
