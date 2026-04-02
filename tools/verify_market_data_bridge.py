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
from market_data.common.pandera_contracts import validate_contract_df

try:
    from tools.verify_market_data_common import add_market_data_args, load_verification_settings
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_market_data_common import add_market_data_args, load_verification_settings


def _load_panel(path: Path) -> pl.DataFrame:
    df = pl.read_csv(path, try_parse_dates=True)
    incomplete_expr = (
        pl.col("is_incomplete_session")
        if df.schema.get("is_incomplete_session") == pl.Boolean
        else (
            pl.col("is_incomplete_session")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes"])
        )
    )
    return df.with_columns(
        pl.col("timestamp_utc").cast(pl.Datetime("us", "UTC")),
        incomplete_expr.alias("is_incomplete_session"),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
    )


def _normalized_path_str(path: str | Path) -> str:
    return str(Path(path).resolve())


def run_checks(
    *,
    panel_path: str,
    require_manifest: bool = False,
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

    panel = _load_panel(path)
    validate_contract_df("export_panel", panel)
    print(f"[bridge] export panel contract: ok ({len(panel)} rows)")

    manifest_path = Path(str(path) + ".manifest.json").resolve()
    if not manifest_path.exists():
        if require_manifest:
            raise SystemExit(f"[bridge] missing export manifest: {manifest_path}")
        print(f"[bridge] skip export manifest: missing {manifest_path}")
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_name") != "export_panel":
        raise SystemExit(f"[bridge] wrong contract_name in export manifest: {manifest.get('contract_name')}")
    if manifest.get("row_count") != len(panel):
        raise SystemExit("[bridge] export manifest row_count mismatch")
    if manifest.get("ticker_count") != panel["ticker"].n_unique():
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
        if not isinstance(domain_statuses, dict) or not isinstance(domain_statuses.get("required_core"), dict):
            raise SystemExit("[bridge] dataset manifest missing required_core domain status")
        required_core = domain_statuses["required_core"]
        if required_core.get("blocking_failures"):
            raise SystemExit("[bridge] dataset manifest reports required_core blocking failures")
        reports = dataset_manifest.get("reports")
        expected_export_manifest = reports.get("export_panel_manifest") if isinstance(reports, dict) else None
        if not expected_export_manifest or _normalized_path_str(expected_export_manifest) != str(manifest_path):
            raise SystemExit("[bridge] dataset manifest export_panel_manifest mismatch")
        for report_name in ("source_coverage_report", "unresolved_identity_report", "quarantine_report", "final_pass_fail_summary"):
            report_path = reports.get(report_name) if isinstance(reports, dict) else None
            if not report_path or not Path(report_path).exists():
                raise SystemExit(f"[bridge] dataset manifest missing required report: {report_name}")

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
    add_market_data_args(parser)
    args = parser.parse_args(argv)
    return run_checks(
        panel_path=args.panel_path,
        require_manifest=args.require_manifest,
        data_lake=args.data_lake,
        config_dir=args.config_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
