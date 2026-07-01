"""Diagnostics — problems a linter hit while *processing* input, as opposed to
findings (deviations from the standards).

These exist so nothing fails silently: a file that won't parse, input a parser
can only treat opaquely (so some rules can't see inside it), a rule that raised,
or a misconfigured rules.yml — each becomes a Diagnostic the user sees in both
the console report and the JSON, so the gap can be understood and fixed.

Severity:
- error   : a rule crashed, or a file could not be read (a real bug / blocker)
- warning : analysis was degraded, or a config entry was ignored — results in
            that region may be incomplete
"""

from __future__ import annotations

from dataclasses import dataclass

DIAGNOSTIC_SEVERITIES = ("error", "warning")

# categories
RULE_ERROR = "rule_error"
PARSE_FAILED = "parse_failed"
PARSE_DEGRADED = "parse_degraded"
FILE_UNREADABLE = "file_unreadable"
CONFIG_UNKNOWN_RULE = "config_unknown_rule"  # rules.yml names a rule id that doesn't exist
BASELINE_STALE = "baseline_stale"  # a baseline entry no longer matches any current finding
IGNORE_STALE = "ignore_stale"  # a rules.yml `ignore:` entry no longer matches any current finding


@dataclass(frozen=True)
class Diagnostic:
    """One processing problem, at a file (and line, when known)."""

    severity: str
    category: str
    file: str
    line: int  # 0 when file-level / not line-specific
    message: str
    rule_id: str = ""

    def sort_key(self) -> tuple:
        return (self.file, self.line, self.category, self.rule_id, self.message)

    def as_line(self) -> str:
        """One-line rendering for the console and the log file."""
        where = f"{self.file}:{self.line}" if self.line else self.file
        tag = f"{self.category}" + (f"/{self.rule_id}" if self.rule_id else "")
        return f"[{self.severity}] {where}  {tag}: {self.message}"
