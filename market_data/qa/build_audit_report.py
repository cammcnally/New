"""Build the QA audit report (HTML + JSON)."""
from __future__ import annotations

import json

from market_data.common.dates import utc_now
from market_data.common.logging import get_logger
from market_data.common.paths import qa_dir
from market_data.common.settings import IngestionSettings

log = get_logger("qa.audit_report")

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Data Lake QA Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; }}
    h1 {{ color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: .5rem; }}
    h2 {{ color: #2a2a2a; margin-top: 2rem; }}
    .summary {{ display: flex; gap: 1.5rem; margin: 1rem 0; }}
    .card {{ background: #fff; border-radius: 8px; padding: 1rem 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,.12); min-width: 120px; }}
    .card.pass {{ border-left: 4px solid #22c55e; }}
    .card.fail {{ border-left: 4px solid #ef4444; }}
    .card.warn {{ border-left: 4px solid #f59e0b; }}
    .card .label {{ font-size: .85rem; color: #666; }}
    .card .value {{ font-size: 1.5rem; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin: .5rem 0; }}
    th, td {{ text-align: left; padding: .4rem .8rem; border-bottom: 1px solid #ddd; }}
    th {{ background: #f0f0f0; font-weight: 600; }}
    .error {{ color: #dc2626; }}
    .warning {{ color: #d97706; }}
    .pass-text {{ color: #16a34a; }}
  </style>
</head>
<body>
  <h1>Data Lake QA Audit Report</h1>
  <p>Generated: {timestamp}</p>
  <div class="summary">
    <div class="card {overall_class}">
      <div class="label">Overall</div>
      <div class="value">{overall_status}</div>
    </div>
    <div class="card {error_class}">
      <div class="label">Errors</div>
      <div class="value">{total_errors}</div>
    </div>
    <div class="card {warn_class}">
      <div class="label">Warnings</div>
      <div class="value">{total_warnings}</div>
    </div>
    <div class="card pass">
      <div class="label">Modules</div>
      <div class="value">{module_count}</div>
    </div>
  </div>
  {module_sections}
</body>
</html>
"""


def _render_list(items: list[str], css_class: str, label: str) -> str:
    if not items:
        return ""
    rows = "".join(
        f"<tr><td class='{css_class}'>{item}</td></tr>" for item in items
    )
    return f"<h3>{label} ({len(items)})</h3><table>{rows}</table>"


def _render_stats(stats: dict) -> str:
    if not stats:
        return ""
    rows = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in sorted(stats.items())
    )
    return f"<h3>Stats</h3><table>{rows}</table>"


def _render_module(name: str, result: dict) -> str:
    errs = result.get("errors", [])
    warns = result.get("warnings", [])
    stats = result.get("stats", {})

    if errs:
        verdict = '<span class="error">FAIL</span>'
    elif warns:
        verdict = '<span class="warning">WARN</span>'
    else:
        verdict = '<span class="pass-text">PASS</span>'

    return (
        f"<h2>{name} &mdash; {verdict}</h2>\n"
        + _render_list(errs, "error", "Errors")
        + _render_list(warns, "warning", "Warnings")
        + _render_stats(stats)
    )


def build_report(
    *,
    settings: IngestionSettings,
    findings: dict[str, object],
) -> None:
    out = qa_dir(settings)
    out.mkdir(parents=True, exist_ok=True)

    total_errors = 0
    total_warnings = 0
    sections: list[str] = []

    for mod_name, result in sorted(findings.items()):
        if not isinstance(result, dict):
            continue
        errs = result.get("errors", [])
        warns = result.get("warnings", [])
        total_errors += len(errs)
        total_warnings += len(warns)
        sections.append(_render_module(mod_name, result))

    if total_errors > 0:
        overall_status, overall_class = "FAIL", "fail"
    elif total_warnings > 0:
        overall_status, overall_class = "WARN", "warn"
    else:
        overall_status, overall_class = "PASS", "pass"

    timestamp = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")

    html = _HTML_TEMPLATE.format(
        timestamp=timestamp,
        overall_class=overall_class,
        overall_status=overall_status,
        error_class="fail" if total_errors else "pass",
        total_errors=total_errors,
        warn_class="warn" if total_warnings else "pass",
        total_warnings=total_warnings,
        module_count=len(findings),
        module_sections="\n".join(sections),
    )

    (out / "report.html").write_text(html, encoding="utf-8")
    log.info("wrote %s", out / "report.html")

    json_out = {
        "generated_at": timestamp,
        "overall": overall_status.lower(),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "modules": findings,
    }
    (out / "audit_findings.json").write_text(
        json.dumps(json_out, indent=2, default=str), encoding="utf-8"
    )
    log.info("wrote %s", out / "audit_findings.json")
