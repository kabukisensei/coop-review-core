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
    "HTML_SCRIPT",
    "LOGO_PATH",
    "logo_data_uri",
    "esc",
    "chip",
    "filter_bar_html",
    "verdict",
    "build_envelope",
    "envelope_text",
    "diagnostic_json",
    "log_text",
    "SARIF_LEVEL",
    "SARIF_FINGERPRINT_KEY",
    "sarif_location",
    "to_sarif",
    "to_junit",
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
/* --- filtering --- */
.pill { cursor: pointer; user-select: none; transition: opacity 0.15s; }
.pill[data-active="false"] { opacity: 0.4; filter: grayscale(100%); }
#searchFilter { width: 100%; max-width: 320px; padding: 6px 12px; margin-left: auto;
  border: 1px solid var(--line); border-radius: 999px; font-family: inherit; font-size: 0.85rem;
  background: var(--card); color: var(--ink); outline: none; }
#searchFilter:focus { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(0,64,104,0.1); }
[hidden] { display: none !important; }
""".strip()

HTML_SCRIPT = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  const pills = document.querySelectorAll('.pills .pill');
  const search = document.getElementById('searchFilter');
  if (!pills.length && !search) return;

  const state = { text: '', severities: new Set() };
  
  pills.forEach(p => {
    const sev = p.dataset.sev;
    if (sev) {
      state.severities.add(sev);
      p.dataset.active = "true";
      p.addEventListener('click', () => {
        if (state.severities.has(sev)) {
          state.severities.delete(sev);
          p.dataset.active = "false";
        } else {
          state.severities.add(sev);
          p.dataset.active = "true";
        }
        update();
      });
    }
  });

  if (search) {
    search.addEventListener('input', (e) => {
      state.text = e.target.value;
      update();
    });
  }

  function update() {
    const term = state.text.toLowerCase();
    
    document.querySelectorAll('.card').forEach(card => {
      let cardHasVisible = false;
      const cardPath = (card.querySelector('.file')?.textContent || '').toLowerCase();
      
      card.querySelectorAll('.f').forEach(row => {
        const sev = row.dataset.sev || 'info';
        const text = (row.textContent || '').toLowerCase();
        
        const sevMatch = state.severities.has(sev);
        const textMatch = !term || text.includes(term) || cardPath.includes(term);
        const show = sevMatch && textMatch;
        
        row.hidden = !show;
        if (show) cardHasVisible = true;
      });
      
      card.hidden = !cardHasVisible;
    });
  }
});
</script>
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


def filter_bar_html() -> str:
    """The interactive search box for the HTML report chrome."""
    return '<input type="text" id="searchFilter" placeholder="Filter findings..." />'


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


# --- JUnit XML (Azure DevOps PublishTestResults@2 — native, no extension) -----------


def _junit_name(f: Mapping) -> str:
    """A stable per-finding test name from whatever a finding carries: ``file:line``
    (sql), else ``model :: object`` (dax), else the object/model, else ``?``."""
    file = str(f.get("file") or "")
    if file:
        line = f.get("line")
        return f"{file}:{line}" if line else file
    model = str(f.get("model") or "")
    obj = str(f.get("object") or "")
    if model and obj:
        return f"{model} :: {obj}"
    return obj or model or "?"


def to_junit(
    *,
    tool_name: str,
    version: str,
    findings: Sequence[Mapping],
    agent_review: Sequence[Mapping] = (),
    diagnostics: Sequence[Diagnostic] = (),
    checked: int = 0,
    unit: str = "file",
    diagnostics_rule_id: str = "syntax-error",
) -> str:
    """A deterministic JUnit XML report (string + trailing LF).

    Azure DevOps pipelines render SARIF only via a marketplace extension, but consume
    JUnit XML natively through the built-in ``PublishTestResults@2`` task — a Tests tab,
    failure counts, and run-over-run trends with zero extensions. Same plain-data
    contract as :func:`to_sarif` (core never imports a tool's ``Result``): ``findings`` /
    ``agent_review`` are mappings with ``rule_id`` / ``severity`` / ``file`` / ``line`` /
    ``message`` (agent items use ``note``); ``diagnostics`` are :class:`Diagnostic`.

    Each finding is a ``<testcase classname="<rule_id>" name="<file>:<line>">``: an
    **error**-severity finding becomes a ``<failure>``, a **warning**/**info** finding a
    ``<skipped>`` (advisory — only errors are hard failures; a caller wanting a stricter
    gate opts in with the tool's ``--strict``). Agent-review items are non-blocking
    ``<skipped>``. Each **error**-severity diagnostic is a ``<failure>`` under the synthetic
    diagnostics rule, mirroring :func:`to_sarif`. No timestamps (``time="0"``, no
    ``timestamp`` attr), sorted, XML-escaped via stdlib ``xml.sax.saxutils`` (no new runtime
    dep), ``ensure_ascii``-safe — byte-identical across runs and OSes."""
    from xml.sax.saxutils import escape, quoteattr

    rows: list[tuple[str, str, str, str, str]] = []  # (classname, name, kind, severity, message)
    for f in findings:
        sev = str(f.get("severity") or "info")
        rows.append(
            (
                str(f.get("rule_id") or ""),
                _junit_name(f),
                "failure" if sev == "error" else "skipped",
                sev,
                str(f.get("message") or ""),
            )
        )
    for a in agent_review:
        rows.append(
            (
                str(a.get("rule_id") or ""),
                _junit_name(a),
                "skipped",
                "info",
                str(a.get("note") or a.get("message") or ""),
            )
        )
    for d in diagnostics:
        if d.severity != "error":
            continue
        loc = f"{d.file}:{d.line}" if d.file else (d.category or diagnostics_rule_id)
        rows.append((diagnostics_rule_id, loc, "failure", "error", d.message))
    rows.sort()

    failures = sum(1 for r in rows if r[2] == "failure")
    skipped = sum(1 for r in rows if r[2] == "skipped")
    suite = (
        f"name={quoteattr(tool_name)} tests={quoteattr(str(len(rows)))} "
        f"failures={quoteattr(str(failures))} errors={quoteattr('0')} "
        f"skipped={quoteattr(str(skipped))} time={quoteattr('0')}"
    )
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f"<testsuites {suite}>", f"  <testsuite {suite}>"]
    out.append(
        "    <properties>"
        f"<property name={quoteattr('tool')} value={quoteattr(f'{tool_name} {version}')}/>"
        f"<property name={quoteattr(f'{unit}s_checked')} value={quoteattr(str(int(checked)))}/>"
        "</properties>"
    )
    for classname, name, kind, sev, msg in rows:
        attrs = f"classname={quoteattr(classname)} name={quoteattr(name)}"
        if kind == "failure":
            out.append(f"    <testcase {attrs}>")
            out.append(
                f"      <failure message={quoteattr(msg)} type={quoteattr(sev)}>{escape(msg)}</failure>"
            )
            out.append("    </testcase>")
        else:  # skipped
            out.append(f"    <testcase {attrs}>")
            out.append(f"      <skipped message={quoteattr(msg)}/>")
            out.append("    </testcase>")
    out += ["  </testsuite>", "</testsuites>"]
    return "\n".join(out) + "\n"
