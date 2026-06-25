"""Inline ignore directives (tool-parameterized) + the fingerprint baseline."""

import json

from coop_review_core.suppressions import (
    is_inline_suppressed,
    load_baseline,
    scan_directives,
    write_baseline,
)

TOOL = "coop-sql-review"


def test_scan_parses_ids_and_stops_at_reason():
    text = "x\n-- coop-sql-review:ignore SQL-NO-SELECT-STAR reason: legacy SQL-NOPE\ny\n"
    assert scan_directives(text, TOOL) == {2: {"SQL-NO-SELECT-STAR"}}


def test_scan_bare_is_wildcard():
    assert scan_directives("// coop-sql-review:ignore\n", TOOL) == {1: {"*"}}


def test_scan_explicit_star_is_wildcard():
    assert scan_directives("-- coop-sql-review:ignore *\n", TOOL) == {1: {"*"}}


def test_scan_unparseable_id_does_not_become_wildcard():
    # A directive that NAMES a rule but whose token doesn't parse (typo'd id,
    # lowercase, no hyphen) must fail closed: suppress NOTHING, never everything.
    assert scan_directives("-- coop-sql-review:ignore SQL001\n", TOOL) == {1: set()}
    assert scan_directives("-- coop-sql-review:ignore sql-no-select-star\n", TOOL) == {1: set()}


def test_scan_multiple_ids():
    assert scan_directives("-- coop-sql-review:ignore SQL-A, SQL-B\n", TOOL) == {1: {"SQL-A", "SQL-B"}}


def test_scan_is_tool_specific():
    # a different tool's directive is not this tool's business
    assert scan_directives("-- coop-dax-review:ignore DAX-X\n", TOOL) == {}


def test_inline_same_line_and_line_above():
    directives = {5: {"SQL-X"}}
    assert is_inline_suppressed("SQL-X", 5, directives)  # trailing on the same line
    assert is_inline_suppressed("SQL-X", 6, directives)  # directive on the line above
    assert not is_inline_suppressed("SQL-X", 7, directives)  # too far
    assert not is_inline_suppressed("SQL-Y", 5, directives)  # different rule
    assert not is_inline_suppressed("SQL-X", 0, directives)  # file-level finding


def test_wildcard_suppresses_any_rule():
    assert is_inline_suppressed("ANY-RULE", 3, {3: {"*"}})


def test_baseline_roundtrip(tmp_path):
    path = tmp_path / "bl.json"
    assert write_baseline(path, ["zzz", "aaa", "aaa"], TOOL) == 2  # de-duplicated
    assert load_baseline(path) == {"aaa", "zzz"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tool"] == TOOL and payload["fingerprints"] == ["aaa", "zzz"]  # sorted


def test_load_missing_or_malformed_is_empty(tmp_path):
    assert load_baseline(tmp_path / "nope.json") == set()
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_baseline(bad) == set()
