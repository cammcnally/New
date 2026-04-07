Status: Non-authoritative work artifact
Canonical authority:
- AGENTS.md
- docs/data_contract.md
- docs/phase1-research-spec.md
- docs/phase1-execution-roadmap.md

# Benchmark Architecture Implementation Plan

> Historical implementation plan retained for sequencing traceability. Use the canonical surfaces above plus `README.md` and `market_data/COMMANDS.md` for live authority.

**Goal:** Build the first compliant benchmark-mapping layer for the repo: canonical benchmark definitions and price surfaces, SEC_SIC_4-based classification history, deterministic SPY-plus-sector benchmark mapping, benchmark side exports for `Pipeline.py`, and fail-closed verification without redefining frozen Phase 1 research semantics.

**Architecture:** Keep `market_data` as the sole benchmark authority. Harden the existing benchmark registry and benchmark price surfaces first, then add a narrow SEC identity bootstrap for `CIK`, build `instrument_classification_history` from SEC filing-time SIC evidence, derive `instrument_benchmark_map` from canonical classification plus a repo-owned crosswalk, export read-only benchmark artifacts, and let `Pipeline.py` consume those artifacts without local inference.

**Tech Stack:** Python 3.11.9, Polars, Pandera, Click CLI (`market_data.cli`), Parquet, YAML configs, existing `market_data` raw/bronze/silver/orchestration layers, `.venv\Scripts\python.exe -m pytest`

---

## Spec Inputs

- **Related work artifact:** `docs/COMBINED_IMPLEMENTATION_DIRECTIVE_v1.md` (benchmark patch + alphalens factor-diagnostics; implementation order **F**).
- Historical checklist: `docs/benchmark_architecture_first_compliant_checklist.md`
- Market-data contract authority: `docs/data_contract.md`
- Repo architecture and operator workflow: `README.md`
- Phase 1 governance: `docs/phase1-research-spec.md`
- Phase 1 work order: `docs/phase1-execution-roadmap.md`

## Codebase Reality To Plan Around

- `benchmark_definitions` is `canonical_live`; adding **`benchmark_id`** (stable key) and tightening role validators is **breaking contract evolution**—ship schema, builders, validators, tests, and docs together.
- `benchmark_prices_daily` is built as the **sid-keyed silver** shape (`BENCHMARK_PRICES_DAILY_SILVER`); Pandera validates that shape. The **instrument-keyed** `BENCHMARK_PRICES_DAILY` dict in `schema_registry.py` (with `adj_close`) is **legacy/deprecated** for new work—do not add downstream dependencies on it. **No `adj_close`** on the canonical unadjusted silver benchmark table; adjusted/total-return lives in a **separate derived surface** (see directive B6–B7).
- `benchmark_definitions` already exists with (`group`, `symbol`, `benchmark_type`, `semantic_role`, `default_usage`, `canonical_or_proxy`) and will gain **`benchmark_id`** as the long-term join key; **`symbol`** stays required and unique.
- `instrument_classification_history` and `instrument_benchmark_map` exist only as deferred contracts; no builders exist yet.
- `normalize_sec_submissions.py` currently drops the company-level SEC `sic` field even though the SEC client fetches it.
- The repo currently has no usable `CIK` bootstrap source in canonical identity. `instrument_master` does not carry `CIK`, `security_master` explicitly writes `cik = NULL`, and the current SEC raw ingests have no reliable source of CIKs.
- `build_filings.py` and `build_fundamentals_reported.py` currently inner-join SEC bronze data through `security_master.cik`, so they will remain effectively empty unless the CIK seam is repaired or those joins are repointed.
- `normalize_sec_companyfacts.py` preserves taxonomy and concept rows, so a DEI-based SIC lookup can be attempted there, but there is no dedicated DEI SIC extraction yet.
- `Pipeline.py` already uses the word `benchmark` for statistical baselines (`deflated_sharpe_benchmark`, `benchmark_base_rate_metrics`), which must remain semantically distinct from market benchmark artifacts.
- Return **basis** must be explicit everywhere (unadjusted close-to-close vs adjusted total return, etc.); the canonical silver benchmark price table stays **unadjusted OHLCV** only.
- `tools/verify_market_data_contracts.py` must **enforce** `benchmark_prices_daily` whenever that dataset is present (no half-strict architecture vs verifier mismatch). `run_all.py` manifest coverage for benchmark/mapping datasets remains to be aligned with export readiness signals.
- `tools/verify_market_data_bridge.py` validates the panel CSV plus its `export_panel` sidecar only. New benchmark side artifacts need a defined manifest/discovery model without breaking the existing bridge contract.
- `_ensure_benchmark_roles` in `pandera_contracts.py` currently couples benchmark validation to context rows such as `^VIX` and `VIXY`, so any registry cleanup must preserve or replace that rule atomically.

## Default Planning Decisions

These defaults resolve current repo gaps without broadening scope:

1. Add a narrow SEC ticker-to-CIK bootstrap source before SEC classification work starts.
2. Propagate bootstrap CIK coverage into the compat identity seam by populating `security_master.cik` from the new ticker-to-CIK source unless a narrower join-path replacement proves cleaner.
3. Preserve the company-level `sic` value from SEC submissions normalization so it is available as the first compliant fallback source when DEI SIC is absent.
4. Attempt DEI precedence by querying normalized SEC companyfacts for `taxonomy = "dei"` and `concept = "EntityPrimarySicNumber"` if present.
5. If DEI SIC is absent for an issuer / filing, fall back to the company-level SIC carried in SEC submissions and record that fallback in `source` / `source_reference`.
6. Keep `DFF` macro-native and outside the OHLCV benchmark registry.
7. Keep `panel_ohlcv_clean.csv` unchanged; add side artifacts instead of bloating the core panel contract.
8. Do not let `Pipeline.py` infer sectors or benchmark mappings locally.
9. Use a stable **`benchmark_id` column on `benchmark_definitions`** as the canonical benchmark key (derived deterministically from config, e.g. `bm_SPY`, `bm_VIX`); **`instrument_benchmark_map.market_benchmark_id` / `sector_benchmark_id`** reference that id—not raw symbol strings as the only key, and not ETF `instrument_id` unless explicitly materialized through `benchmark_definitions`.
10. Keep `^VIX` and `VIXY` as explicit context rows unless `_ensure_benchmark_roles` is revised in the same change slice.
11. Keep `canonical_export_ready` scoped to the existing panel bridge and add a separate manifest-ready signal for benchmark side artifacts rather than silently redefining panel export safety.

## Task 1: Bootstrap SEC Identity Inputs And Classification Config

**Files:**
- Create: `configs/classification_sources.yaml`
- Create: `configs/sec_sic4_to_sector_etf.yaml`
- Create: `market_data/common/classification.py`
- Create: `market_data/raw/ingest_sec_company_tickers.py`
- Create: `market_data/bronze/normalize_sec_company_tickers.py`
- Modify: `market_data/clients/sec_client.py`
- Modify: `market_data/orchestration/run_raw.py`
- Modify: `market_data/orchestration/run_bronze.py`
- Modify: `market_data/silver/compat_security_master.py`
- Modify: `market_data/silver/build_filings.py`
- Modify: `market_data/silver/build_fundamentals_reported.py`
- Modify: `market_data/COMMANDS.md`
- Test: `tests/market_data/test_classification_source_policy.py`
- Test: `tests/market_data/test_sec_sic_crosswalk.py`
- Test: `tests/market_data/test_sec_company_tickers_bootstrap.py`

- [ ] **Step 1: Write the failing tests for classification policy, crosswalk validation, and CIK bootstrap normalization**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_classification_source_policy.py tests/market_data/test_sec_sic_crosswalk.py tests/market_data/test_sec_company_tickers_bootstrap.py -v
```

Expected: FAIL because the config files, helper module, and SEC ticker bootstrap path do not exist yet.

- [ ] **Step 2: Create frozen config files with fail-closed fields**

Add:

- `classification_sources.primary.source_name = SEC_EDGAR_XBRL`
- `classification_sources.primary.classification_system = SEC_SIC_4`
- `classification_sources.primary.field_precedence = [dei:EntityPrimarySicNumber, filing_header_sic]`
  - note: the fallback source is the company-level SIC carried on SEC submissions JSON even though the policy label remains `filing_header_sic` for continuity with the directive text
- `classification_sources.primary.missing_policy = keep_missing`
- `sec_sic4_to_sector_etf.mapping_rule_version`
- `sec_sic4_to_sector_etf.classification_system = SEC_SIC_4`
- exact/family SIC mappings only to `XLC XLY XLP XLE XLF XLV XLI XLB XLRE XLK XLU`

- [ ] **Step 3: Implement `market_data/common/classification.py` loaders and pure helpers**

Implement:

- `load_classification_source_policy()`
- `load_sec_sic_crosswalk()`
- `normalize_sic_code()`
- `resolve_sector_etf_from_sic()`
- `build_effective_windows()`
- `validate_non_overlapping_windows()`

Rules:

- strict SIC normalization
- explicit invalid-input rejection
- deterministic window generation
- no builder-local duplication of these rules later

- [ ] **Step 4: Add SEC ticker-to-CIK bootstrap support**

Implement:

- SEC client fetch for SEC ticker-to-CIK source
- raw ingest for that source
- bronze normalization with stable columns for `ticker`, `cik`, and any source metadata needed for audit
- raw/bronze orchestration registration so the source can be run through existing CLI flows
- propagation of the new CIK mapping into `security_master.cik` or an equivalent shared join path so existing SEC silver builders no longer silently depend on null CIKs

Default source choice:

- use SEC `company_tickers.json` or equivalent SEC-maintained ticker-to-CIK mapping as the bootstrap authority for fetching submissions/companyfacts

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_classification_source_policy.py tests/market_data/test_sec_sic_crosswalk.py tests/market_data/test_sec_company_tickers_bootstrap.py -v
```

Expected: PASS

- [ ] **Step 6: Smoke the new raw and bronze bootstrap path**

Run:

```powershell
uv run python -m market_data.cli raw --source sec --start-date 2024-01-01 --end-date 2024-01-31
uv run python -m market_data.cli bronze --dataset all --start-date 2024-01-01 --end-date 2024-01-31
```

Expected: SEC raw/bronze paths complete without relying on `C:` state or an existing `security_master.cik`.

Implementation note:

- treat this as a real bootstrap/network smoke, not a tiny fixture smoke; SEC source size and rate limits may make the CLI smoke slower than a pure unit test bundle

## Task 2: Make Benchmark Authority Surfaces Mapping-Ready

**Files:**
- Modify: `configs/benchmarks.yaml`
- Modify: `market_data/common/benchmarks.py`
- Modify: `market_data/common/schema_registry.py`
- Modify: `market_data/common/pandera_contracts.py`
- Modify: `market_data/silver/build_benchmark_definitions.py`
- Modify: `market_data/silver/build_benchmark_prices_daily.py`
- Modify: `market_data/silver/build_prices_1d_unadjusted.py`
- Modify: `tools/verify_market_data_contracts.py`
- Modify: `tests/market_data/test_benchmark_definitions_builder.py`
- Modify: `tests/market_data/test_pandera_contracts.py`
- Test: `tests/market_data/test_benchmark_prices_daily_builder.py`

- [ ] **Step 1: Write failing tests for benchmark registry semantics and benchmark price output shape**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_benchmark_definitions_builder.py tests/market_data/test_pandera_contracts.py tests/market_data/test_benchmark_prices_daily_builder.py -v
```

Expected: FAIL because current benchmark outputs are still legacy-shaped and deferred.

- [ ] **Step 2: Migrate benchmark registry semantics without adding a second authority**

Implement in config/loader/builder:

- `SPY` is the only primary market benchmark
- the 11 sector ETFs are the only canonical sector layer
- context series remain context-only
- `DFF` does not appear in the OHLCV benchmark registry
- `benchmark_definitions` exposes stable `benchmark_id` values that later builders can reference deterministically

Default identifier rule for this repo:

- `benchmark_id` is sourced from the canonical `instrument_id` of the seeded benchmark instrument in `instrument_master`
- `market_benchmark_id` and `sector_benchmark_id` in later mapping artifacts resolve to this canonical benchmark instrument ID

Validator note:

- keep `^VIX` and `VIXY` as context rows or update `_ensure_benchmark_roles` in the same slice; do not leave registry/config and validator expectations out of sync

- [ ] **Step 3: Decide and encode benchmark price convention explicitly**

Default choice for this plan:

- make benchmark return convention explicit and consistent with the downstream compatibility export
- if `adj_close` is available from the upstream source, preserve it
- if the repo cannot yet provide adjusted prices for all benchmark-capable sources, keep `adj_close` nullable during migration and document the active benchmark return basis explicitly rather than fabricating adjusted values
- keep the first compliant benchmark return basis aligned with the repo's actual downstream price basis; do not silently switch market-relative calculations onto a different adjustment convention than the exported panel uses

Implementation note:

- if upstream raw/bronze daily price flows need a small extension to preserve adjusted-close fields for benchmark instruments, make that extension in this task
- choose one canonical benchmark price schema and retire the duplicate sid-only silver shape cleanly; do not let both benchmark price contracts persist as competing authorities

- [ ] **Step 4: Upgrade `benchmark_prices_daily` to a mapping-ready surface**

Target fields:

- stable `benchmark_id`
- symbol
- date
- price columns
- source metadata
- timestamp metadata suitable for audit and export

Do not add security-level assignment logic here.

Verification note:

- add `benchmark_prices_daily` to `tools/verify_market_data_contracts.py` once the migrated contract is ready so the table is no longer invisible to the main contract verifier

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_benchmark_definitions_builder.py tests/market_data/test_pandera_contracts.py tests/market_data/test_benchmark_prices_daily_builder.py -v
```

Expected: PASS

## Task 3: Build Classification History From SEC Evidence

**Files:**
- Modify: `market_data/raw/ingest_sec_submissions.py`
- Modify: `market_data/raw/ingest_sec_companyfacts.py`
- Modify: `market_data/bronze/normalize_sec_submissions.py`
- Modify: `market_data/bronze/normalize_sec_companyfacts.py`
- Create: `market_data/silver/build_instrument_classification_history.py`
- Modify: `market_data/silver/compat_security_master.py`
- Modify: `market_data/orchestration/run_silver.py`
- Modify: `market_data/common/schema_registry.py`
- Modify: `market_data/common/pandera_contracts.py`
- Modify: `tests/market_data/test_pandera_contracts.py`
- Test: `tests/market_data/test_build_instrument_classification_history.py`

- [ ] **Step 1: Write failing tests for SIC precedence, normalization, and window generation**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_build_instrument_classification_history.py tests/market_data/test_pandera_contracts.py -v
```

Expected: FAIL because the classification builder and final contract shape do not exist yet.

- [ ] **Step 2: Preserve filing-header SIC in normalized SEC submissions**

Extend normalized submissions rows to carry:

- raw `sic`
- any source reference fields needed for audit
- timestamps needed to derive `effective_from`

Reason:

- the current client fetches `sic`, but the bronze normalizer currently drops it

Clarification:

- the fallback SIC carried in submissions is company-level SEC SIC from the submissions payload; do not overstate it as a richer historical classification than it really is

- [ ] **Step 3: Make raw SEC ingests consume the new CIK bootstrap source**

Update SEC raw ingests so they resolve CIKs from the new SEC ticker bootstrap path rather than a nonexistent `security_master.cik` surface.

Default join-path choice for this plan:

- populate `security_master.cik` from the new bootstrap source so existing SEC silver builders and the new classification builder share one CIK join path

- [ ] **Step 4: Implement the classification history builder**

Builder responsibilities:

- resolve instrument to ticker to CIK deterministically
- query DEI SIC first from normalized companyfacts when present
- fall back to company-level SIC from normalized submissions
- normalize into `SEC_SIC_4`
- map sector label/code via the repo-owned crosswalk
- collapse repeated classifications into non-overlapping effective windows
- emit auditable `source` and `source_reference`

Schema direction:

- add `source_reference`
- replace or align timestamp naming with a directive-compliant `asof_timestamp`
- preserve extra industry columns as nullable only if that avoids a larger unrelated refactor
- update the classification-system enum set so the emitted value is explicitly valid for the first compliant `SEC_SIC_4` implementation

- [ ] **Step 5: Register the builder in `run_silver.py`**

Add:

- `instrument_classification_history` to `SILVER_BUILD_ORDER`
- the module mapping in `_BUILDERS`

- [ ] **Step 6: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_build_instrument_classification_history.py tests/market_data/test_pandera_contracts.py -v
```

Expected: PASS

- [ ] **Step 7: Smoke the new silver dataset through the real CLI**

Run:

```powershell
uv run python -m market_data.cli silver --dataset instrument_classification_history --start-date 2024-01-01 --end-date 2024-03-31 --full-refresh
```

Expected: the dataset builds through the existing silver orchestration path.

## Task 4: Build Deterministic Instrument Benchmark Mapping And Fail-Closed Verification

**Files:**
- Create: `market_data/silver/build_instrument_benchmark_map.py`
- Modify: `market_data/common/schema_registry.py`
- Modify: `market_data/common/pandera_contracts.py`
- Modify: `tools/verify_market_data_contracts.py`
- Modify: `market_data/orchestration/run_silver.py`
- Modify: `market_data/orchestration/run_all.py`
- Modify: `tests/market_data/test_pandera_contracts.py`
- Modify: `tests/market_data/test_verify_market_data_contracts.py`
- Test: `tests/market_data/test_build_instrument_benchmark_map.py`
- Test: `tests/market_data/test_verify_market_data_contracts_benchmark_mapping.py`

- [ ] **Step 1: Write failing tests for benchmark map semantics and verifier failures**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_build_instrument_benchmark_map.py tests/market_data/test_verify_market_data_contracts.py tests/market_data/test_verify_market_data_contracts_benchmark_mapping.py -v
```

Expected: FAIL because the builder, new schema shape, and stricter verifier rules do not exist yet.

- [ ] **Step 2: Migrate `instrument_benchmark_map` to the first compliant shape**

Target fields:

- `instrument_id`
- `effective_from`
- `effective_to`
- `market_benchmark_id`
- `sector_benchmark_id`
- `mapping_rule_version`
- `mapping_source`
- `asof_timestamp`

Retire legacy-only semantics such as:

- `mapping_type`
- `benchmark_instrument_id`
- `mapping_confidence`
- `created_at_utc`

unless a compatibility bridge is explicitly needed and documented.

Naming rule:

- pick one window-field naming scheme and update schema, pandera, verifier, builders, and docs atomically; do not leave `_date` and non-`_date` variants mixed across surfaces

- [ ] **Step 3: Implement the benchmark map builder**

Behavior:

- every eligible equity gets `market_benchmark_id = SPY`
- `sector_benchmark_id` comes only from canonical classification plus the crosswalk
- missing authoritative classification yields an explicit `NULL` sector mapping
- benchmark IDs are resolved from canonical benchmark definitions, not hard-coded symbol output

- [ ] **Step 4: Tighten verifier behavior**

Extend verifier logic to fail closed on:

- missing SPY market coverage
- invalid sector benchmark IDs
- non-overlapping window violations
- benchmark IDs absent from the registry
- sector mappings that extend beyond classification support
- benchmark price surfaces missing from the main contract verification path

- [ ] **Step 5: Wire manifest and required-core handling**

Update `run_all.py` so:

- classification history and benchmark map stop being treated as deferred once implemented
- manifests include both surfaces
- benchmark prices are included in dataset inventory once the migrated contract is active
- missing canonical benchmark-mapping surfaces are explicit failures in benchmark-compliant mode

Manifest policy for this repo:

- keep `canonical_export_ready` scoped to the current panel bridge
- add a separate benchmark-readiness signal in `dataset_manifest.json` for benchmark side artifacts and mapping coverage
- do not silently redefine existing panel-export safety semantics while adding benchmark-compliance gates

- [ ] **Step 6: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_build_instrument_benchmark_map.py tests/market_data/test_verify_market_data_contracts.py tests/market_data/test_verify_market_data_contracts_benchmark_mapping.py -v
```

Expected: PASS

- [ ] **Step 7: Smoke the mapping builder and verifier**

Run:

```powershell
uv run python -m market_data.cli silver --dataset instrument_benchmark_map --start-date 2024-01-01 --end-date 2024-03-31 --full-refresh
uv run python tools/verify_market_data_contracts.py
```

Expected: the map builds and the verifier reports compliant benchmark mapping surfaces.

## Task 5: Export Benchmark Side Artifacts Without Changing The Panel Contract

**Files:**
- Modify: `market_data/bridge/export_pipeline_panel.py`
- Modify: `market_data/common/manifest.py`
- Modify: `market_data/orchestration/run_all.py`
- Modify: `market_data/orchestration\e2e.py`
- Modify: `tools/verify_market_data_bridge.py`
- Modify: `tools/verify_market_data.py`
- Modify: `tools/run_repo_e2e.py`
- Modify: `market_data/COMMANDS.md`
- Test: `tests/market_data/test_export_benchmark_surface.py`

- [ ] **Step 1: Write failing tests for benchmark side exports**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_export_benchmark_surface.py -v
```

Expected: FAIL because benchmark side artifacts are not exported yet.

- [ ] **Step 2: Export benchmark surfaces separately from `panel_ohlcv_clean.csv`**

Export at minimum:

- market / sector / risk-free surface, e.g. `benchmark_surface_daily.parquet`
- mapping surface, e.g. `instrument_benchmark_map.parquet` or a manifest-linked equivalent

Minimum market/risk-free fields:

- `date`
- `spy_ret_1d`
- `dff_daily_rate`

Optional after mapping exists:

- sector ETF returns

Return-basis note:

- whichever benchmark return basis is active must be documented in the exported artifact metadata so `Pipeline.py` knows whether returns derive from `close`, `adj_close`, or another explicitly named basis

- [ ] **Step 3: Make artifacts manifest-discoverable**

Update export metadata so the benchmark side artifacts are discoverable by fixed path or manifest and do not require `Pipeline.py` to infer filenames.

Default discovery rule for this repo:

- keep the existing `export_panel` sidecar manifest valid and panel-focused
- add benchmark artifact paths to `dataset_manifest.json` under stable report/artifact keys
- optionally include a `benchmark_artifacts` list in the panel export sidecar manifest as additive metadata only
- extend `verify_market_data_bridge.py` with an opt-in benchmark-artifact check or add a sibling verifier; do not break the existing panel-only bridge contract by default

- [ ] **Step 4: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_export_benchmark_surface.py -v
```

Expected: PASS

## Task 6: Make `Pipeline.py` A Read-Only Benchmark Consumer

**Files:**
- Modify: `Pipeline.py`
- Modify: `tools/phase1_sanity_check.py`
- Modify: `README.md`
- Modify: `tools/verify_market_data_bridge.py`
- Test: `tests/test_pipeline_benchmark_consumption.py`

- [ ] **Step 1: Write failing tests for benchmark artifact loading and explicit missing-artifact failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_pipeline_benchmark_consumption.py -v
```

Expected: FAIL because `Pipeline.py` does not yet load canonical benchmark side artifacts.

- [ ] **Step 2: Add first compliant benchmark consumption mode**

Implement:

- load SPY benchmark series from canonical side artifact
- optionally load DFF daily rate
- compute evaluation-only diagnostics:
  - active return vs SPY
  - tracking error vs SPY
  - information ratio vs SPY
  - beta/correlation vs SPY
  - optional excess-return metrics using DFF

Default artifact discovery rule:

- `Pipeline.py` reads benchmark artifact paths from manifest metadata produced by the export layer; it must not guess paths from filenames or directory scans

- [ ] **Step 3: Keep sector-relative logic gated**

Allow sector-relative logic only when:

- canonical mapping artifacts exist
- verifier-approved mapping surfaces are present

Do not:

- infer sector ETF from current metadata
- rebuild benchmark mapping inside `Pipeline.py`
- read raw SEC classification directly

- [ ] **Step 4: Clarify existing statistical benchmark terminology**

Rename or document internal statistical `benchmark` usages as needed so they are not confused with economic benchmark artifacts.

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_pipeline_benchmark_consumption.py -v
```

Expected: PASS

## Task 7: Docs, Commands, And Final Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/data_contract.md`
- Modify: `docs/benchmark_architecture_first_compliant_checklist.md`
- Modify: `market_data/COMMANDS.md`
- Modify: `tests/market_data/test_verify_market_data_contracts.py`
- Modify: `tools/verify_market_data_bridge.py`
- Modify: `tools/verify_market_data.py`

- [ ] **Step 1: Update docs from deferred to active semantics**

Update docs so they say, explicitly:

- `SPY` is the universal market benchmark
- the 11 ETFs are the canonical sector layer
- `DFF` remains macro-native
- SEC SIC to sector ETF is the first compliant approximation layer
- sector-relative validity depends on canonical mapping artifacts actually existing

- [ ] **Step 2: Update command docs to reflect real runnable paths**

Prefer actual CLI/verifier entrypoints already used by the repo:

```powershell
uv run python -m market_data.cli silver --dataset instrument_classification_history --start-date 2024-01-01 --end-date 2024-03-31 --full-refresh
uv run python -m market_data.cli silver --dataset instrument_benchmark_map --start-date 2024-01-01 --end-date 2024-03-31 --full-refresh
uv run python tools/verify_market_data_contracts.py
uv run python -m market_data.cli export-latest --output panel_ohlcv_clean.csv
uv run python Pipeline.py --input_panel_csv panel_ohlcv_clean.csv --output_dir pipeline_outputs
```

Also document:

- whether benchmark side artifacts are verified through `verify_market_data_bridge.py --require-benchmark-artifacts` or a sibling benchmark-export verifier
- that DVC remains narrow around the panel export unless intentionally expanded later

- [ ] **Step 3: Run focused regression bundle**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/market_data/test_classification_source_policy.py tests/market_data/test_sec_sic_crosswalk.py tests/market_data/test_sec_company_tickers_bootstrap.py tests/market_data/test_benchmark_definitions_builder.py tests/market_data/test_benchmark_prices_daily_builder.py tests/market_data/test_build_instrument_classification_history.py tests/market_data/test_build_instrument_benchmark_map.py tests/market_data/test_verify_market_data_contracts.py tests/market_data/test_verify_market_data_contracts_benchmark_mapping.py tests/test_pipeline_benchmark_consumption.py -v
```

Expected: PASS

- [ ] **Step 4: Run final repo-level acceptance checks**

Run:

```powershell
uv run python tools/verify_market_data_contracts.py
uv run python tools/verify_market_data.py
uv run python -m market_data.cli export-latest --output panel_ohlcv_clean.csv
uv run python Pipeline.py --input_panel_csv panel_ohlcv_clean.csv --output_dir pipeline_outputs
```

Expected:

- classification history builds from SEC evidence
- benchmark map builds deterministically
- every eligible equity maps to SPY
- rows without authoritative classification have `NULL` sector mapping
- benchmark side artifacts are discoverable
- `Pipeline.py` consumes them without local inference
- the existing panel bridge remains valid and separately verifiable

## Task 8: Alphalens-Reloaded Factor-Diagnostics Layer (Directive A + Order F.7)

**Related work-artifact reference:** `docs/COMBINED_IMPLEMENTATION_DIRECTIVE_v1.md` section **A**.

**Files:**

- Create: `analysis/alpha_diagnostics/__init__.py`, `config.py`, `schemas.py`, `build_factor_data.py`, `run_alphalens.py`, `export_alphalens_artifacts.py`
- Modify: `pyproject.toml` (dependency group `analysis` with pinned `alphalens-reloaded`)
- Modify: `AGENTS.md` policy allowlist entry for `alphalens-reloaded` when required by dependency policy
- Modify: `strategy-report.qmd` (optional params-driven ingestion of `reports/alpha_diagnostics/...` artifacts; sections: Model diagnostics, Quantile return analysis, IC stability, Turnover/rank persistence, Group/sector decomposition)
- Test: `tests/analysis/test_alpha_diagnostics_export.py` (synthetic scores + prices; asserts parquet/json/png outputs and hard failure on broken alignment)

**Role:** Cross-sectional factor evaluation only—**not** replacement for the backtest engine, CPCV, execution model, or economic benchmark registry logic.

- [ ] **Step 1:** Pin `alphalens-reloaded` and document `uv sync --group analysis` for local/CI jobs that run diagnostics.
- [ ] **Step 2:** Implement deterministic `factor_data` build from repo-aligned `date` / `asset` / `score` + wide or long prices; **fail closed** on alignment errors.
- [ ] **Step 3:** Run IC, quantile returns, turnover, rank autocorrelation, optional **by_group** only when canonical group labels are supplied.
- [ ] **Step 4:** Write all machine-readable artifacts and chart exports under `reports/alpha_diagnostics/<strategy_name>/<run_id>/` plus `manifest.json` (no notebook-only outputs).
- [ ] **Step 5:** Wire Quarto to consume exported paths when provided (e.g. Quarto `params`).

## Notes For The Implementer

- Treat the missing CIK bootstrap as a real prerequisite, not a nice-to-have.
- Keep the benchmark work behavior-preserving for frozen Phase 1 downstream semantics.
- Do not broaden the correction boundary, change scorecard semantics, or alter existing research claims while adding benchmark diagnostics.
- Keep `DFF` on the macro path even if it is exported next to benchmark returns downstream.
- If a field-name migration is required in schemas/contracts, update docs/tests/verifiers in the same slice so the repo never sits in an ambiguous half-state.
