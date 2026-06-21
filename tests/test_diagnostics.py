"""The Diagnostic model + category constants."""

from coop_review_core.diagnostics import (
    BASELINE_STALE,
    CONFIG_UNKNOWN_RULE,
    PARSE_FAILED,
    Diagnostic,
)


def test_as_line_with_and_without_line_and_rule():
    assert Diagnostic("warning", "parse_failed", "f.sql", 3, "bad").as_line() == (
        "[warning] f.sql:3  parse_failed: bad"
    )
    assert Diagnostic("error", "rule_error", "f.sql", 0, "boom", rule_id="R").as_line() == (
        "[error] f.sql  rule_error/R: boom"
    )


def test_sort_key_is_deterministic_tuple():
    d = Diagnostic("warning", "parse_failed", "f.sql", 3, "bad")
    assert d.sort_key() == ("f.sql", 3, "parse_failed", "", "bad")


def test_category_constants_exist():
    assert PARSE_FAILED == "parse_failed"
    assert CONFIG_UNKNOWN_RULE == "config_unknown_rule"
    assert BASELINE_STALE == "baseline_stale"
