Status: Non-authoritative work artifact
Canonical authority:
- AGENTS.md
- docs/data_contract.md
- docs/phase1-research-spec.md
- docs/phase1-execution-roadmap.md

# COMBINED_IMPLEMENTATION_DIRECTIVE_v1

Historical combined work artifact retained for implementation traceability. Canonical benchmark/data semantics belong in `docs/data_contract.md`, frozen Phase 1 semantics belong in `docs/phase1-*.md`, operator commands belong in `README.md` or `market_data/COMMANDS.md`, and generated/local shims must defer to `AGENTS.md`.

---

## Objective

Two tightly scoped, coordinated improvements:

1. **Factor-diagnostics layer** using **alphalens-reloaded** for cross-sectional score/rank evaluation before full strategy backtesting.
2. **Benchmark-architecture contract resolution** so benchmark semantics, mapping keys, classification policy, and validator behavior are unambiguous and PIT-safe.

**Package note:** Use **alphalens-reloaded** only; do not add the legacy Quantopian `alphalens` package for new work.

---

## A. Alphalens / factor-diagnostics integration

### A1. Package policy

- Approved: `alphalens-reloaded` (pinned in `pyproject.toml`, dependency group `analysis`).
- Integration must be isolatable (disable without breaking the core backtest engine).

### A2. Role

- Secondary research-evaluation module; mandatory gate for cross-sectional score/rank models before expensive full evaluation.
- **Not** the primary deployable-strategy evaluator; **not** CPCV/walk-forward, execution cost, final PM reports, or benchmark/risk-free semantics.

### A3. Placement

`analysis/alpha_diagnostics/`:

- `__init__.py`
- `build_factor_data.py`
- `run_alphalens.py`
- `export_alphalens_artifacts.py`
- `schemas.py`
- `config.py`

### A4. Canonical inputs

1. Model scores: `date`, `asset`, `score`.
2. Pricing sufficient for forward returns at configured horizons (return basis must be explicit; see B7).
3. Optional group labels: `date`, `asset`, `group` from **canonical** benchmark/classification artifacts only.
4. Config: horizons, quantile count, `long_short`, `group_neutral`, `by_group`, universe filter, minimum coverage.

### A5. Canonical outputs

`reports/alpha_diagnostics/<strategy_name>/<run_id>/`:

- `factor_data.parquet`
- `alphalens_summary_metrics.json`
- `ic_timeseries.parquet`
- `quantile_returns.parquet`
- `turnover_metrics.parquet`
- `factor_rank_autocorr.parquet`
- `by_group_metrics.parquet` (only when groups enabled)
- `charts/` (`ic_timeseries.png`, `mean_return_by_quantile.png`, `top_bottom_spread.png`, `turnover_by_quantile.png`, `factor_rank_autocorrelation.png`, `by_group_returns.png` when groups enabled)
- `manifest.json`

### A6–A10

Analyses, gating policy, Quarto report sections (Model diagnostics, Quantile return analysis, IC stability, Turnover/rank persistence, Group/sector decomposition), acceptance gates, and prohibited patterns are as specified in the task brief: notebook-only outputs are non-compliant; no ad hoc sector inference; no benchmark/risk-free logic inside this module.

---

## B. Benchmark architecture patch resolution

### B1. Canonical benchmark price shape

- **`benchmark_prices_daily`** remains the canonical **live** silver benchmark-price surface.
- Shape: **sid-keyed** `BENCHMARK_PRICES_DAILY_SILVER` (Pandera `benchmark_prices_daily`).
- **Legacy** instrument-keyed `BENCHMARK_PRICES_DAILY` (with `adj_close`) is **deprecated** for new downstream work; document only; no new dependencies.

### B2. `benchmark_definitions`

- Already `canonical_live`; treat contract changes as **breaking** and update schema, validators, tests, and docs in one slice.

### B3. Volatility context

- Retain `^VIX` and `VIXY` in `benchmarks.yaml`.
- Validator (`_ensure_benchmark_roles` + extensions): **SPY** sole **primary** market benchmark; **11 sector ETFs** canonical sector layer; **^VIX** / **VIXY** required **context** symbols.

### B4. Stable `benchmark_id`

- `benchmark_definitions` gains **`benchmark_id`** as the canonical mapping key.
- `symbol` remains required and unique; long-term joins use `benchmark_id` → definitions → sid/symbol → `benchmark_prices_daily`.
- Mapping tables must not rely on raw symbol strings as the only long-term identifier.

### B5. Classification enum

- Extend `CLASSIFICATION_SYSTEM_VALUES` (and equivalents) with **`SEC_SIC_4`** in the same slice as `instrument_classification_history` emission.

### B6. `adj_close` policy

- **`benchmark_prices_daily`**: **unadjusted** OHLCV silver only; **no** `adj_close` on this contract.
- Adjusted/total-return semantics → separate derived surface (e.g. `benchmark_return_surface_daily`); no fabricated `adj_close`.

### B7. Price-basis semantics

- Live benchmark table = unadjusted OHLCV; downstream returns must label basis (close-to-close unadjusted vs adjusted total return, etc.); no silent substitution.

### B8. Verifier status

- `benchmark_prices_daily` must not stay half-strict: move to **explicit live enforcement** in `tools/verify_market_data_contracts.py` in the same slice as contract promotion.

### B9. Semantic freeze (post-patch)

- SPY sole primary market benchmark; 11 sector ETFs canonical sector layer; ^VIX/VIXY context; DFF macro-native outside OHLCV benchmark registry; sid-keyed `benchmark_prices_daily`; `benchmark_id` canonical key; `SEC_SIC_4` first compliant classification system; adjusted returns in derived artifacts only.

---

## C–E. Classification, mapping, export, tests

Sections C (SEC SIC policy, configs, builders), D (benchmark export surfaces, `Pipeline.py` read-only consumption), and E (tests and acceptance gates) follow the detailed field lists and rules in the originating task specification. **`Pipeline.py`** remains a read-only consumer of exported artifacts; **`instrument_benchmark_map`** evolves to `market_benchmark_id` / `sector_benchmark_id` referencing `benchmark_definitions.benchmark_id` when mapping builders land.

---

## F. Implementation order

1. `benchmark_definitions` semantics cleanup, `benchmark_id`, validator/test updates  
2. `benchmark_prices_daily` canonical silver hardening + verifier status cleanup  
3. Classification source config, SIC crosswalk, `classification.py` helper  
4. `instrument_classification_history` builder + contracts + tests  
5. `instrument_benchmark_map` builder + contracts + tests  
6. Benchmark export artifacts  
7. Alpha-diagnostics module  
8. `Pipeline.py` read-only consumption  
9. Quarto ingestion of benchmark + alpha-diagnostics artifacts  
10. Final docs/commands/acceptance verification  

**Atomicity:** Any change touching schemas, validators, table semantics, or mapping keys lands as a coordinated contract slice.

---

## G. Final success condition

- `market_data` is the sole authority for benchmark semantics and mappings.  
- Deterministic market mapping to SPY (`benchmark_id`); sector mapping from canonical classification + crosswalk only.  
- Functioning **alphalens-reloaded** factor-diagnostics layer with machine-readable + chart exports.  
- `Pipeline.py` consumes canonical artifacts without maintaining a parallel benchmark or factor-diagnostics framework.
