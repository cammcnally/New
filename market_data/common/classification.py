from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import polars as pl

from market_data.common.settings import IngestionSettings, load_yaml_config

_ALLOWED_SECTOR_ETFS = frozenset(
    {"XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"}
)


@dataclass(frozen=True)
class ClassificationSourcePolicy:
    source_name: str
    classification_system: str
    field_precedence: tuple[str, ...]
    missing_policy: str


@dataclass(frozen=True)
class SicCrosswalkRule:
    source_exact: str | None
    source_prefix: str | None
    sector_etf: str
    sector_name: str


@dataclass(frozen=True)
class SicCrosswalk:
    mapping_rule_version: str
    classification_system: str
    rules: tuple[SicCrosswalkRule, ...]


def normalize_sic_code(raw_value: object) -> str | None:
    """Normalize a SIC-like raw value to a four-digit code or ``None``."""
    if raw_value is None:
        return None
    text = "".join(ch for ch in str(raw_value).strip() if ch.isdigit())
    if not text:
        return None
    if len(text) < 4:
        return text.zfill(4)
    return text[:4]


def load_classification_source_policy(
    settings: IngestionSettings | None = None,
) -> ClassificationSourcePolicy:
    cfg = load_yaml_config("classification_sources.yaml", settings)
    primary = cfg.get("classification_sources", {}).get("primary", {})
    field_precedence = tuple(str(v) for v in primary.get("field_precedence", []))
    policy = ClassificationSourcePolicy(
        source_name=str(primary.get("source_name", "")),
        classification_system=str(primary.get("classification_system", "")),
        field_precedence=field_precedence,
        missing_policy=str(primary.get("missing_policy", "")),
    )
    if not policy.source_name:
        raise ValueError("classification_sources.primary.source_name is required")
    if policy.classification_system != "SEC_SIC_4":
        raise ValueError("classification_sources.primary.classification_system must be SEC_SIC_4")
    if field_precedence != ("dei:EntityPrimarySicNumber", "filing_header_sic"):
        raise ValueError(
            "classification_sources.primary.field_precedence must be "
            "['dei:EntityPrimarySicNumber', 'filing_header_sic']"
        )
    if policy.missing_policy != "keep_missing":
        raise ValueError("classification_sources.primary.missing_policy must be keep_missing")
    return policy


def load_sec_sic_crosswalk(settings: IngestionSettings | None = None) -> SicCrosswalk:
    cfg = load_yaml_config("sec_sic4_to_sector_etf.yaml", settings)
    node = cfg.get("sec_sic4_to_sector_etf", {})
    rules: list[SicCrosswalkRule] = []
    seen_exact: set[str] = set()
    seen_prefix: set[str] = set()
    for raw in node.get("mappings", []):
        source_exact = normalize_sic_code(raw.get("source_exact")) if raw.get("source_exact") else None
        source_prefix = str(raw.get("source_prefix", "")).strip() or None
        if bool(source_exact) == bool(source_prefix):
            raise ValueError("each SIC crosswalk rule must provide exactly one of source_exact/source_prefix")
        if source_prefix is not None and (not source_prefix.isdigit() or len(source_prefix) > 4):
            raise ValueError(f"invalid source_prefix {source_prefix!r}")
        sector_etf = str(raw.get("sector_etf", "")).strip()
        if sector_etf not in _ALLOWED_SECTOR_ETFS:
            raise ValueError(f"invalid target sector_etf {sector_etf!r}")
        if source_exact:
            if source_exact in seen_exact:
                raise ValueError(f"duplicate exact SIC mapping {source_exact}")
            seen_exact.add(source_exact)
        if source_prefix:
            if source_prefix in seen_prefix:
                raise ValueError(f"duplicate SIC prefix mapping {source_prefix}")
            seen_prefix.add(source_prefix)
        rules.append(
            SicCrosswalkRule(
                source_exact=source_exact,
                source_prefix=source_prefix,
                sector_etf=sector_etf,
                sector_name=str(raw.get("sector_name", sector_etf)).strip(),
            )
        )
    crosswalk = SicCrosswalk(
        mapping_rule_version=str(node.get("mapping_rule_version", "")),
        classification_system=str(node.get("classification_system", "")),
        rules=tuple(rules),
    )
    if not crosswalk.mapping_rule_version:
        raise ValueError("sec_sic4_to_sector_etf.mapping_rule_version is required")
    if crosswalk.classification_system != "SEC_SIC_4":
        raise ValueError("sec_sic4_to_sector_etf.classification_system must be SEC_SIC_4")
    if not crosswalk.rules:
        raise ValueError("sec_sic4_to_sector_etf.mappings must not be empty")
    return crosswalk


def resolve_sector_etf_from_sic(sic_code: str | None, crosswalk: SicCrosswalk) -> str | None:
    normalized = normalize_sic_code(sic_code)
    if normalized is None:
        return None
    for rule in crosswalk.rules:
        if rule.source_exact == normalized:
            return rule.sector_etf
    prefix_matches = [
        rule for rule in crosswalk.rules if rule.source_prefix and normalized.startswith(rule.source_prefix)
    ]
    if not prefix_matches:
        return None
    prefix_matches.sort(key=lambda r: len(r.source_prefix or ""), reverse=True)
    return prefix_matches[0].sector_etf


def build_effective_windows(observations_df: pl.DataFrame) -> pl.DataFrame:
    """
    Convert point-in-time classification observations into non-overlapping windows.

    Required input columns:
    - instrument_id
    - classification_system
    - effective_from
    """
    required = {"instrument_id", "classification_system", "effective_from"}
    missing = required - set(observations_df.columns)
    if missing:
        raise ValueError(f"observations_df missing columns: {sorted(missing)}")
    if observations_df.height == 0:
        return observations_df.with_columns(
            pl.lit(None, dtype=pl.Date).alias("effective_to")
        )

    sort_cols = ["instrument_id", "classification_system", "effective_from"]
    if "asof_timestamp" in observations_df.columns:
        sort_cols.append("asof_timestamp")

    dedupe_subset = ["instrument_id", "classification_system", "effective_from"]
    df = (
        observations_df.sort(sort_cols)
        .unique(subset=dedupe_subset, keep="last")
        .sort(["instrument_id", "classification_system", "effective_from"])
        .with_columns(pl.col("effective_from").cast(pl.Date))
        .with_columns(
            pl.col("effective_from")
            .shift(-1)
            .over(["instrument_id", "classification_system"])
            .alias("_next_effective_from")
        )
        .with_columns(
            pl.when(pl.col("_next_effective_from").is_null())
            .then(pl.lit(None, dtype=pl.Date))
            .otherwise(pl.col("_next_effective_from") - timedelta(days=1))
            .alias("effective_to")
        )
        .drop("_next_effective_from")
    )
    return df


def validate_non_overlapping_windows(df: pl.DataFrame) -> None:
    required = {"instrument_id", "classification_system", "effective_from", "effective_to"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"window frame missing columns: {sorted(missing)}")
    if df.height <= 1:
        return
    ordered = df.sort(["instrument_id", "classification_system", "effective_from"]).with_columns(
        pl.col("effective_to")
        .shift()
        .over(["instrument_id", "classification_system"])
        .alias("_prev_effective_to")
    )
    bad = ordered.filter(
        pl.col("_prev_effective_to").is_not_null()
        & (pl.col("effective_from") <= pl.col("_prev_effective_to"))
    )
    if bad.height > 0:
        raise ValueError("classification windows overlap")

