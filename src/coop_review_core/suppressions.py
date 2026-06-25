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

_RULE_ID_RE = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+")


@lru_cache(maxsize=None)
def _directive_re(tool: str) -> re.Pattern:
    # `<tool>:ignore` followed by optional rule ids, up to a reason/comment delimiter.
    return re.compile(rf"{re.escape(tool)}\s*:\s*ignore\b([^\n]*)", re.IGNORECASE)


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
        head = re.split(r"\breason\b|--|//|#", match.group(1), maxsplit=1)[0]
        ids = set(_RULE_ID_RE.findall(head))
        if ids:
            out[lineno] = ids
        elif head.strip() in ("", "*"):
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


def baseline_payload(fingerprints, tool: str) -> dict:
    """Deterministic baseline content: sorted, de-duplicated fingerprints + a header."""
    return {"tool": tool, "fingerprints": sorted(set(fingerprints))}


def write_baseline(path: Path, fingerprints, tool: str) -> int:
    """Write a baseline file; returns how many fingerprints it recorded."""
    payload = baseline_payload(fingerprints, tool)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return len(payload["fingerprints"])


def load_baseline(path: Path) -> set[str]:
    """The fingerprints recorded in a baseline file (empty if absent/unreadable/malformed)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict):
        return {str(fp) for fp in data.get("fingerprints", [])}
    if isinstance(data, list):
        return {str(fp) for fp in data}
    return set()
