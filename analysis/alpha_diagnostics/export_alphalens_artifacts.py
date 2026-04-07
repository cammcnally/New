from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd

import alphalens

from analysis.alpha_diagnostics.build_factor_data import build_clean_factor_data
from analysis.alpha_diagnostics.config import AlphaDiagnosticsConfig
from analysis.alpha_diagnostics.run_alphalens import run_quantile_tables, summary_metrics
from analysis.alpha_diagnostics.schemas import AlphaDiagnosticsManifest


def default_output_dir(repo_root: Path, strategy_name: str, run_id: str) -> Path:
    return repo_root / "reports" / "alpha_diagnostics" / strategy_name / run_id


def _df_to_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _plot_ic(ic: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    for col in ic.columns:
        ax.plot(ic.index, ic[col], label=str(col))
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.legend(loc="best", fontsize=8)
    ax.set_title("Information coefficient (daily)")
    ax.set_xlabel("date")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_mean_quantile_returns(mean_ret: pd.DataFrame, path: Path) -> None:
    # Collapse date dimension: overall mean return per quantile (first forward-return col)
    try:
        sub = mean_ret.groupby(level="factor_quantile").mean()
    except Exception:
        sub = mean_ret
    fig, ax = plt.subplots(figsize=(7, 4))
    cols = [c for c in sub.columns if isinstance(c, str) and c.startswith("period_")]
    if not cols:
        cols = list(sub.columns[:1])
    sub[cols[0]].plot(kind="bar", ax=ax, color="steelblue")
    ax.set_title(f"Mean forward return by quantile ({cols[0]})")
    ax.set_xlabel("factor_quantile")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_spread(spread: pd.Series | pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    if isinstance(spread, pd.DataFrame):
        for c in spread.columns:
            ax.plot(spread.index, spread[c], label=str(c))
        ax.legend(fontsize=8)
    else:
        ax.plot(spread.index, spread.values, color="darkgreen")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title("Top minus bottom quantile spread")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_turnover(turnover: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    for c in turnover.columns:
        ax.plot(turnover.index, turnover[c], label=f"Q{int(c)}")
    ax.legend(fontsize=8)
    ax.set_title("Quantile turnover")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_autocorr(series: pd.Series, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(series.index, series.values, color="purple")
    ax.set_title("Factor rank autocorrelation")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_by_group(mean_by_g: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    mean_by_g.plot(kind="bar", ax=ax, legend=True)
    ax.set_title("Mean return by group (aggregated)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def export_alpha_diagnostics_run(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    out_dir: Path,
    *,
    strategy_name: str,
    run_id: str,
    config: AlphaDiagnosticsConfig | None = None,
    groups: pd.DataFrame | None = None,
    group_neutral: bool = False,
) -> AlphaDiagnosticsManifest:
    """
    Build factor_data, run alphalens tables, write parquet/json/png under ``out_dir``.
    """
    if config is None:
        config = AlphaDiagnosticsConfig()
    if config.disabled:
        raise ValueError("alpha_diagnostics export refused: config.disabled is True")

    out_dir = Path(out_dir)
    charts = out_dir / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    factor_data = build_clean_factor_data(
        scores, prices, config, groups=groups, group_neutral=group_neutral
    )
    _df_to_parquet(factor_data.reset_index(), out_dir / "factor_data.parquet")

    tables = run_quantile_tables(factor_data, config)
    summ = summary_metrics(tables, config)
    summ_json = out_dir / "alphalens_summary_metrics.json"
    summ_json.write_text(json.dumps(summ, indent=2), encoding="utf-8")

    _df_to_parquet(tables["ic_timeseries"], out_dir / "ic_timeseries.parquet")
    _df_to_parquet(tables["mean_return_by_quantile"], out_dir / "quantile_returns.parquet")
    _df_to_parquet(tables["turnover_by_quantile"], out_dir / "turnover_metrics.parquet")
    ser = tables["factor_rank_autocorr"]
    _df_to_parquet(ser.to_frame(name="autocorr"), out_dir / "factor_rank_autocorr.parquet")

    artifacts = [
        "factor_data.parquet",
        "alphalens_summary_metrics.json",
        "ic_timeseries.parquet",
        "quantile_returns.parquet",
        "turnover_metrics.parquet",
        "factor_rank_autocorr.parquet",
    ]

    _plot_ic(tables["ic_timeseries"], charts / "ic_timeseries.png")
    _plot_mean_quantile_returns(tables["mean_return_by_quantile"], charts / "mean_return_by_quantile.png")
    _plot_spread(tables["top_bottom_spread"], charts / "top_bottom_spread.png")
    _plot_turnover(tables["turnover_by_quantile"], charts / "turnover_by_quantile.png")
    _plot_autocorr(tables["factor_rank_autocorr"], charts / "factor_rank_autocorrelation.png")
    artifacts.extend(
        f"charts/{p.name}"
        for p in [
            charts / "ic_timeseries.png",
            charts / "mean_return_by_quantile.png",
            charts / "top_bottom_spread.png",
            charts / "turnover_by_quantile.png",
            charts / "factor_rank_autocorrelation.png",
        ]
    )

    if "by_group_mean_returns" in tables:
        bg = tables["by_group_mean_returns"]
        _df_to_parquet(bg, out_dir / "by_group_metrics.parquet")
        _plot_by_group(bg, charts / "by_group_returns.png")
        artifacts.extend(["by_group_metrics.parquet", "charts/by_group_returns.png"])

    manifest: AlphaDiagnosticsManifest = {
        "strategy_name": strategy_name,
        "run_id": run_id,
        "return_basis": config.return_basis,
        "alphalens_version": str(alphalens.__version__),
        "quantiles": config.quantiles,
        "periods": list(config.forward_return_horizons),
        "artifacts": artifacts,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def export_from_repo(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    strategy_name: str,
    run_id: str,
    repo_root: Path | None = None,
    config: AlphaDiagnosticsConfig | None = None,
    groups: pd.DataFrame | None = None,
    group_neutral: bool = False,
) -> AlphaDiagnosticsManifest:
    root = repo_root or Path(__file__).resolve().parents[2]
    out = default_output_dir(root, strategy_name, run_id)
    return export_alpha_diagnostics_run(
        scores,
        prices,
        out,
        strategy_name=strategy_name,
        run_id=run_id,
        config=config,
        groups=groups,
        group_neutral=group_neutral,
    )
