"""Inline ignore directives (tool-parameterized) + the fingerprint baseline."""

import json

import pytest

from coop_review_core.suppressions import (
    BaselineError,
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


def test_scan_reason_only_no_id_suppresses_nothing():
    # A directive carrying only a reason/comment but NO rule id must fail closed:
    # suppress nothing, never fall into the bare-wildcard branch.
    assert scan_directives("-- coop-sql-review:ignore reason: legacy\n", TOOL) == {1: set()}
    assert scan_directives("-- coop-sql-review:ignore -- just because\n", TOOL) == {1: set()}
    assert scan_directives("-- coop-sql-review:ignore # note\n", TOOL) == {1: set()}


def test_scan_tool_name_suffix_does_not_match():
    # A directive for a differently-named tool whose token merely ENDS with this
    # tool's name must not suppress this tool's findings (no fail-open).
    assert scan_directives("-- xcoop-sql-review:ignore SQL-FOO\n", TOOL) == {}


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


def test_load_missing_or_malformed_raises_baseline_error(tmp_path):
    # issue #3: an unusable baseline is a loud error, not a silent empty set
    # (which would flood every baselined finding back with no explanation).
    with pytest.raises(BaselineError, match="not found"):
        load_baseline(tmp_path / "nope.json")

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BaselineError, match="not valid JSON"):
        load_baseline(bad)

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text("42", encoding="utf-8")  # valid JSON, wrong type
    with pytest.raises(BaselineError, match="unexpected shape"):
        load_baseline(wrong_shape)


def test_load_baseline_bare_list_and_toolless_dict_still_load(tmp_path):
    # the lenient shape handling is unchanged: a bare list or a dict without a
    # `tool` field loads fine (only genuinely-broken input raises).
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(["aaa", "bbb"]), encoding="utf-8")
    assert load_baseline(bare, tool=TOOL) == {"aaa", "bbb"}
    toolless = tmp_path / "toolless.json"
    toolless.write_text(json.dumps({"fingerprints": ["ccc"]}), encoding="utf-8")
    assert load_baseline(toolless, tool=TOOL) == {"ccc"}


def test_load_baseline_rejects_a_different_tools_baseline(tmp_path):
    # issue #3: a coop-sql-review baseline handed to coop-dax-review is a
    # misconfiguration, not an empty baseline — surfaced only when `tool` is given.
    path = tmp_path / "bl.json"
    write_baseline(path, ["aaa"], "coop-sql-review")
    assert load_baseline(path) == {"aaa"}  # no tool arg -> no check (back-compat)
    assert load_baseline(path, tool="coop-sql-review") == {"aaa"}  # match -> fine
    with pytest.raises(BaselineError, match="written by"):
        load_baseline(path, tool="coop-dax-review")


@pytest.mark.parametrize("tool", ["coop-sql-review", "coop-dax-review"])
def test_scan_syntax_ignores_fires_and_non_fires(tool):
    from coop_review_core.suppressions import scan_directives, scan_syntax_ignores

    text = "\n".join(
        [
            f"a  -- {tool}:ignore syntax",  # 1: explicit token
            f"b  -- {tool}:ignore",  # 2: bare -> wildcard
            f"c  -- {tool}:ignore *",  # 3: literal *
            f"d  -- {tool}:ignore SQL-NO-SELECT-STAR",  # 4: rule id only -> NOT a syntax ignore
            f"e  -- {tool}:ignore syntax reason: known bad vendor DDL",  # 5: token + reason tail
            "f  -- nothing here",  # 6: no directive
        ]
    )
    assert scan_syntax_ignores(text, tool) == {1, 2, 3, 5}
    # a rule-ids-only directive still silences that RULE, but NOT a syntax diagnostic —
    # the two channels stay separate (fail-closed: `syntax` never parses as a rule id).
    assert scan_directives(text, tool).get(4) == {"SQL-NO-SELECT-STAR"}


def test_is_syntax_ignored_line_and_line_above():
    from coop_review_core.suppressions import is_syntax_ignored

    lines = {5}
    assert is_syntax_ignored(5, lines) is True  # same line
    assert is_syntax_ignored(6, lines) is True  # line directly below the directive
    assert is_syntax_ignored(4, lines) is False
    assert is_syntax_ignored(0, lines) is False  # whole-file diagnostic never inline-targeted


def test_syntax_token_never_parses_as_a_rule_id_in_scan_directives():
    from coop_review_core.suppressions import scan_directives

    # deliberate separation: `syntax` is lowercase/un-hyphenated so it can't match the
    # rule-id shape — a bare-looking directive of only `syntax` suppresses no RULE.
    d = scan_directives("x  -- coop-sql-review:ignore syntax", "coop-sql-review")
    assert d.get(1) == set()  # tokens present but none is a rule id -> suppress nothing
