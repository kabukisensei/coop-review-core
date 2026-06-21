"""Severity ordering and the stable finding fingerprint.

Severity is advisory; nothing a linter produces is fatal to a build unless the
caller opts into a strict gate. The fingerprint is a short, line-independent id
so a consumer can track or suppress a finding across runs even as lines shift.
"""

from __future__ import annotations

import hashlib

SEVERITIES = ("error", "warning", "info")
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def severity_rank(severity: str) -> int:
    """Order key for a severity; unknown severities sort last."""
    return _SEVERITY_RANK.get(severity, len(_SEVERITY_RANK))


def at_or_above(severity: str, threshold: str) -> bool:
    """True when ``severity`` is as serious as ``threshold`` (error >= warning >= info)."""
    return severity_rank(severity) <= severity_rank(threshold)


def fingerprint(*parts: str) -> str:
    """A short, stable hash over the identity ``parts``. Callers deliberately
    exclude volatile parts (line number, severity) so the id survives edits."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]
