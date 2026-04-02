"""Gold mart: intraday 30-minute panel using compatibility identity."""
from __future__ import annotations

import shutil

import polars as pl

from market_data.common.dates import parse_date
from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import gold_path, silver_path
from market_data.common.settings import IngestionSettings, load_yaml_config

log = get_logger("gold.intraday_panel")


def _intraday_symbols(settings: IngestionSettings) -> list[str]:
    """Flatten intraday_core_30m symbol lists from universe config."""
    cfg = load_yaml_config("universe.yaml", settings)
    members = cfg.get("universes", {}).get("intraday_core_30m", {}).get("members", {})
    symbols: list[str] = []
    for group in members.values():
        if isinstance(group, list):
            symbols.extend(group)
    return symbols


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict:
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    prices_dir = silver_path("prices_30m_unadjusted", settings)
    master_dir = silver_path("security_master", settings)

    for name, path in [
        ("prices_30m_unadjusted", prices_dir),
        ("compat security_master", master_dir),
    ]:
        if not path.exists():
            log.warning("silver %s not found: %s", name, path)
            return {"rows": 0}

    out_dir = gold_path("gold_intraday_panel", settings)
    if full_refresh and out_dir.exists():
        shutil.rmtree(out_dir)

    target_symbols = _intraday_symbols(settings)
    if not target_symbols:
        log.warning("no symbols in intraday_core_30m universe")
        return {"rows": 0}

    master = (
        read_parquet(master_dir)
        .filter(pl.col("symbol_current").is_in(target_symbols))
        .select("sid", "symbol_current")
        .collect()
    )
    if len(master) == 0:
        log.warning("no compat security_master entries for intraday symbols")
        return {"rows": 0}

    target_sids = master["sid"].to_list()

    prices = (
        read_parquet(prices_dir)
        .filter(
            pl.col("sid").is_in(target_sids)
            & (pl.col("session_date") >= sd)
            & (pl.col("session_date") <= ed)
        )
        .collect()
    )
    if len(prices) == 0:
        log.warning("no intraday prices in date range")
        return {"rows": 0}

    panel = prices.join(master, on="sid", how="left")

    panel = (
        panel.select(
            [
                "sid",
                pl.col("symbol_current").alias("symbol"),
                "ts_utc",
                "ts_exchange",
                "session_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )
        .sort(["sid", "ts_utc"])
        .with_columns(
            pl.col("session_date").dt.year().alias("year"),
            pl.col("session_date").dt.month().alias("month"),
        )
    )

    rows = write_parquet(panel, out_dir, partition_by=["year", "month"])
    log.info("gold_intraday_panel: %d rows -> %s", rows, out_dir)
    return {"rows": rows}
