"""Build silver symbol_map_history from canonical symbol history only."""
from __future__ import annotations

from pathlib import Path
import polars as pl

from market_data.common.io_parquet import read_parquet, write_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("silver.symbol_map_history")


def _remove_stale_output(path: Path) -> None:
    if path.exists():
        path.unlink()


def build(
    *,
    settings: IngestionSettings,
    start_date: str,
    end_date: str,
    full_refresh: bool = False,
) -> dict[str, object]:
    _ = (start_date, end_date, full_refresh)

    ish_path = silver_path("instrument_symbol_history", settings) / "instrument_symbol_history.parquet"
    out_path = silver_path("symbol_map_history", settings) / "symbol_map_history.parquet"
    if ish_path.exists():
        df = read_parquet(ish_path).collect()
        if len(df) == 0:
            log.warning("instrument_symbol_history is empty")
            _remove_stale_output(out_path)
            return {"rows": 0, "canonical_symbol_history_present": True}

        out = (
            df.select(
                [
                    pl.col("instrument_id").cast(pl.Utf8).alias("sid"),
                    pl.col("normalized_source_symbol").alias("symbol"),
                    pl.col("effective_from_date").alias("effective_from"),
                    pl.col("effective_to_date").alias("effective_to"),
                    pl.when(pl.col("is_primary_for_source"))
                    .then(pl.lit("canonical_symbol_history"))
                    .otherwise(pl.lit("secondary_symbol_history"))
                    .alias("reason_code"),
                    pl.col("source"),
                ]
            )
            .sort(["sid", "source", "effective_from"])
            .unique(subset=["sid", "source", "symbol", "effective_from"], keep="first")
        )

        written = write_parquet(out, out_path)
        log.info("silver symbol_map_history: %d rows -> %s", written, out_path)
        return {"rows": written, "canonical_symbol_history_present": True}

    _remove_stale_output(out_path)
    log.warning("instrument_symbol_history not found; refusing to derive symbol_map_history from compatibility surfaces")
    return {"rows": 0, "canonical_symbol_history_present": False}
