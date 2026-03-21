# Master Cursor Build Prompt

> **This master file supersedes both prior versions. On conflict, Section A governs.**

You are implementing a **complete institutional-grade feature-discovery and strategy-library pipeline** in this repository.

## Core instruction

Build the full system now.  
Do not respond with “v1 now, v2 later.”  
Do not leave placeholder sections.  
Do not create avoidable file sprawl.  
Keep the implementation centered on **one main file: `Pipeline.py`**, with small supporting files only where they materially improve robustness.

The implementation is acceptable only if it is:
- end-to-end runnable
- chronology-safe
- free of placeholders and mocked results
- overwrite-oriented by default
- auditable by the supplied pipeline-auditor
- aligned with the files in this bundle

You must follow:
- `02_PIPELINE_BLUEPRINT.md`
- `03_FEATURE_LIBRARY_SPEC.md`
- `04_OUTPUT_FILE_POLICY.md`
- `05_SUBAGENTS_RULES_COMMANDS.md`
- `06_VALIDATION_AND_ACCEPTANCE.md`

## Primary objective

Transform the current pipeline into a **single pooled long-only equity research pipeline** that:

1. Builds a broad candidate feature library
   - minimum **70 regular features**
   - minimum **20 physics / fractal / regime features**
   - includes a dedicated **volatility-clustering family**

2. Learns from a **one-model pooled panel** over the existing universe

3. Uses a **staged feature-discovery workflow**
   - feature registry
   - all-features baseline
   - model importance extraction
   - permutation importance on OOS-scored data
   - family-level contribution
   - fold-stability ranking
   - regime-specific importance
   - ablation
   - orthogonality / redundancy pruning
   - constrained subset selection on survivors
   - ranked strategy library output

4. Keeps the predictive task and the portfolio task separate
   - predictive layer estimates a clean trade-event probability
   - policy layer converts that into EV ranking, threshold selection, and portfolio behavior

5. Optimizes the strategy library against portfolio-level gates and priorities, not just classification metrics

6. Produces a **clean output directory** with overwrite behavior by default, durable checkpoints, and clear human-readable reports

## Non-negotiable implementation rules

### No fake completeness
Do not return:
- placeholders
- random stand-ins
- dummy or mocked strategy metrics
- commented-out core stages
- scaffold-only outputs presented as complete

### Preserve and upgrade the real pipeline
Do not replace a working pipeline with a toy skeleton.  
Upgrade the real implementation in place.

### Train-only transforms
Any learned transform, pruning step, clustering step, family ranking, or subset search must be fit on **training data only within the relevant fold stage** unless explicitly proven safe and unsupervised at the global level.

### Current build assumptions
- same current panel / same universe
- long-only
- one pooled model
- 1-hour bars
- target holding period roughly **2 trading days to 3 trading weeks**
- regular-session intraday data assumed unless the repo clearly states otherwise

## Target horizon defaults for 1-hour bars

Use a **horizon-aware lookback ladder** centered on the intended trade duration.

### Default lookback ladder
Use these as the primary standard windows:
- short: 3, 5, 8
- core: 13, 21, 34, 55
- extended context: 89

Interpretation:
- 13 bars ≈ ~2 trading days
- 34 bars ≈ ~1 trading week
- 55 bars ≈ ~1.5–2 weeks
- 89 bars ≈ ~2.5–3 weeks

Do not make very long windows (>89 bars) primary signal features unless they are clearly labeled as **context/regime only**.

### Default event-label geometry
Unless the existing repo already contains a stronger validated geometry, use:
- `max_horizon_bars = 98`
- `stop_atr_multiple = 1.25`
- `target_atr_multiple = 2.50`

These are defaults, not immutable truths. If the existing repo has stronger evidence for alternatives, preserve it and document why.

## Portfolio gates

Use these hard minimum gates:
- Profit Factor >= 1.75
- Calmar >= 1.0
- Max Drawdown <= 20%
- Expectancy_r >= 0.25
- Minimum Trades >= 200
- Positive-Fold Ratio >= 60%
- Top-Ticker Concentration <= 25%
- Churn <= 15%

## Optimization priority order

1. Calmar
2. Profit Factor
3. Expectancy_r
4. CAGR
5. Max Drawdown
6. Trade Count

Implement a composite strategy score consistent with that hierarchy and document the weights explicitly.

## Modeling stack

Implement / preserve:
- Random Forest
- Extra Trees
- XGBoost
- LightGBM
- Elastic Net logistic baseline
- Logistic meta model
- Calibration layer

### Calibration defaults
- default calibration method: **sigmoid / logistic**
- isotonic is allowed only if calibration holdout has at least:
  - 500 total rows
  - 75 positives
  - 75 negatives
- otherwise force sigmoid

### Holdout defaults
- threshold holdout:
  - minimum 50 rows
  - both classes present
  - skip fold if invalid
- calibration holdout:
  - minimum 200 rows
  - minimum 25 positives
  - minimum 25 negatives
  - skip fold if invalid

### Calibration chronology
Do not fit the calibrator on rows used to fit the meta model.
Use a chronologically later calibration holdout inside outer-train.

## Volatility clustering

Add a dedicated **volatility_clustering** feature family.

It must be:
- separate in the registry
- separate in importance outputs
- separate in ablation
- separate in final reporting

Use volatility clustering as a **context family**, not as a hard-coded rule engine.  
Do not hard-code “only trade low-vol” unless later evidence strongly supports it.

## Information Coefficient (IC)

Add a ranking-quality layer.

### Primary IC
- Spearman rank IC

### IC targets
Compute against:
1. realized R-multiple
2. forward return over horizon

### Required IC outputs
- mean Spearman IC
- IC std
- IC hit rate
- ICIR
- optional Pearson IC as secondary diagnostic
- optional top-decile vs bottom-decile spread

Do not replace IC with accuracy.

## Seed robustness

Add staged seed evaluation.

### Default seed policy
- development mode: 1 seed
- research mode: 5 seeds
- final shortlist mode: 10 seeds

Suggested default seed lists:
- research: `[11, 23, 42, 57, 73]`
- final shortlist: `[11, 23, 31, 42, 57, 73, 88, 101, 117, 149]`

Do not blow up compute by sweeping every seed across every stage.
Use:
- primary/default seed for broad discovery
- seed sweeps only for shortlisted feature sets / strategy sets

## Orthogonality / redundancy

If multiple indicators in the same family are strong, do **not** automatically keep all of them.

Prefer:
- strongest
- most stable across folds
- highest incremental lift after accounting for correlation / redundancy

### Default orthogonality rules
- near-duplicate correlation threshold: 0.80
- family cap: no family > 30% of final selected features
- promote features only if fold stability >= 70%
- reject if stability < 50% unless exceptional ablation lift clearly justifies retention

## Classification metrics

Track as diagnostics only:
- log loss
- Brier
- ROC-AUC
- PR-AUC
- accuracy (side metric only)

Do **not** optimize primarily around accuracy.

## Required outputs

### Feature-discovery outputs
1. ranked_feature_table.csv
2. family_importance_table.csv
3. fold_stability_table.csv
4. family_ablation.csv
5. selected_final_feature_set.csv
6. rejected_unstable_features.csv
7. regime_specific_importance.csv
8. ensemble_importance.csv
9. permutation_importance.csv
10. fold_ic_summary.csv
11. seed_robustness_summary.csv

### Strategy outputs
12. strategy_library.csv
13. strategy_scorecards.csv
14. best_strategy_summary.json

### Core research outputs
15. fold_metrics.csv
16. concurrency_comparison.csv
17. trade_blotter.csv
18. equity_curves.csv
19. selected_thresholds.csv
20. feature_stability_summary.csv
21. final_report.md

### Human-readable report requirements
The final report must:
- list all implemented features in plain English
- group them by family
- describe settings / lookbacks
- explain which features / families survived and why
- explain which were rejected and why
- explain what Spearman IC means in plain English
- explain how seed robustness was evaluated
- explain whether volatility clustering added stable OOS lift
- describe final strategy candidates in human-readable language
- explain entry logic, exit logic, ranking logic, and risk logic at a decision level
- explicitly state that ensemble tree models are not automatically simple crossover systems unless a separate rule-distillation layer is added

## File-creation discipline

Follow `04_OUTPUT_FILE_POLICY.md`.

High-level rules:
- do not create a new file per run unless required
- overwrite current-state artifacts by default
- keep only files needed for:
  - current-state review
  - resume/checkpointing
  - final reporting
- archive only behind an explicit flag
- keep directories clearly numbered and ordered

## Required output tree

Use:
- `00_logs/`
- `01_data/`
- `02_metrics/`
- `03_features/`
- `04_strategies/`
- `05_reports/`
- `06_state/`

## Build requirements

### A. Feature registry
Implement a registry in or alongside `Pipeline.py` that stores:
- feature_name
- english_name
- family
- subfamily
- regular_or_physics
- lookback
- parameters
- formula_group
- default_enabled
- depends_on
- candidate_group_id
- orthogonality_cluster_id
- family_cap_weight
- interpretability_tag
- requires_external_reference

### B. Staged discovery
Implement:
1. all-features baseline
2. raw model importance
3. permutation importance on OOS-scored data
4. fold stability
5. family contribution
6. family ablation
7. regime-specific importance
8. orthogonality pruning
9. restricted subset search on survivors
10. strategy-library ranking

### C. Strategy library
Do not return a single “best” strategy only.
Produce a ranked library of candidates.

Promotion rules:
- reject candidate if any hard gate fails
- apply seed-robustness downgrade on shortlisted candidates
- retain tie-breakers explicitly:
  1. higher Calmar
  2. higher PF
  3. higher expectancy_r
  4. lower MDD
  5. higher trade count
  6. higher ICIR

### D. Logging
`pipeline.log` must show:
- fold start / end
- purge counts
- threshold-holdout and calibration-holdout sizes
- current stage
- current seed in seed-sweep mode
- full fold metrics block
- IC block
- skip reasons
- checkpoint writes
- final summary

## Acceptance
Do not consider the build complete unless it passes `06_VALIDATION_AND_ACCEPTANCE.md`.

---

## Section B — Legacy clarifications & context

### Feature source philosophy
Use the Quantified Strategies indicator catalog as a **candidate feature source**, not as a proof hierarchy. Treat it as a broad feature universe to source indicators and transforms from, then let the pipeline determine which survive. Reference: https://www.quantifiedstrategies.com/trading-indicators/

### Feature selection philosophy
Do **not** brute-force feature subsets over the full raw library. Use the staged approach (registry → baseline → importance → stability → ablation → orthogonality → restricted subset search → strategy library).

### Strategy distillation
If feasible without major complexity, add a small **rule-distillation** layer for the final shortlisted strategies so the report can describe the strategy logic in plain English. Do not fake simple crossover rules if the underlying logic is an ensemble score. If full rule distillation is not cleanly achievable, explain the strategy in terms of dominant feature families, ranking logic, threshold logic, exit logic, replacement logic, and risk logic.

### Long-run execution model
Use checkpointing, resume, and overwrite-oriented outputs. The pipeline must be able to run for hours / overnight, resume safely, and continue logging live status to `pipeline.log`.

### Deliver back
Return: (1) updated `Pipeline.py`, (2) any minimal supporting files created, (3) summary of what changed, (4) output directory structure, (5) note on overwrite behavior, (6) note on how to run and resume.
