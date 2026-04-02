from __future__ import annotations

from typing import Any

import pandas as pd

from alphalens import performance as perf

from analysis.alpha_diagnostics.config import AlphaDiagnosticsConfig


def run_quantile_tables(factor_data: pd.DataFrame, config: AlphaDiagnosticsConfig) -> dict[str, Any]:
    mean_ret, std_err = perf.mean_return_by_quantile(
        factor_data, by_date=True, demeaned=config.long_short
    )
    spread, spread_err = perf.compute_mean_returns_spread(
        mean_ret, upper_quant=config.quantiles, lower_quant=1, std_err=std_err
    )
    ic = perf.factor_information_coefficient(factor_data)
    mean_ic = perf.mean_information_coefficient(factor_data, by_time=None)
    qf = factor_data["factor_quantile"]
    turnover_by_q: dict[int, pd.Series] = {}
    for q in range(1, config.quantiles + 1):
        turnover_by_q[q] = perf.quantile_turnover(qf, q, period=1)
    turnover_df = pd.DataFrame(turnover_by_q)
    autocorr = perf.factor_rank_autocorrelation(factor_data, period=1)
    out: dict[str, Any] = {
        "mean_return_by_quantile": mean_ret,
        "mean_return_std_err": std_err,
        "top_bottom_spread": spread,
        "top_bottom_spread_std_err": spread_err,
        "ic_timeseries": ic,
        "mean_ic": mean_ic,
        "turnover_by_quantile": turnover_df,
        "factor_rank_autocorr": autocorr,
    }
    if "group" in factor_data.columns:
        mean_by_g, _ = perf.mean_return_by_quantile(
            factor_data, by_date=False, by_group=True, demeaned=config.long_short
        )
        out["by_group_mean_returns"] = mean_by_g
    return out


def summary_metrics(tables: dict[str, Any], config: AlphaDiagnosticsConfig) -> dict[str, Any]:
    ic = tables["ic_timeseries"]
    mean_ic = ic.mean(skipna=True).to_dict()
    ic_std = ic.std(skipna=True).to_dict()
    hit_rate = (ic > 0).mean(skipna=True).to_dict()
    spread = tables["top_bottom_spread"]
    if isinstance(spread, pd.Series):
        spread_mean = float(spread.mean())
    elif isinstance(spread, pd.DataFrame):
        spread_mean = float(spread.mean().mean())
    else:
        spread_mean = float(spread)
    return {
        "mean_ic_by_horizon": {str(k): float(v) for k, v in mean_ic.items()},
        "ic_std_by_horizon": {str(k): float(v) for k, v in ic_std.items()},
        "ic_hit_rate_by_horizon": {str(k): float(v) for k, v in hit_rate.items()},
        "mean_top_minus_bottom_spread": spread_mean,
        "quantiles": config.quantiles,
        "periods": list(config.forward_return_horizons),
        "return_basis": config.return_basis,
    }
