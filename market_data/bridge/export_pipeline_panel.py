"""Export canonical silver data as a Pipeline.py-compatible CSV.

The research pipeline's ``load_panel`` / ``verify_panel`` requires:
  ticker, timestamp_utc, open, high, low, close, volume, is_incomplete_session

This module reads from canonical silver price data, uses the preserved
date-effective source symbol as the downstream compatibility label, computes
``is_incomplete_session`` from the trading calendar, validates the export
contract, and writes a CSV matching the downstream compatibility contract.

Timestamp semantics: ``timestamp_utc`` is set to the actual NYSE/NASDAQ
session close time in UTC for each trade_date (typically 20:00 or 21:00 UTC
depending on daylight saving).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import polars as pl

from market_data.common.calendars import session_open_close, is_early_close, trading_days
from market_data.common.manifest import (
    build_export_manifest,
    current_dataset_build_id,
    dataset_manifest_path,
    read_manifest,
    write_manifest,
    write_export_manifest,
)
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.pandera_contracts import validate_contract_df
from market_data.common.settings import IngestionSettings
from market_data.common.io_parquet import read_parquet
from market_data.common.dates import parse_date

log = get_logger("bridge.export")


def _check_prerequisite(name: str, path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required silver table '{name}' not found at {path}. "
            f"Run 'python -m market_data.cli bootstrap' first."
        )


def _build_close_times(start: date, end: date) -> pl.DataFrame:
    """Build a mapping of trade_date -> market_close_utc for NYSE sessions."""
    days = trading_days(start, end)
    rows = []
    for d in days:
        _, close_ts = session_open_close(d)
        rows.append({
            "trade_date": d,
            "market_close_utc": close_ts.to_pydatetime(),
            "is_early_close": is_early_close(d),
        })
    return pl.DataFrame(rows).with_columns(
        pl.col("market_close_utc").cast(pl.Datetime("us", "UTC")),
    )


def _benchmark_surface_path_for_panel(out: Path) -> Path:
    return out.with_name(f"{out.stem}_benchmark_surface_daily.parquet")


def _build_benchmark_surface(
    *,
    settings: IngestionSettings,
    output_panel_path: Path,
    start_date: date,
    end_date: date,
) -> Path | None:
    bench_path = silver_path("benchmark_prices_daily", settings)
    sec_master_path = silver_path("security_master", settings)
    if not bench_path.exists() or not sec_master_path.exists():
        return None

    bench = (
        read_parquet(bench_path)
        .filter((pl.col("trade_date") >= start_date) & (pl.col("trade_date") <= end_date))
        .collect()
    )
    if bench.height == 0:
        return None
    sec_master = read_parquet(sec_master_path).select(["sid", "symbol_current"]).collect()
    bench = (
        bench.join(sec_master, on="sid", how="left")
        .filter(pl.col("symbol_current").is_not_null())
        .sort(["symbol_current", "trade_date"])
        .with_columns(
            pl.col("close").pct_change().over("symbol_current").alias("ret_1d"),
        )
        .with_columns(
            (((pl.col("ret_1d").fill_null(0.0) + 1.0).cum_prod().over("symbol_current")) - 1.0).alias(
                "cumret"
            )
        )
    )

    ret_wide = bench.pivot(on="symbol_current", index="trade_date", values="ret_1d").rename(
        {
            col: f"{col.lower().replace('^', '').replace('.', '_')}_ret_1d"
            for col in bench["symbol_current"].unique().to_list()
        }
    )
    cum_wide = bench.pivot(on="symbol_current", index="trade_date", values="cumret").rename(
        {
            col: f"{col.lower().replace('^', '').replace('.', '_')}_cumret"
            for col in bench["symbol_current"].unique().to_list()
        }
    )
    surface = ret_wide.join(cum_wide, on="trade_date", how="left").rename({"trade_date": "date"})

    macro_path = silver_path("macro_asof_daily", settings)
    if macro_path.exists():
        dff = (
            read_parquet(macro_path)
            .filter(
                (pl.col("series_id") == "DFF")
                & (pl.col("asof_date") >= start_date)
                & (pl.col("asof_date") <= end_date)
            )
            .select(
                pl.col("asof_date").alias("date"),
                (pl.col("value") / pl.lit(100.0 * 360.0)).alias("dff_daily_rate"),
            )
            .collect()
        )
        if dff.height > 0:
            surface = surface.join(dff, on="date", how="left")

    out_path = _benchmark_surface_path_for_panel(output_panel_path)
    surface.write_parquet(out_path, compression="zstd")
    return out_path


def export_panel(
    *,
    settings: IngestionSettings,
    output_path: str | None = None,
    start_date: str,
    end_date: str,
    universe: str = "all_us_common_daily",
) -> Path:
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    _ = universe
    out = (Path(output_path) if output_path else Path("panel_ohlcv_clean.csv")).resolve()

    prices_path = silver_path("prices_1d_unadjusted", settings)
    calendar_path = silver_path("trading_calendar", settings)

    _check_prerequisite("prices_1d_unadjusted", prices_path)
    _check_prerequisite("trading_calendar", calendar_path)

    prices = read_parquet(prices_path).filter(
        (pl.col("trade_date") >= sd) & (pl.col("trade_date") <= ed)
    )

    close_times = _build_close_times(sd, ed)

    panel = (
        prices
        .collect()
        .join(close_times, on="trade_date", how="left")
        .with_columns(
            pl.col("market_close_utc").alias("timestamp_utc"),
            pl.col("is_early_close").fill_null(False).alias("is_incomplete_session"),
        )
        .select(
            pl.col("source_symbol").alias("ticker"),
            "timestamp_utc",
            "open", "high", "low", "close", "volume",
            "is_incomplete_session",
        )
        .filter(pl.col("ticker").is_not_null())
        .filter(
            (pl.col("low") <= pl.col("open"))
            & (pl.col("low") <= pl.col("close"))
            & (pl.col("low") <= pl.col("high"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
        )
        .sort("ticker", "timestamp_utc")
        .unique(subset=["ticker", "timestamp_utc"], keep="first")
    )
    panel = validate_contract_df("export_panel", panel)
    dataset_build_id = current_dataset_build_id(settings)
    if not dataset_build_id:
        raise FileNotFoundError(
            "Required dataset manifest not found. "
            f"Build canonical market_data first so {dataset_manifest_path(settings)} exists."
        )
    dataset_manifest = read_manifest(dataset_manifest_path(settings))
    if not dataset_manifest.get("canonical_export_ready"):
        raise RuntimeError(
            "Dataset manifest indicates canonical_export_ready=false; "
            "refusing to export a downstream compatibility panel."
        )
    if dataset_manifest.get("compatibility_fallback_used"):
        raise RuntimeError(
            "Dataset manifest indicates compatibility_fallback_used=true; "
            "refusing to export a canonical downstream compatibility panel."
        )
    panel.write_csv(out)
    benchmark_surface_path = _build_benchmark_surface(
        settings=settings,
        output_panel_path=out,
        start_date=sd,
        end_date=ed,
    )
    export_manifest = build_export_manifest(
        output_path=out,
        contract_name="export_panel",
        start_date=start_date,
        end_date=end_date,
        row_count=len(panel),
        ticker_count=panel["ticker"].n_unique(),
        dataset_build_id=dataset_build_id,
        verification_artifacts=dataset_manifest.get("verification_artifacts", []),
        deferred_components=dataset_manifest.get("deferred_components", []),
        side_artifacts={
            "benchmark_surface_daily": str(benchmark_surface_path)
        }
        if benchmark_surface_path
        else {},
    )
    export_manifest_path = write_export_manifest(export_manifest, out)

    reports = dataset_manifest.get("reports")
    if not isinstance(reports, dict):
        reports = {}
    reports["export_panel_manifest"] = str(export_manifest_path)
    if benchmark_surface_path:
        reports["benchmark_surface_daily"] = str(benchmark_surface_path)
    dataset_manifest["reports"] = reports
    write_manifest(dataset_manifest, dataset_manifest_path(settings))

    log.info("exported %d rows (%d tickers) to %s",
             len(panel), panel["ticker"].n_unique(), out)
    return out
