"""Inline ``<tool>:ignore`` directives + a fingerprint baseline.

Tool-agnostic: pass the linter's tool name (e.g. ``"coop-sql-review"``) so the
directive regex matches that tool's marker. Findings and baselines are
identified by the fingerprint string the caller computes (see
:func:`coop_review_core.severity.fingerprint`). Both mechanisms let an advisory
linter be adopted on an existing code base without drowning in known findings —
and both stay deterministic and never block:

- **inline**: a comment ``<tool>:ignore RULE-ID [reason: ...]`` on a finding's
  line (or the line directly above) silences that rule there. List several ids
  (``ignore A, B``) or none / ``*`` to silence all rules on that line.
- **baseline**: a JSON file of fingerprints; findings already in it are hidden so
  only *new* findings surface (a ratchet).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from coop_review_core.errors import CoopReviewError

__all__ = [
    "scan_directives",
    "is_inline_suppressed",
    "scan_syntax_ignores",
    "is_syntax_ignored",
    "baseline_payload",
    "write_baseline",
    "BaselineError",
    "load_baseline",
]

_RULE_ID_RE = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+")

# The reason/comment delimiter that ends a directive's rule-id list. IGNORECASE
# to match the directive regex below — a case-sensitive split let a capitalized
# `Reason:` tail fail OPEN (a rule id mentioned in the prose was captured and
# suppressed too), the exact fail-open scan_directives' docstring rules out.
_REASON_SPLIT_RE = re.compile(r"\breason\b|--|//|#", re.IGNORECASE)


@lru_cache(maxsize=None)
def _directive_re(tool: str) -> re.Pattern:
    # `<tool>:ignore` followed by optional rule ids, up to a reason/comment delimiter.
    # `(?<![\w-])` keeps the tool token from matching as the suffix of a longer
    # identifier (e.g. `xcoop-sql-review` must not match `coop-sql-review`).
    return re.compile(rf"(?<![\w-]){re.escape(tool)}\s*:\s*ignore\b([^\n]*)", re.IGNORECASE)


def scan_directives(text: str, tool: str) -> dict[int, set[str]]:
    """Map each 1-based line carrying a ``<tool>:ignore`` directive to the rule
    ids it silences.

    Fail-closed: the blanket ``{"*"}`` wildcard (silence every rule on the
    target line) fires ONLY for a truly bare directive — an empty/whitespace
    tail or the literal ``*``. If the user wrote tokens but NONE parsed as a
    rule-id shape (a typo'd / lowercase / un-hyphenated id like ``SQL001`` or
    ``sql-no-select-star``), the line gets an empty id set so that NOTHING is
    suppressed, rather than silently silencing everything.
    """
    pattern = _directive_re(tool)
    out: dict[int, set[str]] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = pattern.search(line)
        if not match:
            continue
        # Stop at a reason/comment delimiter so a reason mentioning a RULE-LIKE
        # token isn't captured as a rule id.
        raw = match.group(1)
        head = _REASON_SPLIT_RE.split(raw, maxsplit=1)[0]
        ids = set(_RULE_ID_RE.findall(head))
        if ids:
            out[lineno] = ids
        elif raw.strip() in ("", "*"):
            out[lineno] = {"*"}  # truly bare directive (or literal *): suppress all
        else:
            out[lineno] = set()  # tokens written but none parsed -> suppress nothing
    return out


def is_inline_suppressed(rule_id: str, line: int, directives: dict[int, set[str]]) -> bool:
    """True if a directive on this line (or the line directly above) covers the rule."""
    if not line:  # file-/model-level findings (line 0) can't be inline-targeted
        return False
    for d_line in (line, line - 1):
        ids = directives.get(d_line)
        if ids and ("*" in ids or rule_id in ids):
            return True
    return False


def scan_syntax_ignores(text: str, tool: str) -> set[int]:
    """1-based lines whose ``<tool>:ignore`` directive silences a *syntax* diagnostic.

    A syntax diagnostic (a real syntax error a tool detects) isn't a rule, so
    :func:`scan_directives`' rule-id matcher deliberately can't represent it. This
    fires for an explicit lowercase ``syntax`` token (``<tool>:ignore syntax``) or
    a bare / ``*`` wildcard directive (which already silences everything on the
    line); a directive naming only rule ids does NOT silence a syntax diagnostic.
    It shares the one cached :func:`_directive_re` and strips the ``reason:`` /
    comment tail identically to :func:`scan_directives`, so the whole family has a
    single directive grammar.
    """
    pattern = _directive_re(tool)
    out: set[int] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = pattern.search(line)
        if not match:
            continue
        tail = _REASON_SPLIT_RE.split(match.group(1), maxsplit=1)[0]
        tokens = tail.split()
        if not tokens or tail.strip() == "*" or any(token.lower() == "syntax" for token in tokens):
            out.add(lineno)
    return out


def is_syntax_ignored(line: int, directive_lines: set[int]) -> bool:
    """True if a syntax-ignore directive sits on this line or the line directly
    above (line 0 — a whole-file diagnostic — is never inline-targeted)."""
    if not line:
        return False
    return line in directive_lines or (line - 1) in directive_lines


def baseline_payload(fingerprints, tool: str) -> dict:
    """Deterministic baseline content: sorted, de-duplicated fingerprints + a header."""
    return {"tool": tool, "fingerprints": sorted(set(fingerprints))}


def write_baseline(path: Path, fingerprints, tool: str) -> int:
    """Write a baseline file; returns how many fingerprints it recorded."""
    payload = baseline_payload(fingerprints, tool)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return len(payload["fingerprints"])


class BaselineError(CoopReviewError):
    """A ``--baseline`` file that cannot be used as given — missing, unreadable,
    not valid JSON, the wrong shape, or written by a different tool. Raised so an
    unusable baseline is a loud, user-facing error rather than a silent empty set
    that floods every previously-baselined finding back with no explanation
    (issue #3). A consumer should catch it and surface a friendly message
    (recommended: a ``click.UsageError`` / exit 2, like a malformed ``rules.yml``)."""


def load_baseline(path: Path, tool: str | None = None) -> set[str]:
    """The fingerprints recorded in a baseline file.

    Raises :class:`BaselineError` — never a silently-empty set — when the file is
    **missing, unreadable, not valid JSON, or the wrong shape**: an unusable
    baseline means every baselined finding resurfaces, and returning ``set()``
    gave the user no reason why. When ``tool`` is given and the baseline records a
    *different* ``tool``, that is a BaselineError too (a coop-sql-review baseline
    handed to coop-dax-review is a misconfiguration, not an empty baseline); a
    baseline with no recorded tool is accepted. Valid ``{"tool","fingerprints"}``
    dicts and bare fingerprint lists load unchanged.
    """
    path = Path(path)
    if not path.is_file():
        raise BaselineError(f"baseline file not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaselineError(f"baseline file could not be read: {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise BaselineError(f"baseline file is not valid JSON: {path} ({exc})") from exc
    if isinstance(data, dict):
        recorded = data.get("tool")
        if tool is not None and recorded is not None and str(recorded) != tool:
            raise BaselineError(
                f"baseline file {path} was written by {str(recorded)!r}, not {tool!r} — "
                "use a baseline created by this tool (re-run --write-baseline)"
            )
        return {str(fp) for fp in data.get("fingerprints", [])}
    if isinstance(data, list):
        return {str(fp) for fp in data}
    raise BaselineError(
        f"baseline file has an unexpected shape ({type(data).__name__}); expected a JSON "
        f"object or a list of fingerprints: {path}"
    )
