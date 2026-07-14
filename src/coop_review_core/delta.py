"""Run-to-run comparison of two review envelopes (issue #29).

Core already owns the two halves this needs: the stable, line- and
path-independent fingerprint (:mod:`severity`) and the machine-JSON envelope
shape (:func:`report.build_envelope`). This module turns two envelopes from the
**same tool** into a delta — what is NEW, what got FIXED, and how many findings
PERSIST — the single most persuasive artifact in a standards-remediation
engagement. (The suppression baseline only *hides* old findings; it never reports
what got fixed.) Landing it here gives both linters and coop-agent's ``coop
review`` the capability from one implementation.

Matching is keyed purely on each finding's ``fingerprint`` (both linters emit it
in the envelope's ``findings`` list, and it excludes line and path), so a finding
that merely moved is ``persisting`` — never counted as both fixed and new.
"""

from __future__ import annotations

from dataclasses import dataclass

from coop_review_core.errors import CoopReviewError
from coop_review_core.report import BADGE, BADGE_COLOR, sty
from coop_review_core.severity import SEVERITIES, severity_rank

__all__ = ["DeltaError", "EnvelopeDelta", "diff_envelopes", "delta_text", "delta_markdown"]


class DeltaError(CoopReviewError):
    """A comparison that cannot be made — e.g. two different tools' envelopes.

    A ``CoopReviewError`` like the rest of the family, mirroring the cross-tool
    guard in :func:`suppressions.load_baseline`, so a consumer's ``--diff-against``
    handler surfaces it as one friendly line rather than a traceback.
    """


@dataclass(frozen=True)
class EnvelopeDelta:
    """The difference between an ``old`` and a ``new`` envelope from the same tool.

    ``new_findings`` are the NEW envelope's finding dicts whose fingerprint was
    absent from OLD; ``fixed_findings`` are the OLD envelope's finding dicts whose
    fingerprint is absent from NEW (kept whole so a renderer has the rule /
    location / message to show what was resolved). ``persisting`` counts the
    fingerprints present in both. ``summary_delta`` is per-severity, NEW minus OLD.
    ``old_standards_sha256`` / ``new_standards_sha256`` are the two ``standards``
    digests: when they differ the run spans a standards change, so findings may
    differ because the *rules* changed, not the code — surfaced via
    :attr:`standards_changed` rather than silently skewing the comparison.
    """

    tool: str
    new_findings: list[dict]
    fixed_findings: list[dict]
    persisting: int
    summary_delta: dict[str, int]
    old_standards_sha256: str
    new_standards_sha256: str

    @property
    def new_count(self) -> int:
        return len(self.new_findings)

    @property
    def fixed_count(self) -> int:
        return len(self.fixed_findings)

    @property
    def standards_changed(self) -> bool:
        """True when the two runs used different standards documents."""
        return self.old_standards_sha256 != self.new_standards_sha256


def diff_envelopes(old: dict, new: dict) -> EnvelopeDelta:
    """Compare two envelopes from the same tool, keyed on each finding's fingerprint.

    Raises :class:`DeltaError` if the ``tool`` fields disagree — comparing one
    tool's findings against another's is meaningless (and their fingerprint spaces
    are disjoint), so it fails loud rather than reporting everything as new+fixed.
    """
    old_tool = str(old.get("tool") or "")
    new_tool = str(new.get("tool") or "")
    if old_tool != new_tool:
        raise DeltaError(
            "cannot compare envelopes from different tools: "
            f"{old_tool or '(unknown)'} vs {new_tool or '(unknown)'}"
        )

    old_by_fp = _by_fingerprint(old.get("findings") or [])
    new_by_fp = _by_fingerprint(new.get("findings") or [])
    old_fps, new_fps = set(old_by_fp), set(new_by_fp)

    new_findings = sorted((new_by_fp[fp] for fp in new_fps - old_fps), key=_sort_key)
    fixed_findings = sorted((old_by_fp[fp] for fp in old_fps - new_fps), key=_sort_key)

    old_summary = old.get("summary") or {}
    new_summary = new.get("summary") or {}
    summary_delta = {s: int(new_summary.get(s, 0)) - int(old_summary.get(s, 0)) for s in SEVERITIES}

    return EnvelopeDelta(
        tool=new_tool,
        new_findings=new_findings,
        fixed_findings=fixed_findings,
        persisting=len(old_fps & new_fps),
        summary_delta=summary_delta,
        old_standards_sha256=str((old.get("standards") or {}).get("sha256") or ""),
        new_standards_sha256=str((new.get("standards") or {}).get("sha256") or ""),
    )


# --- helpers ------------------------------------------------------------------


def _by_fingerprint(findings: list[dict]) -> dict[str, dict]:
    """Map each finding to its ``fingerprint``. Findings without one are skipped
    (nothing to match on); the envelope contract guarantees the field, so this only
    guards a malformed input rather than silently dropping real findings."""
    return {f["fingerprint"]: f for f in findings if isinstance(f, dict) and f.get("fingerprint")}


def _location(f: dict) -> str:
    """A best-effort, tool-agnostic display location: the model/file container and
    the object within it (dax leads with ``model``, sql with ``file``)."""
    head = str(f.get("model") or f.get("file") or "")
    obj = str(f.get("object") or "")
    if head and obj:
        return f"{head} :: {obj}"
    return head or obj


def _sort_key(f: dict) -> tuple:
    """Deterministic order: severity, then rule, location, message, fingerprint."""
    return (
        severity_rank(str(f.get("severity") or "")),
        str(f.get("rule_id") or ""),
        _location(f),
        str(f.get("message") or ""),
        str(f.get("fingerprint") or ""),
    )


def _short(sha: str) -> str:
    return sha[:10] if sha else "(none)"


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


# --- renderers (deterministic, sorted, LF; ASCII-only for Windows-safe consoles) ---


def _text_line(f: dict, *, color: bool) -> str:
    sev = str(f.get("severity") or "info")
    badge = sty(BADGE.get(sev, sev.upper()[:5]), BADGE_COLOR.get(sev, "blue"), color=color)
    loc = _location(f)
    tail = "  ".join(p for p in (str(f.get("rule_id") or ""), loc, str(f.get("message") or "")) if p)
    return f"  {badge}  {tail}"


def delta_text(delta: EnvelopeDelta, *, color: bool = False) -> str:
    """A console summary of the delta, using core's badge/style chrome. ASCII-only
    and deterministic (findings pre-sorted), with a trailing newline."""
    lines = [
        sty(
            f"{delta.tool} - {delta.new_count} new, {delta.fixed_count} fixed, {delta.persisting} unchanged",
            "bold",
            color=color,
        )
    ]
    if delta.standards_changed:
        lines.append(
            sty(
                f"! standards changed ({_short(delta.old_standards_sha256)} -> "
                f"{_short(delta.new_standards_sha256)}) - findings may differ because the "
                "rules changed, not the code",
                "yellow",
                color=color,
            )
        )
    if delta.new_findings:
        lines += ["", sty(f"NEW ({delta.new_count})", "bold", color=color)]
        lines += [_text_line(f, color=color) for f in delta.new_findings]
    if delta.fixed_findings:
        lines += ["", sty(f"FIXED ({delta.fixed_count})", "bold", color=color)]
        lines += [_text_line(f, color=color) for f in delta.fixed_findings]
    lines += [
        "",
        "summary delta: " + ", ".join(f"{s} {_signed(delta.summary_delta.get(s, 0))}" for s in SEVERITIES),
    ]
    return "\n".join(lines) + "\n"


def _md_line(f: dict) -> str:
    head = f"- `{f.get('rule_id') or ''}` **{f.get('severity') or 'info'}**"
    loc = _location(f)
    if loc:
        head += f" `{loc}`"
    return f"{head} - {f.get('message') or ''}"


def delta_markdown(delta: EnvelopeDelta) -> str:
    """The delta as Markdown for a PR comment: deterministic, LF, trailing newline."""
    lines = [
        f"### {delta.tool} - run-to-run delta",
        "",
        f"**{delta.new_count} new**, **{delta.fixed_count} fixed**, {delta.persisting} unchanged.",
    ]
    if delta.standards_changed:
        lines += [
            "",
            f"> **Standards changed** ({_short(delta.old_standards_sha256)} -> "
            f"{_short(delta.new_standards_sha256)}) - findings may differ because the rules "
            "changed, not the code.",
        ]
    if delta.new_findings:
        lines += ["", f"#### New ({delta.new_count})", ""]
        lines += [_md_line(f) for f in delta.new_findings]
    if delta.fixed_findings:
        lines += ["", f"#### Fixed ({delta.fixed_count})", ""]
        lines += [_md_line(f) for f in delta.fixed_findings]
    lines += ["", "| severity | delta |", "| --- | --- |"]
    lines += [f"| {s} | {_signed(delta.summary_delta.get(s, 0))} |" for s in SEVERITIES]
    return "\n".join(lines) + "\n"
