from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("alphalens")

from analysis.alpha_diagnostics.build_factor_data import build_clean_factor_data
from analysis.alpha_diagnostics.config import AlphaDiagnosticsConfig
from analysis.alpha_diagnostics.export_alphalens_artifacts import export_alpha_diagnostics_run


def _sample_scores_prices(
    *, n_days: int = 45, n_assets: int = 5, seed: int = 0, extra_price_days: int = 5
):
    rng = np.random.default_rng(seed)
    score_dates = pd.bdate_range("2024-01-02", periods=n_days)
    price_dates = pd.bdate_range("2024-01-02", periods=n_days + extra_price_days)
    assets = [f"S{i}" for i in range(n_assets)]
    score_rows = []
    price_rows = []
    levels = {a: 100.0 for a in assets}
    for d in price_dates:
        for a in assets:
            if d in score_dates:
                score_rows.append(
                    {"date": pd.Timestamp(d), "asset": a, "score": float(rng.normal())}
                )
            levels[a] *= 1.0 + float(rng.normal(0, 0.008))
            price_rows.append({"date": pd.Timestamp(d), "asset": a, "close": levels[a]})
    return pd.DataFrame(score_rows), pd.DataFrame(price_rows)


def test_export_alpha_diagnostics_writes_machine_readable_and_charts(tmp_path: Path) -> None:
    scores, prices = _sample_scores_prices()
    cfg = AlphaDiagnosticsConfig(forward_return_horizons=(1, 2), quantiles=5, max_loss=0.95)
    out = tmp_path / "alpha_run"
    manifest = export_alpha_diagnostics_run(
        scores,
        prices,
        out,
        strategy_name="test_strategy",
        run_id="run_001",
        config=cfg,
    )
    assert manifest["strategy_name"] == "test_strategy"
    assert (out / "factor_data.parquet").is_file()
    assert (out / "alphalens_summary_metrics.json").is_file()
    assert (out / "ic_timeseries.parquet").is_file()
    assert (out / "quantile_returns.parquet").is_file()
    assert (out / "turnover_metrics.parquet").is_file()
    assert (out / "factor_rank_autocorr.parquet").is_file()
    assert (out / "manifest.json").is_file()
    for name in (
        "ic_timeseries.png",
        "mean_return_by_quantile.png",
        "top_bottom_spread.png",
        "turnover_by_quantile.png",
        "factor_rank_autocorrelation.png",
    ):
        assert (out / "charts" / name).is_file()


def test_build_clean_factor_data_fails_closed_on_misaligned_asset() -> None:
    scores, prices = _sample_scores_prices(n_days=30, n_assets=3)
    bad = scores.copy()
    bad = pd.concat(
        [bad, pd.DataFrame([{"date": scores["date"].iloc[0], "asset": "UNKNOWN", "score": 1.0}])],
        ignore_index=True,
    )
    cfg = AlphaDiagnosticsConfig(forward_return_horizons=(1,), quantiles=3, max_loss=0.2)
    with pytest.raises(ValueError, match="alignment|max_loss"):
        build_clean_factor_data(bad, prices, cfg)
