from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_data.common.hashing import hash_file
from market_data.common.manifest import current_dataset_build_id, dataset_manifest_path, read_manifest, stable_content_id

try:
    from tools.verify_market_data_common import add_market_data_args, load_verification_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import add_market_data_args, load_verification_settings


def _incomplete_session_expr() -> pl.Expr:
    c = pl.col("is_incomplete_session")
    return (
        pl.when(c.cast(pl.Utf8, strict=False).str.to_lowercase().is_in(["true", "1", "yes"]))
        .then(pl.lit(True))
        .when(c.cast(pl.Utf8, strict=False).str.to_lowercase().is_in(["false", "0", "no"]))
        .then(pl.lit(False))
        .otherwise(c.cast(pl.Boolean, strict=False))
    )


def _scan_normalized_export_panel(path: Path) -> pl.LazyFrame:
    """Lazy scan of the export CSV with the same column semantics as the legacy eager loader."""
    lf = pl.scan_csv(path, try_parse_dates=True, infer_schema_length=50_000)
    return lf.with_columns(
        pl.col("timestamp_utc").cast(pl.Datetime("us", "UTC")),
        _incomplete_session_expr().alias("is_incomplete_session"),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
    )


def _lazy_export_panel_contract_checks(lf: pl.LazyFrame) -> None:
    """Mirror ``export_panel`` Pandera + custom checks without materializing the full panel."""
    nulls = lf.null_count().collect()
    for col in (
        "ticker",
        "timestamp_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_incomplete_session",
    ):
        if col not in nulls.columns:
            raise SystemExit(f"[bridge] export panel missing column: {col}")
        if nulls[col][0] > 0:
            raise SystemExit(f"[bridge] export panel null values in column: {col}")

    dupes = (
        lf.group_by(["ticker", "timestamp_utc"])
        .len()
        .filter(pl.col("len") > 1)
        .select(pl.len())
        .collect()
        .item()
    )
    if dupes > 0:
        raise SystemExit("[bridge] export panel duplicate (ticker, timestamp_utc) keys")

    bad_ohlc = lf.filter(
        (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("low") > pl.col("high"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
    ).select(pl.len())
    if bad_ohlc.collect().item() > 0:
        raise SystemExit("[bridge] export panel invalid OHLC bounds")

    neg_vol = lf.filter(pl.col("volume") < 0).select(pl.len())
    if neg_vol.collect().item() > 0:
        raise SystemExit("[bridge] export panel negative volume")


def _normalized_path_str(path: str | Path) -> str:
    return str(Path(path).resolve())


def run_checks(
    *,
    panel_path: str,
    require_manifest: bool = False,
    require_benchmark_artifacts: bool = False,
    data_lake: str | None = None,
    config_dir: str | None = None,
) -> int:
    args = argparse.Namespace(data_lake=data_lake, config_dir=config_dir)
    settings = load_verification_settings(args)
    path = Path(panel_path).resolve()
    if not path.exists():
        if require_manifest:
            raise SystemExit(f"[bridge] missing export panel: {path}")
        print(f"[bridge] skip export panel: missing {path}")
        return 0

    lf = _scan_normalized_export_panel(path)
    _lazy_export_panel_contract_checks(lf)

    row_count = lf.select(pl.len()).collect().item()
    ticker_count = lf.select(pl.col("ticker").n_unique()).collect().item()
    print(f"[bridge] export panel contract: ok ({row_count} rows)")

    manifest_path = Path(str(path) + ".manifest.json").resolve()
    if not manifest_path.exists():
        if require_manifest:
            raise SystemExit(f"[bridge] missing export manifest: {manifest_path}")
        print(f"[bridge] skip export manifest: missing {manifest_path}")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_name") != "export_panel":
        raise SystemExit(f"[bridge] wrong contract_name in export manifest: {manifest.get('contract_name')}")
    if manifest.get("row_count") != row_count:
        raise SystemExit("[bridge] export manifest row_count mismatch")
    if manifest.get("ticker_count") != ticker_count:
        raise SystemExit("[bridge] export manifest ticker_count mismatch")
    content_hash = hash_file(path)
    if manifest.get("content_hash") != content_hash:
        raise SystemExit("[bridge] export manifest content_hash mismatch")
    if manifest.get("export_panel_version_id") != stable_content_id("export-panel", content_hash):
        raise SystemExit("[bridge] export manifest export_panel_version_id mismatch")
    if not manifest.get("dataset_build_id"):
        raise SystemExit("[bridge] export manifest missing dataset_build_id")
    if not manifest.get("start_date") or not manifest.get("end_date"):
        raise SystemExit("[bridge] export manifest missing date range")
    if "verification_artifacts" not in manifest or not isinstance(manifest["verification_artifacts"], list):
        raise SystemExit("[bridge] export manifest missing verification_artifacts")
    if "deferred_components" not in manifest or not isinstance(manifest["deferred_components"], list):
        raise SystemExit("[bridge] export manifest missing deferred_components")
    if "side_artifacts" not in manifest or not isinstance(manifest["side_artifacts"], dict):
        raise SystemExit("[bridge] export manifest missing side_artifacts")
    if require_benchmark_artifacts:
        benchmark_surface = manifest["side_artifacts"].get("benchmark_surface_daily")
        if not benchmark_surface:
            raise SystemExit("[bridge] export manifest missing benchmark_surface_daily side artifact")
        benchmark_surface_path = Path(str(benchmark_surface)).resolve()
        if not benchmark_surface_path.exists():
            raise SystemExit("[bridge] missing benchmark_surface_daily artifact")
        benchmark_df = pl.read_parquet(benchmark_surface_path)
        required_cols = {"date", "spy_ret_1d", "spy_cumret"}
        missing_cols = required_cols - set(benchmark_df.columns)
        if missing_cols:
            raise SystemExit(
                f"[bridge] benchmark_surface_daily missing required columns: {sorted(missing_cols)}"
            )
    expected_dataset_build_id = current_dataset_build_id(settings)
    if require_manifest and not expected_dataset_build_id:
        raise SystemExit(f"[bridge] missing dataset manifest: {dataset_manifest_path(settings)}")
    if expected_dataset_build_id and manifest.get("dataset_build_id") != expected_dataset_build_id:
        raise SystemExit("[bridge] export manifest dataset_build_id mismatch")
    if expected_dataset_build_id:
        dataset_manifest = read_manifest(dataset_manifest_path(settings))
        if dataset_manifest.get("canonical_export_ready") is False:
            raise SystemExit("[bridge] dataset manifest canonical_export_ready=false")
        if dataset_manifest.get("compatibility_fallback_used") is True:
            raise SystemExit("[bridge] dataset manifest compatibility_fallback_used=true")
        domain_statuses = dataset_manifest.get("domain_statuses")
        has_domain_gate = isinstance(domain_statuses, dict) and isinstance(
            domain_statuses.get("required_core"), dict
        )
        if has_domain_gate:
            required_core = domain_statuses["required_core"]
            if required_core.get("blocking_failures"):
                raise SystemExit("[bridge] dataset manifest reports required_core blocking failures")
            reports = dataset_manifest.get("reports")
            expected_export_manifest = reports.get("export_panel_manifest") if isinstance(reports, dict) else None
            if not expected_export_manifest or _normalized_path_str(expected_export_manifest) != str(
                manifest_path
            ):
                raise SystemExit("[bridge] dataset manifest export_panel_manifest mismatch")
            for report_name in (
                "source_coverage_report",
                "unresolved_identity_report",
                "quarantine_report",
                "final_pass_fail_summary",
            ):
                report_path = reports.get(report_name) if isinstance(reports, dict) else None
                if not report_path or not Path(report_path).exists():
                    raise SystemExit(f"[bridge] dataset manifest missing required report: {report_name}")
        else:
            print(
                "[bridge] warn: dataset manifest missing domain_statuses.required_core; "
                "skipping domain/report linkage checks (refresh via market_data orchestration)"
            )

    print(f"[bridge] export manifest: ok ({manifest_path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the exported panel bridge surface.")
    parser.add_argument(
        "--panel-path",
        default="panel_ohlcv_clean.csv",
        help="Path to exported panel CSV",
    )
    parser.add_argument(
        "--require-manifest",
        action="store_true",
        help="Fail if the export sidecar manifest is missing",
    )
    parser.add_argument(
        "--require-benchmark-artifacts",
        action="store_true",
        help="Fail if benchmark side artifacts are missing from the export manifest",
    )
    add_market_data_args(parser)
    args = parser.parse_args(argv)
    return run_checks(
        panel_path=args.panel_path,
        require_manifest=args.require_manifest,
        require_benchmark_artifacts=args.require_benchmark_artifacts,
        data_lake=args.data_lake,
        config_dir=args.config_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
