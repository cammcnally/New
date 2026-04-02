# Market Data Contract

## Purpose

This document is the normative contract for the canonical market-data layer.

From this point onward:

- `market_data` is the source of truth.
- `Pipeline.py` is a downstream Phase 1 consumer of a derived/exported compatibility surface.
- older panel-first assumptions are stale documentation, not architecture.
- frozen downstream research semantics remain governed by `docs/phase1-research-spec.md` and `docs/phase1-execution-roadmap.md`.

## Layer Model

The repository has two explicit layers:

1. Canonical market-data platform
2. Downstream research pipeline

The canonical market-data platform owns:

- instrument identity
- source symbol mapping
- canonical prices and PIT-sensitive upstream data
- benchmark semantics
- manifests and verification
- compatibility export generation

The downstream research pipeline owns:

- feature engineering
- labels
- walk-forward validation
- model training and calibration
- threshold search
- portfolio simulation
- Phase 1 robustness reporting
- promotion logic

## Contract Status Vocabulary

Use these statuses consistently in docs, manifests, and verifier output:

- `canonical_live`: authoritative today and expected to satisfy runtime contracts
- `compatibility_only`: retained only for legacy consumers
- `generated`: derived output, never hand-authored
- `contract_defined_deferred`: contract semantics are defined, but the surface is not yet authoritative enough to enable dependent logic
- `deferred_component`: intentionally incomplete and reported as deferred in manifests/status outputs

## Source-Of-Truth Rules

- `instrument_master` is canonical.
- `instrument_symbol_history` is canonical.
- `instrument_id` is the canonical identity key.
- ticker/symbol labels are compatibility labels, never economic identity.
- `security_master` is compatibility only.
- `security_master` must be generated from canonical identity tables only.
- no new code may write authoritative business logic directly to `security_master`.
- any remaining `security_master` consumer is transitional and must be treated as read-only compatibility logic.

## Required-Core Versus Optional-Enrichment

The canonical market-data layer distinguishes between two classes of data:

### Required-Core

Required-core surfaces are mandatory for canonical export readiness:

- canonical instrument identity
- source-namespace-aware symbol mapping
- canonical OHLCV
- session and trade-date correctness
- benchmark/reference coverage required by active downstream logic
- export-safe compatibility labeling

Rules:

- required-core failures may block canonical export
- required-core rows that fail identity, schema, or PIT rules must be quarantined or excluded
- unresolved required-core rows must never be silently exported

### Optional-Enrichment

Optional-enrichment surfaces improve downstream context but do not redefine canonical export readiness by themselves:

- SEC / EDGAR filings and fundamentals
- FRED / ALFRED macro vintages and as-of materializations
- other deferred enrichments that remain outside the minimum required-core contract

Rules:

- optional-enrichment absence must not fail an otherwise safe canonical export
- when optional enrichments are present, they must still satisfy their own schema and PIT rules
- export schemas must stay stable when optional enrichment coverage changes
- missing optional enrichments must remain null and flagged rather than backfilled unsafely

## Canonical Surface Inventory

| Surface | Status | Contract role | Notes |
| ------ | ------ | ------ | ------ |
| `instrument_master` | `canonical_live` | Canonical identity | Authority for identity, asset/security type, canonical symbol, exchange, and active state |
| `instrument_symbol_history` | `canonical_live` | Canonical symbol mapping | Authority for source symbol history and effective windows |
| `prices_1d_unadjusted` | `canonical_live` | Canonical daily price surface | Instrument-ID keyed daily OHLCV surface for downstream canonical builds and exports |
| `benchmark_definitions` | `canonical_live` | Canonical benchmark catalog | Versioned semantic-role catalog generated from benchmark configuration and validated for canonical versus proxy rules |
| `macro_observations_vintage` | `canonical_live` | PIT vintage storage | Must retain availability timestamps and reject future-available joins |
| `macro_asof_daily` | `canonical_live` | PIT materialization | Must choose the latest eligible vintage under the documented as-of rule |
| `instrument_benchmark_map` | `contract_defined_deferred` | Benchmark mapping | Semantics are fixed; historical completeness is still deferred |
| `instrument_classification_history` | `contract_defined_deferred` | Date-effective classification | Required before sector-relative logic may be enabled |
| `security_master` | `compatibility_only` + `generated` | Legacy identity adapter | Derived only from canonical identity surfaces |
| export panel contract | `compatibility_only` + `generated` | `Pipeline.py` compatibility bridge | Versioned export with manifest and verification refs |

## Canonical Identity Laws

- primary keys must be unique by contract
- date-effective windows must not overlap for the same logical entity
- open-ended windows must remain auditable
- required fields are contractual, not inferred from current data
- enum domains are explicit and version-controlled

This applies at minimum to:

- `instrument_master`
- `instrument_symbol_history`
- `instrument_classification_history`
- `instrument_benchmark_map`

## Price Sanity Laws

For canonical daily OHLCV surfaces:

- `low <= open`
- `low <= close`
- `low <= high`
- `high >= open`
- `high >= close`
- volume must not be negative
- duplicate primary keys are invalid

These are hard contract failures.

## PIT Laws

The repo enforces two distinct PIT disciplines and both must hold before data is exported downstream:

- `entity-PIT`: the row must resolve to the correct economic entity through canonical identity plus a valid effective symbol/entity mapping for that source and date
- `time-PIT`: the row or enrichment must only become available after its documented public-availability or session-cutoff time

Both are required. Time-safe data attributed to the wrong entity is still invalid, and correctly attributed data joined before public availability is still invalid.

### Entity-PIT Law

For canonical price or identity-bearing rows:

- raw source symbols must be preserved for audit
- canonical attribution must resolve through `instrument_id`
- source symbol mapping must be date-effective for the specific source namespace
- current-symbol fallback through compatibility surfaces is not allowed in canonical mode
- unresolved rows must be quarantined and reported, not silently attributed

### Time-PIT Law

For PIT-sensitive joins and exports:

- daily prices use the canonical market-session close as the as-of cutoff
- macro vintages use `available_from_ts_utc`
- fundamentals use public availability / acceptance timing, not fiscal period end alone
- later revisions must not backfill earlier as-of dates
- optional enrichments that miss time-PIT eligibility remain null and flagged

### Domain-Specific PIT Requirements

The dual `entity-PIT` and `time-PIT` laws apply differently by domain and must stay explicit:

#### Price PIT

A canonical price row is export-safe only if:

- the raw source symbol is preserved for audit
- the row resolves to canonical `instrument_id` through date-effective source-symbol history
- the trade date falls inside the valid mapping window
- no current-symbol fallback is used in canonical attribution
- session timestamps align with the canonical trading calendar and market close

#### SEC / Fundamentals PIT

A canonical SEC or fundamentals row is export-safe only if:

- the filing or fact resolves to the correct canonical instrument
- the public availability or acceptance timestamp is available and respected
- joins are not performed by fiscal period end alone

#### Macro PIT

A canonical macro value is export-safe only if:

- the correct vintage and availability history is retained
- the selected vintage was available by the as-of cutoff
- later revisions do not leak into earlier as-of dates

#### Export PIT

A row may enter the `Pipeline.py` compatibility export only if:

- its required-core fields satisfy price PIT
- any included enrichment satisfies its own domain PIT rules
- missing optional enrichments remain null and explicitly flagged

### Macro Vintage Storage

The canonical vintage surface must retain at minimum:

- `series_id`
- `observation_date`
- `value`
- `vintage_date`
- `release_ts_utc`
- `available_from_ts_utc`
- `available_to_ts_utc`
- `source`
- `ingested_at_utc`

Rules:

- `available_from_ts_utc` is the earliest time the system could have known the value.
- `available_to_ts_utc` is the exclusive end of the availability window when applicable.
- `vintage_date` alone is insufficient to prove PIT safety.
- storage must preserve enough timing information to reject future-available joins.

### Macro As-Of Materialization

The canonical as-of macro surface must retain at minimum:

- `series_id`
- `asof_date`
- `observation_date`
- `value`
- `selected_vintage_date`
- `selected_available_from_ts_utc`
- `selection_rule_version`
- `built_at_utc`

Rules:

- for each `series_id` and `asof_date`, only vintages available by the as-of cutoff may be selected
- the latest eligible vintage must win under the documented selection rule
- no selected availability timestamp may be in the future relative to the as-of boundary
- later revisions must never backfill earlier as-of dates

### PIT Join Law

All PIT-sensitive joins must be timestamp-safe:

- no macro vintage may join before it was available
- no benchmark or classification row may apply outside its effective window
- no fundamentals fact may join before public availability
- if a required PIT-safe surface is not available, the join must fail closed or the dependent logic must remain disabled

## Benchmark Semantics

Benchmark and reference instruments are role-bearing surfaces, not loose aliases.

Rules:

- every benchmark/reference instrument must declare a semantic role
- canonical versus proxy status must be explicit
- proxy instruments must not silently replace canonical instruments in claims
- `^VIX` is the canonical spot-volatility index reference when used
- `VIXY` is a tradable volatility ETP proxy and must never be treated as equivalent to `^VIX`
- broad-market benchmarks may be used without sector classification history
- sector-relative logic remains disabled until valid date-effective classification support exists

## Classification Fallback Hierarchy

Required behavior:

1. Use a date-effective row from `instrument_classification_history` for the requested classification system and as-of date.
2. If no valid row exists, do not infer a historical classification from stale snapshots or current labels.
3. If classification support is absent, fall back only to non-sector-relative context such as broad-market or explicitly documented benchmark context.

Invalid fallbacks:

- using current static sector labels historically
- backfilling future classifications into earlier dates
- silently substituting benchmark group membership for missing classification history

## Compatibility Bridge Rules

The compatibility bridge preserves downstream operation while the canonical layer remains authoritative.

Rules:

- `security_master` is generated from canonical identity only
- legacy symbol/history adapters are compatibility-only outputs
- the export bridge is generated from canonical market-data surfaces plus compatibility adapters
- `Pipeline.py` continues to consume the exported compatibility panel until explicit downstream migration happens
- compatibility adapters must not become hidden authorities for canonical attribution

## Export Bridge Contract

The export bridge must produce a reproducible panel with columns:

- `ticker`
- `timestamp_utc`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `is_incomplete_session`

Rules:

- `ticker` is a compatibility label, not canonical identity
- canonical export eligibility must be decided before any compatibility labeling step
- `timestamp_utc` represents the actual market session close in UTC
- `is_incomplete_session` is derived from exchange calendar semantics, including early closes
- the exported panel must satisfy the downstream `Pipeline.py` loader contract
- every export must have an `export_panel_version_id`
- every export must reference a `dataset_build_id`
- the export bridge may run only when the dataset manifest reports `canonical_export_ready = true`
- if `compatibility_fallback_used = true`, canonical export must fail closed
- every material export must have a manifest entry with row count, content hash, deferred-component status, and verification refs

## Row State And Export Eligibility

The dataset manifest's `row_state_model` is not descriptive only. It is the minimum state vocabulary for canonical build reporting:

- `RAW_ACCEPTED`
- `SILVER_RESOLVED`
- `SILVER_QUARANTINED`
- `EXPORT_ELIGIBLE`
- `EXPORT_EXCLUDED`

Rules:

- no required-core row may remain in an implicit unknown state
- ordinary companies with unresolved or unreliable required-core data may be quarantined or export-excluded without failing the whole build
- benchmark/reference failures must be treated as blocking when downstream logic requires them
- `canonical_export_ready = true` means the required-core export surface is safe, not merely that some QA checks passed
- quarantine counts, unresolved identity counts, and compatibility fallback usage must be reflected truthfully in manifests and reports

## Manifest And Build-ID Laws

Canonical manifests must be trustworthy.

Minimum requirements:

- dataset manifests mint and persist `dataset_build_id`
- export manifests mint and persist `export_panel_version_id`
- dataset manifests carry a repo-wide `row_state_model`
- dataset manifests carry a `reports` block linking canonical build, coverage, unresolved identity, quarantine, export, and final-status artifacts
- dataset manifests carry `final_status`, `canonical_export_ready`, and `compatibility_fallback_used`
- manifests include git commit, python version, source inputs, row counts, content hashes, and verification refs
- manifests identify deferred components explicitly instead of implying completeness
- downstream outputs and tracking surfaces must carry concrete dataset/export build references before a run is considered comparable
- downstream `config_snapshot.json`, `verification.json`, and MLflow tags/params must carry the same build references
- if the optional OpenLineage surface is enabled and emission succeeds, file-backed run events and `lineage_summary.json` must carry the same build references as the export manifest

## Canonical Build Pass/Warning/Fail Matrix

### Pass

A canonical build passes only if all of the following are true for the required-core export surface:

- exported rows have correct identity attribution
- exported rows satisfy OHLCV, timestamp, and bridge-contract requirements
- PIT cutoff laws are enforced for exported data
- unresolved or conflicted required-core rows are quarantined out of export
- required benchmark/reference instruments are present and valid
- required manifests and reports are written

### Non-Blocking Warning

Warnings may exist without failing canonical export when:

- optional enrichments are absent or incomplete
- ordinary non-benchmark companies are quarantined or export-excluded
- deferred components remain explicitly deferred and truthfully reported

### Fail

A canonical build fails if any of the following is true:

- an exported row has wrong or unresolved identity attribution
- current-symbol fallback was used in canonical export eligibility
- required benchmark/reference instruments are unresolved or invalid
- exported OHLCV, timestamp, or calendar fields violate contract
- PIT leakage exists in exported data
- the export contract is invalid for `Pipeline.py`
- required manifests or verification outputs are missing

## Verification Requirements

No material schema, PIT, benchmark, bridge, manifest, or orchestration change is complete unless code, tests, docs, and verification move together.

Required verification surfaces:

- identity verification, including date-effective attribution and unresolved identity reporting
- price verification, including key uniqueness, OHLC sanity, timestamps, and required benchmark/reference coverage
- manifest truthfulness verification, including build IDs, fallback usage, quarantine counts, and report inventory
- Pandera contract validation
- targeted `tests/market_data/` coverage
- PIT leakage checks
- compatibility checks
- bridge/export checks
- benchmark-role checks
- docs synchronization checks
- DuckDB or QA audits where relevant

Required repo gates:

- `schema_guard`
- `docs_sync_guard`
- `pit_guard`
- `compat_guard`
- `bridge_guard`
- `verification_guard`

## Silver legacy Phase-2 surfaces (write-time contracts)

These tables use legacy column shapes aligned to current builders (sid-keyed or Alpha Vantage paths). They are registered as `contract_defined_deferred` for bundle gating: the global contract verifier does not require them until the roadmap promotes them, but builders run `validate_contract_df` at write time.

| Table | Notes |
| --- | --- |
| `benchmark_prices_daily` | Slice of `prices_1d_unadjusted` for configured benchmarks; PK `(sid, trade_date, source_vendor)` |
| `corporate_actions` | From bronze `av_daily_adjusted`; PK `(sid, action_type, ex_date, source_vendor)`; `record_date` / `payment_date` / `declared_date` nullable |
| `adjustment_factors` | Derived from split corporate actions; PK `(sid, effective_date)` |

Gold `gold_macro_context` pivots silver `macro_asof_daily` on **`asof_date`** (not `trade_date`), matching the canonical macro PIT model.

## Documentation Synchronization Rule

A material change affecting any of the following is incomplete unless `README.md`, `market_data/COMMANDS.md`, and this document are updated in the same change:

- schema
- PIT logic
- benchmark semantics
- source-of-truth boundaries
- compatibility bridge behavior
- export contracts
- orchestration critical path
- user-facing verification or e2e commands

## Deferred And De-Prioritized Components

The following remain intentionally incomplete or de-prioritized and must be reported as such rather than implied complete:

- authoritative historical classification coverage
- fully populated `instrument_benchmark_map`
- broader fundamentals PIT completeness
- broader orchestration refactors
- broad Great Expectations expansion
- broad DVC expansion
- expanded Dagster role
- Prefect
- lakeFS
- broad MCP integrations

Revisit conditions live in `docs/market_data_roadmap.md`.
