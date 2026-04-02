from __future__ import annotations

from dataclasses import dataclass

from market_data.common.settings import IngestionSettings, load_yaml_config


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    enabled: bool
    source_class: str
    roles: tuple[str, ...]
    raw_datasets: tuple[str, ...]
    bronze_datasets: tuple[str, ...]
    notes: str


_DEFAULT_SOURCE_CLASS = {
    "yfinance": "required_core",
    "alphavantage": "required_core",
    "stooq": "supplemental_support",
    "sec": "optional_enrichment",
    "fred": "optional_enrichment",
}

_DEFAULT_ROLES = {
    "yfinance": (
        "ohlcv_daily_primary",
        "benchmark_prices_primary",
    ),
    "alphavantage": (
        "listing_metadata_primary",
        "symbol_metadata_support",
        "corporate_actions_support",
    ),
    "stooq": (
        "ohlcv_daily_secondary",
        "intraday_secondary",
        "price_conflict_diagnostics",
    ),
    "sec": (
        "company_fundamentals_authoritative_when_available",
        "legal_name_authoritative_when_available",
        "entity_verification_support",
    ),
    "fred": (
        "macro_vintages_authoritative_when_available",
    ),
}

_BRONZE_DATASET_MAP = {
    ("yfinance", "daily"): "yfinance_daily",
    ("stooq", "daily"): "stooq_daily",
    ("stooq", "intraday"): "stooq_intraday",
    ("alphavantage", "listing_status"): "av_listing_status",
    ("alphavantage", "daily_adjusted"): "av_daily_adjusted",
    ("sec", "submissions"): "sec_submissions",
    ("sec", "companyfacts"): "sec_companyfacts",
    ("fred", "observations"): "fred_observations",
    ("fred", "vintages"): "fred_vintages",
}


def _normalize_raw_datasets(name: str, config: dict[str, object]) -> tuple[str, ...]:
    raw = config.get("raw")
    if isinstance(raw, dict):
        datasets = raw.get("datasets")
        if isinstance(datasets, list):
            return tuple(str(item) for item in datasets)

    datasets = config.get("datasets")
    if isinstance(datasets, list):
        return tuple(str(item) for item in datasets)

    granularity = config.get("granularity")
    if isinstance(granularity, list):
        return tuple(str(item) for item in granularity)

    return ()


def _normalize_bronze_datasets(name: str, config: dict[str, object], raw_datasets: tuple[str, ...]) -> tuple[str, ...]:
    bronze = config.get("bronze")
    if isinstance(bronze, dict):
        datasets = bronze.get("datasets")
        if isinstance(datasets, list):
            return tuple(str(item) for item in datasets)

    out: list[str] = []
    for dataset in raw_datasets:
        mapped = _BRONZE_DATASET_MAP.get((name, dataset))
        if mapped:
            out.append(mapped)
    return tuple(out)


def load_source_catalog(settings: IngestionSettings) -> dict[str, SourceDefinition]:
    cfg = load_yaml_config("sources.yaml", settings)
    sources = cfg.get("sources") or {}
    out: dict[str, SourceDefinition] = {}

    for name, raw_value in sources.items():
        if not isinstance(raw_value, dict):
            continue

        raw_datasets = _normalize_raw_datasets(name, raw_value)
        bronze_datasets = _normalize_bronze_datasets(name, raw_value, raw_datasets)
        roles = raw_value.get("roles")
        if not isinstance(roles, list):
            roles = list(_DEFAULT_ROLES.get(name, ()))

        out[name] = SourceDefinition(
            name=name,
            enabled=bool(raw_value.get("enabled", True)),
            source_class=str(raw_value.get("source_class") or _DEFAULT_SOURCE_CLASS.get(name, "supplemental_support")),
            roles=tuple(str(role) for role in roles),
            raw_datasets=raw_datasets,
            bronze_datasets=bronze_datasets,
            notes=str(raw_value.get("notes", "")).strip(),
        )

    return out


def enabled_raw_sources(settings: IngestionSettings) -> tuple[str, ...]:
    catalog = load_source_catalog(settings)
    return tuple(
        source.name
        for source in catalog.values()
        if source.enabled and source.raw_datasets
    )


def enabled_bronze_datasets(settings: IngestionSettings) -> tuple[str, ...]:
    catalog = load_source_catalog(settings)
    out: list[str] = []
    for source in catalog.values():
        if not source.enabled:
            continue
        for dataset in source.bronze_datasets:
            if dataset not in out:
                out.append(dataset)
    return tuple(out)
