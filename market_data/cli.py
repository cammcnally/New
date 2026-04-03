"""CLI entry point: ``python -m market_data.cli``."""
from __future__ import annotations

import json

import click

from market_data.common.logging import setup_logging, get_logger
from market_data.common.settings import get_settings
from market_data.common.paths import ensure_lake_dirs


@click.group()
@click.option("--config-dir", default=None, help="Override configs directory path")
@click.option("--data-lake", default=None, help="Override data-lake root path")
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
)
@click.pass_context
def cli(ctx: click.Context, config_dir: str | None, data_lake: str | None, log_level: str) -> None:
    """PIT-correct U.S. equities ingestion pipeline."""
    setup_logging(log_level)
    overrides: dict = {"log_level": log_level}
    if config_dir:
        from pathlib import Path
        overrides["configs_dir"] = Path(config_dir)
    if data_lake:
        from pathlib import Path
        overrides["data_lake_root"] = Path(data_lake)
    settings = get_settings(**overrides)
    ensure_lake_dirs(settings)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = settings


# ── Primary commands ──────────────────────────────────────────────────────────

@cli.command()
@click.option("--start-date", required=True, help="Historical start date YYYY-MM-DD")
@click.option("--end-date", default=None, help="End date (default: today)")
@click.pass_context
def bootstrap(ctx: click.Context, start_date: str, end_date: str | None) -> None:
    """Full historical backfill. Run once to initialize the data lake."""
    log = get_logger("cli.bootstrap")
    settings = ctx.obj["settings"]
    log.info("BOOTSTRAP: start=%s end=%s", start_date, end_date or "today")
    from market_data.orchestration.sync import run_bootstrap
    run_bootstrap(settings=settings, start_date=start_date, end_date=end_date)


@cli.command()
@click.pass_context
def sync(ctx: click.Context) -> None:
    """Incremental update from last watermark. Requires prior bootstrap."""
    log = get_logger("cli.sync")
    settings = ctx.obj["settings"]
    log.info("SYNC: incremental from watermark")
    from market_data.orchestration.sync import run_sync
    run_sync(settings=settings)


@cli.command("export-latest")
@click.option("--output", default=None, help="Output CSV path (default: panel_ohlcv_clean.csv)")
@click.option(
    "--skip-universe-filter",
    is_flag=True,
    default=False,
    help="Export all symbols in the date range (ignore silver/universe_membership). Emergency use only.",
)
@click.pass_context
def export_latest(ctx: click.Context, output: str | None, skip_universe_filter: bool) -> None:
    """Export latest validated snapshot as Pipeline.py-compatible CSV."""
    log = get_logger("cli.export")
    settings = ctx.obj["settings"]
    from market_data.common.manifest import read_watermark
    wm = read_watermark(settings)
    if wm is None:
        raise click.ClickException("No watermark found. Run bootstrap first.")
    log.info("EXPORT-LATEST: %s -> %s", wm["start_date"], wm["end_date"])
    from market_data.bridge.export_pipeline_panel import export_panel
    export_panel(
        settings=settings, output_path=output,
        start_date=wm["start_date"], end_date=wm["end_date"],
        skip_universe_filter=skip_universe_filter,
    )


@cli.command("export-asof")
@click.option("--asof-date", required=True, help="Export as of this date YYYY-MM-DD")
@click.option("--output", default=None, help="Output CSV path")
@click.option(
    "--skip-universe-filter",
    is_flag=True,
    default=False,
    help="Export all symbols in the date range (ignore silver/universe_membership). Emergency use only.",
)
@click.pass_context
def export_asof(ctx: click.Context, asof_date: str, output: str | None, skip_universe_filter: bool) -> None:
    """Export dataset as of a specific date for reproducible testing."""
    log = get_logger("cli.export_asof")
    settings = ctx.obj["settings"]
    from market_data.common.manifest import read_watermark
    wm = read_watermark(settings)
    if wm is None:
        raise click.ClickException("No watermark found. Run bootstrap first.")
    log.info("EXPORT-ASOF: %s -> %s", wm["start_date"], asof_date)
    from market_data.bridge.export_pipeline_panel import export_panel
    export_panel(
        settings=settings, output_path=output,
        start_date=wm["start_date"], end_date=asof_date,
        skip_universe_filter=skip_universe_filter,
    )


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current data lake state, freshness, and coverage."""
    settings = ctx.obj["settings"]
    from market_data.orchestration.sync import run_status
    result = run_status(settings=settings)
    click.echo(json.dumps(result, indent=2, default=str))


# ── Granular / debug commands ────────────────────────────────────────────────

@cli.command()
@click.option("--source", default="all", help="Source: stooq|alphavantage|sec|fred|all")
@click.option("--start-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--end-date", required=True, help="End date YYYY-MM-DD")
@click.option("--full-refresh", is_flag=True, default=False)
@click.option("--symbols-file", default=None)
@click.option("--fail-fast", is_flag=True, default=False)
@click.pass_context
def raw(ctx: click.Context, source: str, start_date: str, end_date: str,
        full_refresh: bool, symbols_file: str | None, fail_fast: bool) -> None:
    """[Debug] Ingest raw data from external sources."""
    settings = ctx.obj["settings"]
    from market_data.orchestration.run_raw import run_raw
    run_raw(settings=settings, source=source, start_date=start_date, end_date=end_date,
            full_refresh=full_refresh, symbols_file=symbols_file, fail_fast=fail_fast)


@cli.command()
@click.option("--dataset", default="all")
@click.option("--start-date", required=True)
@click.option("--end-date", required=True)
@click.option("--full-refresh", is_flag=True, default=False)
@click.option("--fail-fast", is_flag=True, default=False)
@click.pass_context
def bronze(ctx: click.Context, dataset: str, start_date: str, end_date: str,
           full_refresh: bool, fail_fast: bool) -> None:
    """[Debug] Normalize raw data into typed bronze tables."""
    settings = ctx.obj["settings"]
    from market_data.orchestration.run_bronze import run_bronze
    run_bronze(settings=settings, dataset=dataset, start_date=start_date, end_date=end_date,
               full_refresh=full_refresh, fail_fast=fail_fast)


@cli.command()
@click.option("--dataset", default="all")
@click.option("--start-date", required=True)
@click.option("--end-date", required=True)
@click.option("--full-refresh", is_flag=True, default=False)
@click.option("--fail-fast", is_flag=True, default=False)
@click.pass_context
def silver(ctx: click.Context, dataset: str, start_date: str, end_date: str,
           full_refresh: bool, fail_fast: bool) -> None:
    """[Debug] Build PIT-correct silver domain tables."""
    settings = ctx.obj["settings"]
    from market_data.orchestration.run_silver import run_silver
    run_silver(settings=settings, dataset=dataset, start_date=start_date, end_date=end_date,
               full_refresh=full_refresh, fail_fast=fail_fast)


@cli.command()
@click.option("--all", "run_all_checks", is_flag=True, default=True)
@click.option("--fail-fast", is_flag=True, default=False)
@click.pass_context
def qa(ctx: click.Context, run_all_checks: bool, fail_fast: bool) -> None:
    """[Debug] Run QA checks and generate audit report."""
    settings = ctx.obj["settings"]
    from market_data.orchestration.run_qa import run_qa
    run_qa(settings=settings, fail_fast=fail_fast)


@cli.command("register-views")
@click.pass_context
def register_views(ctx: click.Context) -> None:
    """Register all Parquet datasets as DuckDB views."""
    settings = ctx.obj["settings"]
    from market_data.common.duckdb_utils import register_all_views
    from market_data.common.paths import duckdb_path
    con = register_all_views()
    tables = con.execute("SHOW TABLES").fetchall()
    click.echo(f"registered {len(tables)} views in {duckdb_path(settings)}")
    con.close()


# ── __main__ support ──────────────────────────────────────────────────────────

def main() -> None:
    cli(auto_envvar_prefix="MARKET_DATA")


if __name__ == "__main__":
    main()
