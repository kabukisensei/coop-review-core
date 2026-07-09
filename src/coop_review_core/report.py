"""Shared report-rendering primitives for the coop-*-review linters.

The pieces of the report layer that were byte-identical between the linters live
here ONCE (issue #9): the ASCII console chrome (badges + ANSI styling), the
Cooptimize-branded HTML style block and bundled logo, the HTML escaping/chip
helpers, and the machine-JSON envelope (verdict + envelope + diagnostics log).
Each linter keeps its own ``Finding``/``Result`` model and renders from plain
data it passes in; core never imports a tool's types.

Everything here is deterministic and offline: no timestamps, no network,
``sort_keys`` + ``ensure_ascii`` on JSON, LF newlines — output is byte-identical
across runs and operating systems. The console chrome stays ASCII so it is safe
on a legacy Windows console (cp1252/cp437); ANSI escape bytes are themselves
ASCII, so even the colored chrome stays cp1252-safe.
"""

from __future__ import annotations

import base64
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from coop_review_core.diagnostics import Diagnostic
from coop_review_core.severity import SEVERITIES

__all__ = [
    "REPORT_WIDTH",
    "BADGE",
    "BADGE_COLOR",
    "ANSI",
    "sty",
    "HTML_STYLE",
    "LOGO_PATH",
    "logo_data_uri",
    "esc",
    "chip",
    "verdict",
    "build_envelope",
    "envelope_text",
    "diagnostic_json",
    "log_text",
    "SARIF_LEVEL",
    "SARIF_FINGERPRINT_KEY",
    "sarif_location",
    "to_sarif",
]

# --- console chrome -----------------------------------------------------------

REPORT_WIDTH = 72
BADGE = {"error": "ERROR", "warning": "WARN ", "info": "INFO "}
BADGE_COLOR = {"error": "red", "warning": "yellow", "info": "blue"}
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
}


def sty(text: str, *codes: str, color: bool) -> str:
    """Wrap text in ANSI codes when ``color`` is on; return it unchanged otherwise."""
    if not color or not codes:
        return text
    return "".join(ANSI[c] for c in codes) + text + ANSI["reset"]


# --- HTML report chrome ---------------------------------------------------------

# Cooptimize brand palette (sampled from the integrated logo): navy #004068,
# accent red-orange #e84028, green gradient #407838 / #80a840 / #b0d030.
HTML_STYLE = """
:root {
  --bg: #f6f8f9; --card: #ffffff; --ink: #14202b; --muted: #5c6b73; --line: #e4e8ea;
  --brand: #004068; --accent: #e84028;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --error: #c23b22; --error-bg: #fdece8; --warning: #8a5a00; --warning-bg: #fff5dd;
  --info: #3a5a72; --info-bg: #e9eef2;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5; }
.wrap { max-width: 960px; margin: 0 auto; padding: 28px 20px 64px; }
header.brand { display: flex; align-items: center; gap: 14px; }
header.brand img { height: 46px; width: auto; }
header.brand h1 { font-size: 1.4rem; margin: 0; letter-spacing: -0.01em; color: var(--brand); }
header.brand .sub { color: var(--muted); font-size: 0.85rem; }
.brandbar { height: 4px; border-radius: 4px; margin: 14px 0 18px;
  background: linear-gradient(90deg, #004068, #407838, #80a840, #b0d030); }
.meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 14px; }
.meta code { font-family: var(--mono); }
.pills { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 8px; }
.pill { font-size: 0.8rem; font-weight: 600; padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--card); }
.pill.error { color: var(--error); background: var(--error-bg); border-color: transparent; }
.pill.warning { color: var(--warning); background: var(--warning-bg); border-color: transparent; }
.pill.info { color: var(--info); background: var(--info-bg); border-color: transparent; }
.advisory { color: var(--muted); font-size: 0.85rem; margin: 4px 0 24px; }
h2 { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--brand);
  margin: 32px 0 12px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  margin-bottom: 14px; overflow: hidden; box-shadow: 0 1px 2px rgba(20,32,43,0.04); }
.file { font-family: var(--mono); font-size: 0.85rem; font-weight: 600; padding: 12px 16px;
  border-bottom: 1px solid var(--line); background: #fbfcfd; color: var(--brand);
  word-break: break-all; }
.f { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; padding: 12px 16px;
  border-bottom: 1px solid var(--line); }
.f:last-child { border-bottom: 0; }
.f.error { box-shadow: inset 3px 0 0 var(--accent); }
.chip { align-self: start; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.03em; padding: 3px 8px; border-radius: 6px; white-space: nowrap; }
.chip.error { color: var(--error); background: var(--error-bg); }
.chip.warning { color: var(--warning); background: var(--warning-bg); }
.chip.info { color: var(--info); background: var(--info-bg); }
.head { font-size: 0.8rem; color: var(--muted); font-family: var(--mono); }
.head .rule { color: var(--ink); font-weight: 600; }
.msg { grid-column: 2; }
.empty { color: var(--muted); padding: 24px; text-align: center; background: var(--card);
  border: 1px solid var(--line); border-radius: 12px; }
""".strip()

# The ONE bundled copy of the Cooptimize logo the whole family shares.
LOGO_PATH = Path(__file__).resolve().parent / "data" / "cooptimize-logo.png"


def logo_data_uri() -> str:
    """The bundled Cooptimize logo as a base64 data URI, so the HTML stays
    self-contained (no external image). Empty string if the asset is missing."""
    try:
        raw = LOGO_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def esc(value) -> str:
    """HTML-escape any value (quotes included) for safe interpolation."""
    return html.escape(str(value), quote=True)


def chip(severity: str) -> str:
    """A severity chip ``<span>``; an unknown severity styles as ``info``."""
    sev = severity if severity in SEVERITIES else "info"
    return f'<span class="chip {sev}">{esc(severity)}</span>'


# --- the machine-JSON envelope (the agent contract) -----------------------------


def verdict(summary: Mapping[str, int], *, has_findings: bool, has_error_diagnostic: bool) -> dict:
    """A compact, advisory machine verdict the agent can route on (never a gate).

    An error-severity diagnostic (a genuine syntax error, a rule crash, an
    unreadable file) makes the run **not clean** even with zero findings — the
    tool's coverage of that input is compromised, which the agent must not read
    as a clean pass. It is also the most severe signal the tool can emit, so it
    sets ``highest_severity`` to ``error``.

    ``summary`` is the tool's per-severity finding count (``result.summary()``);
    ``has_findings`` / ``has_error_diagnostic`` are passed explicitly so core
    never touches a tool's ``Result`` type.
    """
    present = [s for s in SEVERITIES if summary.get(s)]
    highest = "error" if has_error_diagnostic else (present[0] if present else None)
    return {"clean": not has_findings and not has_error_diagnostic, "highest_severity": highest}


def build_envelope(
    *,
    tool: str,
    schema_version: int,
    version: str,
    standards: Mapping[str, str],
    checked_key: str,
    checked: int,
    verdict: dict,
    findings: list[dict],
    summary: Mapping[str, int],
    agent_review: list[dict],
    diagnostics: list[dict],
) -> dict:
    """The shared JSON envelope both linters emit, from pre-serialized parts.

    The tool supplies its identity (``tool`` / ``version`` / its own
    ``schema_version``), its checked-count key (``"files_checked"`` for
    coop-sql-review, ``"models_checked"`` for coop-dax-review), and its
    already-rendered ``findings`` / ``agent_review`` / ``diagnostics`` dicts —
    core owns only the envelope shape, so each tool's finding fields (e.g. dax's
    ``model`` key) stay tool-side. Serialized via :func:`envelope_text` this
    reproduces each tool's current ``json_text`` output byte-for-byte.
    """
    return {
        "tool": tool,
        "schema_version": schema_version,
        "version": version,
        "standards": {"path": standards.get("path", ""), "sha256": standards.get("sha256", "")},
        checked_key: checked,
        "verdict": verdict,
        "findings": findings,
        "summary": dict(summary),
        "agent_review": agent_review,
        "diagnostics": diagnostics,
    }


def envelope_text(envelope: dict) -> str:
    """JSON string with a trailing newline, sorted keys, LF line endings.

    ``ensure_ascii=True`` keeps the output pure ASCII: deterministic + safe on
    any Windows console/code page.
    """
    return json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def diagnostic_json(diagnostic: Diagnostic) -> dict:
    """One diagnostic as the JSON dict both linters' envelopes carry."""
    return {
        "severity": diagnostic.severity,
        "category": diagnostic.category,
        "file": diagnostic.file,
        "line": diagnostic.line,
        "message": diagnostic.message,
        "rule_id": diagnostic.rule_id,
    }


def log_text(diagnostics: Sequence[Diagnostic], *, tool: str, checked: int, unit: str) -> str:
    """Full diagnostics log for ``--log-file``: every processing problem, one per
    line, deterministically ordered (the caller passes them pre-sorted).
    Empty-safe. ``unit`` is the tool's input noun (``"file"`` / ``"model"``)."""
    header = f"{tool} diagnostics log - {checked} {unit}(s) checked"
    if not diagnostics:
        return header + "\nNo diagnostics.\n"
    body = "\n".join(diag.as_line() for diag in diagnostics)
    return f"{header}\n{body}\n"


# --- SARIF 2.1.0 (GitHub code scanning / Azure DevOps PR annotations) ----------------

SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}
# Default partialFingerprints KEY, deliberately frozen at v2 for coop-sql-review
# (its shipped value). GitHub code scanning matches alerts across runs by
# (key, value) pair; renaming an already-shipped key would orphan every existing
# alert and re-open it as new. The VALUES are whatever fingerprint scheme the
# tool computes today — only the label stays put. A tool bumps ITS key (via the
# ``fingerprint_key`` parameter) only if a future scheme changes identities so
# broadly that a clean alert reset is the better trade.
SARIF_FINGERPRINT_KEY = "coopFingerprint/v2"


def sarif_location(uri: str, line: int) -> dict:
    """One SARIF physical location; the region is omitted for file-level results (line 0)."""
    phys: dict = {"artifactLocation": {"uri": uri}}
    if line:
        phys["region"] = {"startLine": line}
    return {"physicalLocation": phys}


def to_sarif(
    *,
    tool_name: str,
    information_uri: str,
    version: str,
    driver_rules: list[dict],
    findings: Sequence[Mapping],
    agent_review: Sequence[Mapping] = (),
    diagnostics: Sequence[Diagnostic] = (),
    diagnostics_rule_id: str = "syntax-error",
    diagnostics_rule_description: str = (
        "A processing problem: a real syntax error, a rule crash, or an unreadable file."
    ),
    fingerprint_key: str = SARIF_FINGERPRINT_KEY,
) -> str:
    """A deterministic single-run SARIF 2.1.0 log (string + trailing LF).

    Findings/agent-items/error-diagnostics become ``results`` with SARIF ``level``
    (error/warning/note), a physical location, and ``partialFingerprints`` (GitHub
    uses them to dedupe alerts across runs). Warning-severity diagnostics are
    advisory processing notes and are intentionally NOT emitted. No timestamps ->
    byte-stable (``sort_keys`` + ``ensure_ascii``).

    The linter supplies its identity and metadata as plain data:

    - ``driver_rules``: its pre-built SARIF rule entries (``id`` / ``name`` /
      ``shortDescription`` / ``defaultConfiguration`` / ``properties``), WITHOUT
      the synthetic diagnostics rule — core appends that one (``ruleIndex`` =
      ``len(driver_rules)``) so genuinely broken input still annotates the PR line.
    - ``findings``: mappings with ``rule_id`` / ``severity`` / ``file`` / ``line``
      / ``message`` / ``fingerprint`` (the fingerprint pre-computed tool-side).
    - ``agent_review``: mappings with ``rule_id`` / ``note`` / ``file`` / ``line``
      / ``fingerprint`` — judgment items are visible but never blocking (``note``).
    - ``fingerprint_key``: the partialFingerprints label. coop-sql-review MUST
      keep passing (or defaulting to) ``coopFingerprint/v2`` — see the frozen-key
      note on :data:`SARIF_FINGERPRINT_KEY`.
    """
    rule_index = {rule["id"]: i for i, rule in enumerate(driver_rules)}
    all_rules = list(driver_rules)
    diag_index = len(all_rules)
    all_rules.append(
        {
            "id": diagnostics_rule_id,
            "name": diagnostics_rule_id,
            "shortDescription": {"text": diagnostics_rule_description},
            "defaultConfiguration": {"level": "error"},
        }
    )

    results: list[dict] = []
    for f in findings:
        row = {
            "ruleId": f["rule_id"],
            "level": SARIF_LEVEL.get(f["severity"], "note"),
            "message": {"text": f["message"]},
            "locations": [sarif_location(f["file"], f["line"])],
            "partialFingerprints": {fingerprint_key: f["fingerprint"]},
        }
        if f["rule_id"] in rule_index:
            row["ruleIndex"] = rule_index[f["rule_id"]]
        results.append(row)
    for a in agent_review:
        row = {
            "ruleId": a["rule_id"],
            "level": "note",  # judgment items are visible but never blocking
            "message": {"text": a["note"]},
            "locations": [sarif_location(a["file"], a["line"])],
            "partialFingerprints": {fingerprint_key: a["fingerprint"]},
        }
        if a["rule_id"] in rule_index:
            row["ruleIndex"] = rule_index[a["rule_id"]]
        results.append(row)
    for d in diagnostics:
        if d.severity != "error":
            continue  # warning-severity processing notes are not surfaced as SARIF results
        results.append(
            {
                "ruleId": diagnostics_rule_id,
                "ruleIndex": diag_index,
                "level": "error",
                "message": {"text": d.message},
                "locations": [sarif_location(d.file, d.line)],
            }
        )

    log = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": version,
                        "informationUri": information_uri,
                        "rules": all_rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(log, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
