"""
Generate a self-contained HTML dashboard from the latest demo reports.

Usage:
    python demo/generate_dashboard.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).parent.parent
SAMPLE_RUN = ROOT / "demo" / "sample_run"
OUTPUT_PATH = SAMPLE_RUN / "dashboard.html"


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def status_class(status: str | None) -> str:
    normalized = (status or "unknown").lower()
    if normalized == "passed":
        return "passed"
    if normalized in {"failed", "error"}:
        return "failed"
    return "unknown"


def count_status(results: list[dict], wanted: str) -> int:
    return sum(1 for result in results if str(result.get("status", "")).lower() == wanted)


def render_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    html_parts: list[str] = []
    in_list = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        if line.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{format_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h2>{format_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{format_inline(line[2:])}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<p>{format_inline(line)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def format_inline(text: str) -> str:
    escaped = escape(text)
    escaped = escaped.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
    while "`" in escaped:
        escaped = escaped.replace("`", "<code>", 1)
        if "`" in escaped:
            escaped = escaped.replace("`", "</code>", 1)
        else:
            break
    return escaped


def render_result_rows(results: list[dict]) -> str:
    if not results:
        return '<tr><td colspan="6" class="empty">No execution results found</td></tr>'

    rows = []
    for result in results:
        status = str(result.get("status", "unknown"))
        rows.append(
            "<tr>"
            f"<td>{escape(str(result.get('test_id', '-')))}</td>"
            f"<td><span class=\"pill {status_class(status)}\">{escape(status.upper())}</span></td>"
            f"<td>{escape(str(result.get('steps_executed', '-')))}</td>"
            f"<td>{escape(str(result.get('duration_ms', '-')))} ms</td>"
            f"<td>{escape(str(result.get('failure_reason') or '-'))}</td>"
            f"<td>{escape(str(result.get('error_message') or '-'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_live_rows(results: list[dict]) -> str:
    if not results:
        return '<tr><td colspan="6" class="empty">No live smoke results found</td></tr>'

    rows = []
    for result in results:
        status = str(result.get("status", "unknown"))
        missing = result.get("missing_text") or []
        rows.append(
            "<tr>"
            f"<td>{escape(str(result.get('name', '-')))}</td>"
            f"<td><a href=\"{escape(str(result.get('url', '#')))}\">{escape(str(result.get('url', '-')))}</a></td>"
            f"<td><span class=\"pill {status_class(status)}\">{escape(status.upper())}</span></td>"
            f"<td>{escape(str(result.get('status_code') or '-'))}</td>"
            f"<td>{escape(str(result.get('duration_ms', '-')))} ms</td>"
            f"<td>{escape(', '.join(missing) if missing else '-')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_audit_rows(records: list[dict]) -> str:
    if not records:
        return '<tr><td colspan="5" class="empty">No MCP audit records found</td></tr>'

    rows = []
    for record in records[-20:]:
        ok = bool(record.get("ok"))
        rows.append(
            "<tr>"
            f"<td>{escape(str(record.get('call_id', '-')))}</td>"
            f"<td>{escape(str(record.get('tool', '-')))}</td>"
            f"<td><span class=\"pill {'passed' if ok else 'failed'}\">{'OK' if ok else 'ERROR'}</span></td>"
            f"<td>{escape(str(record.get('duration_ms', '-')))} ms</td>"
            f"<td><code>{escape(json.dumps(record.get('args', {}), ensure_ascii=False))}</code></td>"
            "</tr>"
        )
    return "\n".join(rows)


def main() -> None:
    execution_log = load_json(SAMPLE_RUN / "execution_log.json", {})
    live_smoke = load_json(SAMPLE_RUN / "live_site_smoke.json", {})
    audit_log = load_json(SAMPLE_RUN / "mcp_audit_log.json", [])
    bug_report = load_text(SAMPLE_RUN / "bug_report.md")

    execution_results = execution_log.get("results", [])
    live_results = live_smoke.get("results", [])
    live_summary = live_smoke.get("summary", {})
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI-QEF Report Dashboard</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-alt: #eef4f1;
      --text: #18212b;
      --muted: #647184;
      --line: #d9e0e7;
      --accent: #0f766e;
      --accent-2: #b45309;
      --pass-bg: #dcfce7;
      --pass-text: #166534;
      --fail-bg: #fee2e2;
      --fail-text: #991b1b;
      --unknown-bg: #e5e7eb;
      --unknown-text: #374151;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}

    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}

    .wrap {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
    }}

    .topbar {{
      min-height: 88px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }}

    h1 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.15;
      font-weight: 760;
    }}

    .subtitle {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }}

    .meta {{
      display: grid;
      gap: 6px;
      min-width: 220px;
      color: var(--muted);
      font-size: 13px;
      text-align: right;
    }}

    main {{
      padding: 24px 0 40px;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}

    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 104px;
    }}

    .metric .label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}

    .metric .value {{
      margin-top: 10px;
      font-size: 28px;
      line-height: 1;
      font-weight: 760;
    }}

    .metric .note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}

    .section {{
      margin-top: 24px;
    }}

    .section-head {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 10px;
    }}

    h2 {{
      margin: 0;
      font-size: 19px;
      line-height: 1.25;
    }}

    .section-note {{
      color: var(--muted);
      font-size: 13px;
    }}

    .table-shell {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }}

    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}

    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      background: #fbfcfd;
    }}

    tr:last-child td {{
      border-bottom: 0;
    }}

    .pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 70px;
      min-height: 24px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }}

    .pill.passed {{
      background: var(--pass-bg);
      color: var(--pass-text);
    }}

    .pill.failed {{
      background: var(--fail-bg);
      color: var(--fail-text);
    }}

    .pill.unknown {{
      background: var(--unknown-bg);
      color: var(--unknown-text);
    }}

    .report {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      font-size: 14px;
      line-height: 1.55;
    }}

    .report h2 {{
      margin: 0 0 12px;
    }}

    .report h3 {{
      margin: 18px 0 8px;
      font-size: 16px;
    }}

    .report ul {{
      margin: 8px 0 0;
      padding-left: 20px;
    }}

    .report li {{
      margin: 7px 0;
    }}

    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      background: #eef2f7;
      border-radius: 5px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }}

    a {{
      color: var(--accent);
      text-decoration: none;
    }}

    a:hover {{
      text-decoration: underline;
    }}

    .empty {{
      color: var(--muted);
      text-align: center;
      padding: 24px;
    }}

    @media (max-width: 780px) {{
      .topbar {{
        align-items: flex-start;
        flex-direction: column;
        padding: 18px 0;
      }}

      .meta {{
        text-align: left;
      }}

      .summary-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    @media (max-width: 520px) {{
      .wrap {{
        width: min(100% - 20px, 1180px);
      }}

      .summary-grid {{
        grid-template-columns: 1fr;
      }}

      h1 {{
        font-size: 24px;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap topbar">
      <div>
        <h1>AI-QEF Report Dashboard</h1>
        <div class="subtitle">{escape(str(execution_log.get("requirement") or "Latest quality engineering run"))}</div>
      </div>
      <div class="meta">
        <div>Generated: {escape(generated_at)}</div>
        <div>Trace: {escape(str(execution_log.get("trace_id") or "-"))}</div>
        <div>Target: {escape(str(execution_log.get("target_env") or live_smoke.get("base_url") or "-"))}</div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <section class="summary-grid" aria-label="Run summary">
      <div class="metric">
        <div class="label">Framework Tests</div>
        <div class="value">{len(execution_results)}</div>
        <div class="note">{count_status(execution_results, "passed")} passed, {count_status(execution_results, "failed")} failed, {count_status(execution_results, "error")} errors</div>
      </div>
      <div class="metric">
        <div class="label">Live Smoke</div>
        <div class="value">{escape(str(live_summary.get("passed", 0)))}/{escape(str(live_summary.get("total", 0)))}</div>
        <div class="note">{escape(str(live_smoke.get("base_url") or "No live target recorded"))}</div>
      </div>
      <div class="metric">
        <div class="label">Healing Attempts</div>
        <div class="value">{escape(str(execution_log.get("healing_attempts", 0)))}</div>
        <div class="note">Guardrail retries: {escape(str(execution_log.get("guardrail_retry_count", 0)))}</div>
      </div>
      <div class="metric">
        <div class="label">MCP Audit Calls</div>
        <div class="value">{len(audit_log)}</div>
        <div class="note">Latest recorded tool boundary activity</div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Live Site Smoke</h2>
        <div class="section-note">Read-only checks against public pages</div>
      </div>
      <div class="table-shell">
        <table>
          <thead>
            <tr><th>Page</th><th>URL</th><th>Status</th><th>HTTP</th><th>Duration</th><th>Missing Text</th></tr>
          </thead>
          <tbody>
            {render_live_rows(live_results)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Execution Results</h2>
        <div class="section-note">Agent pipeline result artifact</div>
      </div>
      <div class="table-shell">
        <table>
          <thead>
            <tr><th>Test ID</th><th>Status</th><th>Steps</th><th>Duration</th><th>Reason</th><th>Message</th></tr>
          </thead>
          <tbody>
            {render_result_rows(execution_results)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Bug Report</h2>
        <div class="section-note">Generated Markdown rendered for review</div>
      </div>
      <div class="report">
        {render_markdown(bug_report) if bug_report else '<p class="empty">No bug report found</p>'}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>MCP Audit Trail</h2>
        <div class="section-note">Last 20 calls</div>
      </div>
      <div class="table-shell">
        <table>
          <thead>
            <tr><th>Call ID</th><th>Tool</th><th>Result</th><th>Duration</th><th>Arguments</th></tr>
          </thead>
          <tbody>
            {render_audit_rows(audit_log)}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
