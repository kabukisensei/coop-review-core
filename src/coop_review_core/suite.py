"""Suite summary module: merge multiple tool envelopes into one branded engagement report.

This layer sits above the individual linters, aggregating their standard JSON
envelopes into a single combined artifact (console text or HTML).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from coop_review_core.errors import CoopReviewError
from coop_review_core.report import (
    BADGE,
    HTML_SCRIPT,
    HTML_STYLE,
    chip,
    esc,
    logo_data_uri,
    sty,
)
from coop_review_core.severity import SEVERITIES

__all__ = [
    "SuiteError",
    "load_envelopes",
    "suite_summary",
    "suite_text",
    "suite_html",
]


class SuiteError(CoopReviewError):
    """A user-facing problem loading or parsing suite envelopes."""


def load_envelopes(paths: Iterable[Path | str]) -> list[dict]:
    """Load and validate tool JSON envelopes from paths.
    Raises SuiteError on unreadable or mis-shaped files."""
    envelopes = []
    for path in paths:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8-sig")
            if "\x00" in text:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "null byte")
        except UnicodeDecodeError:
            raise SuiteError(f"{p}: not UTF-8") from None
        except OSError as exc:
            raise SuiteError(f"cannot read envelope {p}: {exc}") from exc
        try:
            env = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SuiteError(f"{p}: invalid JSON - {exc}") from exc
        if not isinstance(env, dict) or "tool" not in env or "verdict" not in env:
            raise SuiteError(f"{p}: not a valid coop-review envelope (missing 'tool' or 'verdict')")
        envelopes.append(env)
    return sorted(envelopes, key=lambda e: str(e.get("tool", "")))


def suite_summary(envelopes: list[dict]) -> dict:
    """Compute combined metrics across all loaded envelopes.

    Returns:
      {
        "tools": { tool_name: { "checked_key": "files_checked", "checked": 42, "standards": {...} } },
        "summary": { "error": 2, "warning": 1, "info": 0 },
        "verdict": { "clean": False, "highest_severity": "error" }
      }
    """
    tools = {}
    total_summary = {sev: 0 for sev in SEVERITIES}
    highest_severity = None
    clean = True

    for env in envelopes:
        tool = str(env.get("tool", "unknown"))
        checked_key = next((k for k in env if k.endswith("_checked")), "checked")
        tools[tool] = {
            "checked_key": checked_key,
            "checked": env.get(checked_key, 0),
            "standards": env.get("standards", {}),
        }

        env_summary = env.get("summary", {})
        for sev in SEVERITIES:
            total_summary[sev] += env_summary.get(sev, 0)

        env_verdict = env.get("verdict", {})
        if not env_verdict.get("clean", True):
            clean = False
            env_high = env_verdict.get("highest_severity")
            if env_high in SEVERITIES:
                if highest_severity is None or SEVERITIES.index(env_high) < SEVERITIES.index(
                    highest_severity
                ):
                    highest_severity = env_high

    return {
        "tools": tools,
        "summary": total_summary,
        "verdict": {"clean": clean, "highest_severity": highest_severity},
    }


def suite_text(envelopes: list[dict], summary: dict, color: bool = True) -> str:
    """A multi-tool console summary."""
    lines = []

    v = summary["verdict"]
    status_text = "CLEAN" if v["clean"] else "ISSUES FOUND"
    high_sev = v["highest_severity"]
    if not v["clean"] and high_sev in BADGE:
        status_text = f"ISSUES FOUND ({BADGE[high_sev].strip()})"

    lines.append(sty(f"== Suite Review: {status_text} ==", "bold", color=color))

    for sev in SEVERITIES:
        count = summary["summary"][sev]
        if count:
            label = BADGE.get(sev, sev.upper())
            lines.append(f"{label} {count:4d}")

    lines.append("")
    for tool, data in summary["tools"].items():
        lines.append(f"{tool}: {data['checked']} {data['checked_key'].replace('_checked', '(s)')}")

    return "\n".join(lines) + "\n"


def suite_html(envelopes: list[dict], summary: dict, html_paths: dict[str, str] = None) -> str:
    """A single self-contained branded HTML report spanning all tools."""
    if html_paths is None:
        html_paths = {}

    logo_uri = logo_data_uri()
    logo_img = f'<img src="{logo_uri}" alt="Cooptimize">' if logo_uri else ""

    v = summary["verdict"]
    status = "Clean" if v["clean"] else "Issues Found"
    high_sev = v["highest_severity"]
    status_pill = chip(high_sev) if high_sev else '<span class="pill info">Clean</span>'

    # Summary section
    summary_html = []
    for sev in SEVERITIES:
        count = summary["summary"][sev]
        if count:
            summary_html.append(f'<span class="pill {sev}">{count} {sev.title()}(s)</span>')

    tools_html = []
    for env in envelopes:
        tool = env.get("tool", "unknown")
        checked_key = next((k for k in env if k.endswith("_checked")), "checked")
        checked = env.get(checked_key, 0)
        noun = checked_key.replace("_checked", "(s)")

        tool_v = env.get("verdict", {})
        tool_status = (
            chip(tool_v.get("highest_severity"))
            if not tool_v.get("clean")
            else '<span class="chip info">Clean</span>'
        )

        link = ""
        if tool in html_paths:
            link = f' <a href="{esc(html_paths[tool])}">View full {tool} report</a>'

        tools_html.append(f"""
        <div class="card" style="padding: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0;">{esc(tool)} {tool_status}</h3>
                <span class="meta">{checked} {noun} checked{link}</span>
            </div>
        </div>
        """)

    pills_html = " ".join(summary_html) or '<span class="pill info">No findings</span>'
    tools_joined = "".join(tools_html)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Suite Review Summary</title>
<style>
{HTML_STYLE}
</style>
{HTML_SCRIPT}
</head>
<body>
<div class="wrap">
  <header class="brand">
    {logo_img}
    <div>
      <h1>Suite Review Summary</h1>
      <div class="sub">Cooptimize standards engagement</div>
    </div>
  </header>
  <div class="brandbar"></div>
  
  <div style="margin-bottom: 24px;">
    <h2 style="margin-top: 0;">Overall Verdict: {status} {status_pill}</h2>
    <div class="pills">{pills_html}</div>
  </div>
  
  <h2>Tool Summaries</h2>
  {tools_joined}
</div>
</body>
</html>
"""
    return html
