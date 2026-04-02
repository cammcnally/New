from __future__ import annotations

import pandas as pd

from analysis.alpha_diagnostics.config import AlphaDiagnosticsConfig


def scores_to_factor_series(scores: pd.DataFrame) -> pd.Series:
    """Build MultiIndex (date, asset) factor Series from long scores table."""
    required = {"date", "asset", "score"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"scores missing columns: {sorted(missing)}")
    s = scores.sort_values(["date", "asset"])
    idx = pd.MultiIndex.from_arrays([s["date"].values, s["asset"].values], names=["date", "asset"])
    out = pd.Series(s["score"].values, index=idx, name="factor")
    if out.index.duplicated().any():
        raise ValueError("duplicate (date, asset) rows in scores")
    return out


def prices_long_to_wide(prices: pd.DataFrame, *, price_col: str = "close") -> pd.DataFrame:
    """Pivot long prices (date, asset, close) to wide for alphalens."""
    need = {"date", "asset", price_col}
    if not need.issubset(prices.columns):
        raise ValueError(f"prices must include columns {sorted(need)}")
    wide = prices.pivot(index="date", columns="asset", values=price_col)
    wide = wide.sort_index()
    wide.index = pd.DatetimeIndex(wide.index)
    if not wide.index.is_monotonic_increasing:
        wide = wide.sort_index()
    return wide.astype(float)


def merge_group_labels(scores: pd.DataFrame, groups: pd.DataFrame | None) -> pd.DataFrame:
    """Left-join canonical group labels onto scores on (date, asset)."""
    if groups is None or groups.empty:
        return scores
    need = {"date", "asset", "group"}
    if not need.issubset(groups.columns):
        raise ValueError(f"groups must include {sorted(need)}")
    g = groups[["date", "asset", "group"]].drop_duplicates(subset=["date", "asset"])
    merged = scores.merge(g, on=["date", "asset"], how="left")
    if merged["group"].isna().any():
        raise ValueError(
            "alpha_diagnostics: missing group labels for some (date, asset); "
            "refuse ad hoc fill — supply complete canonical labels or disable by_group."
        )
    return merged


def build_clean_factor_data(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    config: AlphaDiagnosticsConfig,
    *,
    groups: pd.DataFrame | None = None,
    group_neutral: bool = False,
) -> pd.DataFrame:
    """
    Align scores and prices into alphalens ``factor_data`` frame.

    Raises ``ValueError`` on alignment / coverage failure (including alphalens max_loss).
    """
    from alphalens.utils import MaxLossExceededError, get_clean_factor_and_forward_returns

    s = merge_group_labels(scores, groups) if groups is not None else scores
    factor = scores_to_factor_series(s[["date", "asset", "score"]])
    px = prices_long_to_wide(prices)

    factor_assets = set(s["asset"].astype(str).unique())
    price_assets = set(map(str, px.columns))
    missing_assets = sorted(factor_assets - price_assets)
    if missing_assets:
        raise ValueError(
            "alpha_diagnostics: factor/price alignment failed; "
            f"missing price coverage for assets {missing_assets[:10]}"
        )

    factor_dates = pd.DatetimeIndex(pd.to_datetime(s["date"]).sort_values().unique())
    if factor_dates.empty:
        raise ValueError("alpha_diagnostics: no score rows provided")
    if factor_dates.min() < px.index.min() or factor_dates.max() > px.index.max():
        raise ValueError(
            "alpha_diagnostics: factor/price alignment failed; "
            "score dates fall outside provided price history"
        )

    required_last_sell_date = factor_dates.max()
    last_required_loc = px.index.get_indexer([required_last_sell_date], method=None)[0]
    if last_required_loc < 0 or last_required_loc + max(config.forward_return_horizons) >= len(px.index):
        raise ValueError(
            "alpha_diagnostics: factor/price alignment failed; "
            "insufficient forward price horizon coverage"
        )

    groupby = None
    if groups is not None and "group" in s.columns:
        groupby = s.set_index(["date", "asset"])["group"]
        groupby.index.names = ["date", "asset"]

    try:
        return get_clean_factor_and_forward_returns(
            factor,
            px,
            quantiles=config.quantiles,
            periods=config.forward_return_horizons,
            max_loss=config.max_loss,
            groupby=groupby,
            groupby_labels=None,
            binning_by_group=bool(group_neutral and groupby is not None),
        )
    except MaxLossExceededError as exc:
        raise ValueError(
            "alpha_diagnostics: factor/price alignment failed (max_loss exceeded); "
            "check coverage, horizons, and return basis."
        ) from exc
