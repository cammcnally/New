"""QA checks for silver universe_membership table."""
from __future__ import annotations

import polars as pl

from market_data.common.io_parquet import read_parquet
from market_data.common.logging import get_logger
from market_data.common.paths import silver_path
from market_data.common.settings import IngestionSettings

log = get_logger("qa.universe")

_DELIST_GRACE_DAYS = 30


def check(*, settings: IngestionSettings) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    membership_dir = silver_path("universe_membership", settings)
    if not membership_dir.exists():
        warnings.append("universe_membership directory not found")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    df = read_parquet(membership_dir).collect()
    stats["total_rows"] = len(df)
    stats["universe_names"] = df["universe_name"].unique().to_list()

    members = df.filter(pl.col("is_member"))

    eligibility_cols = [
        c
        for c in ("price_ok", "liquidity_ok", "age_ok", "status_ok")
        if c in df.columns
    ]
    if eligibility_cols:
        ineligible = members.filter(
            pl.any_horizontal(
                [pl.col(c) == False for c in eligibility_cols]  # noqa: E712
            )
        )
        if len(ineligible) > 0:
            errors.append(
                f"{len(ineligible)} members fail eligibility flags: "
                f"{eligibility_cols}"
            )
        stats["ineligible_members"] = len(ineligible)

    master_dir = silver_path("security_master", settings)
    if master_dir.exists():
        master = (
            read_parquet(master_dir)
            .select("sid", "is_active", "delist_date")
            .collect()
        )
        delisted = master.filter(
            (~pl.col("is_active")) & pl.col("delist_date").is_not_null()
        )
        if len(delisted) > 0:
            joined = members.join(
                delisted.select("sid", "delist_date"), on="sid", how="inner"
            )
            stale = joined.filter(
                pl.col("trade_date")
                > (pl.col("delist_date") + pl.duration(days=_DELIST_GRACE_DAYS))
            )
            if len(stale) > 0:
                warnings.append(
                    f"{len(stale)} membership rows "
                    f">{_DELIST_GRACE_DAYS} days after delist_date"
                )
            stats["stale_delisted_members"] = len(stale)
    else:
        warnings.append("security_master not found; skipping delist window check")

    log.info("qa_universe: %d errors, %d warnings", len(errors), len(warnings))
    return {"errors": errors, "warnings": warnings, "stats": stats}
