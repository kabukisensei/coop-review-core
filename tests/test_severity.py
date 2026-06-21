"""Severity ordering + the line-independent fingerprint."""

from coop_review_core.severity import SEVERITIES, at_or_above, fingerprint, severity_rank


def test_severities_order():
    assert SEVERITIES == ("error", "warning", "info")
    assert severity_rank("error") < severity_rank("warning") < severity_rank("info")
    assert severity_rank("nonsense") == 3  # unknown sorts last


def test_at_or_above():
    assert at_or_above("error", "warning")
    assert at_or_above("warning", "warning")
    assert not at_or_above("info", "warning")


def test_fingerprint_stable_and_distinct():
    assert fingerprint("a", "b") == fingerprint("a", "b")  # deterministic
    assert fingerprint("a", "b") != fingerprint("a", "c")  # content-sensitive
    assert fingerprint("a", "b") != fingerprint("ab", "")  # separator avoids collisions
    assert len(fingerprint("x")) == 12
