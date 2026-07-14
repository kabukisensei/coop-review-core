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


def test_scan_reason_delimiter_is_case_insensitive():
    # The directive regex is IGNORECASE, so the reason-tail split must be too.
    # A capitalized `Reason:` used to pass through the split, and a rule id
    # mentioned in the prose was captured and suppressed (fail-open).
    text = "-- coop-sql-review:ignore SQL-A Reason: overlaps SQL-B\n"
    assert scan_directives(text, TOOL) == {1: {"SQL-A"}}
    text = "-- coop-sql-review:ignore SQL-A REASON: overlaps SQL-B\n"
    assert scan_directives(text, TOOL) == {1: {"SQL-A"}}


def test_scan_bare_is_wildcard():
    assert scan_directives("// coop-sql-review:ignore\n", TOOL) == {1: {"*"}}


def test_scan_explicit_star_is_wildcard():
    assert scan_directives("-- coop-sql-review:ignore *\n", TOOL) == {1: {"*"}}


def test_scan_star_with_reason_is_wildcard():
    # issue #16: the documented grammar is `<tool>:ignore [RULE-IDS | *] [reason: ...]`,
    # so `* reason: ...` composes a wildcard with a human reason. It must suppress
    # every rule on the line in BOTH views (rule and syntax), like a bare `*`.
    from coop_review_core.suppressions import scan_syntax_ignores

    assert scan_directives("-- coop-sql-review:ignore * reason: x\n", TOOL) == {1: {"*"}}
    assert scan_syntax_ignores("-- coop-sql-review:ignore * reason: x\n", TOOL) == {1}
    # But a reason with NO `*` and NO id still fails closed: suppress nothing.
    assert scan_directives("-- coop-sql-review:ignore reason: x\n", TOOL) == {1: set()}


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


def test_scan_syntax_ignores_reason_delimiter_is_case_insensitive():
    from coop_review_core.suppressions import scan_syntax_ignores

    # A capitalized `Reason:` tail used to survive the case-sensitive split, so a
    # `syntax` word in the PROSE turned a rule-ids-only directive into a syntax
    # ignore (fail-open). The split is now IGNORECASE like the directive regex.
    text = "-- coop-sql-review:ignore SQL-A Reason: syntax is fine here\n"
    assert scan_syntax_ignores(text, TOOL) == set()
    text = "-- coop-sql-review:ignore SQL-A REASON: syntax is fine here\n"
    assert scan_syntax_ignores(text, TOOL) == set()


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


@pytest.mark.parametrize("sep", ["\x0c", "\x85"])
def test_scan_line_numbers_use_newline_only_not_splitlines(sep):
    # str.splitlines() splits on more than \n (form feed \x0c, NEL \x85, etc.),
    # but the family's parsers count \n only. A splitlines-only separator before
    # a directive used to shift its line number, silently misaligning the
    # suppression against a finding whose line was computed by \n counting.
    from coop_review_core.suppressions import (
        is_inline_suppressed,
        scan_directives,
        scan_syntax_ignores,
    )

    # One physical (\n) line 1 that happens to contain a form-feed/NEL char,
    # then the directive on \n-line 2.
    text = f"SELECT 1{sep}still line 1\n-- coop-sql-review:ignore SQL-A\n"
    scan = scan_directives(text, TOOL)
    assert scan == {2: {"SQL-A"}}  # \n-line 2, NOT shifted to 3 by the separator
    assert is_inline_suppressed("SQL-A", 2, scan)  # a finding on \n-line 2 is covered

    syntax_text = f"SELECT 1{sep}x\n-- coop-sql-review:ignore syntax\n"
    assert scan_syntax_ignores(syntax_text, TOOL) == {2}


def test_scan_line_numbers_use_newline_only_for_crlf_and_lone_cr():
    # Both CRLF and a lone CR normalize to \n before counting, matching the
    # consumers (coop-dax-review normalizes lone \r to \n before \n-splitting).
    from coop_review_core.suppressions import scan_directives

    assert scan_directives("a\r\nb\r\n-- coop-sql-review:ignore SQL-A\r\n", TOOL) == {3: {"SQL-A"}}
    assert scan_directives("a\rb\r-- coop-sql-review:ignore SQL-A\r", TOOL) == {3: {"SQL-A"}}


# --- single-pass scan_all_directives (issue #14) ------------------------------


def _reference_scan_directives(text, tool):
    """An independent two-loop implementation of scan_directives, kept as the
    grammar's reference for the equivalence property test below. The wildcard
    condition tracks the documented grammar (issue #16): a bare head OR a head of
    the literal ``*`` (so ``* reason: ...`` is a wildcard)."""
    import re

    from coop_review_core.suppressions import _directive_re, _REASON_SPLIT_RE  # noqa: PLC2701

    rule_id_re = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+")
    pattern = _directive_re(tool)
    out = {}
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for lineno, line in enumerate(normalized.split("\n"), start=1):
        match = pattern.search(line)
        if not match:
            continue
        raw = match.group(1)
        head = _REASON_SPLIT_RE.split(raw, maxsplit=1)[0]
        ids = set(rule_id_re.findall(head))
        if ids:
            out[lineno] = ids
        elif raw.strip() == "" or head.strip() == "*":
            out[lineno] = {"*"}
        else:
            out[lineno] = set()
    return out


def _reference_scan_syntax_ignores(text, tool):
    """The pre-#14 implementation of scan_syntax_ignores, kept verbatim."""
    from coop_review_core.suppressions import _directive_re, _REASON_SPLIT_RE  # noqa: PLC2701

    pattern = _directive_re(tool)
    out = set()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for lineno, line in enumerate(normalized.split("\n"), start=1):
        match = pattern.search(line)
        if not match:
            continue
        tail = _REASON_SPLIT_RE.split(match.group(1), maxsplit=1)[0]
        tokens = tail.split()
        if not tokens or tail.strip() == "*" or any(token.lower() == "syntax" for token in tokens):
            out.add(lineno)
    return out


# Every directive-line shape the grammar knows about: ids, lists, `*`, bare,
# `syntax`, mixed-case Reason: tails, every comment delimiter, non-parsing
# tokens, prose mentioning rule-like ids, and non-directive lines.
_DIRECTIVE_CORPUS = [
    "SELECT 1",
    "-- coop-sql-review:ignore",
    "-- coop-sql-review:ignore *",
    "-- coop-sql-review:ignore SQL-A",
    "-- coop-sql-review:ignore SQL-A, SQL-B2",
    "-- coop-sql-review:ignore SQL-A reason: legacy SQL-B",
    "-- coop-sql-review:ignore SQL-A Reason: overlaps SQL-B",
    "-- coop-sql-review:ignore SQL-A REASON: syntax is fine here",
    "-- coop-sql-review:ignore * reason: everything accepted",
    "-- coop-sql-review:ignore reason: no ids at all",
    "-- coop-sql-review:ignore syntax",
    "-- coop-sql-review:ignore SYNTAX reason: vendor DDL",
    "-- coop-sql-review:ignore syntax SQL-A",
    "-- coop-sql-review:ignore sql001",
    "-- coop-sql-review:ignore sql-no-select-star",
    "// coop-sql-review:ignore SQL-A -- trailing comment SQL-B",
    "# coop-sql-review:ignore SQL-A # note SQL-B",
    "-- COOP-SQL-REVIEW:IGNORE SQL-A",
    "-- coop-sql-review : ignore SQL-A",
    "-- xcoop-sql-review:ignore SQL-A",
    "-- coop-dax-review:ignore DAX-A",
    "   -- coop-sql-review:ignore\t SQL-A\t reason:\t tabs",
]


def test_scan_all_directives_wrappers_match_the_reference_line_for_line():
    from coop_review_core.suppressions import scan_all_directives, scan_directives, scan_syntax_ignores

    text = "\n".join(_DIRECTIVE_CORPUS) + "\n"
    for tool in ("coop-sql-review", "coop-dax-review"):
        expected_rules = _reference_scan_directives(text, tool)
        expected_syntax = _reference_scan_syntax_ignores(text, tool)
        assert scan_directives(text, tool) == expected_rules
        assert scan_syntax_ignores(text, tool) == expected_syntax
        scan = scan_all_directives(text, tool)
        assert scan.rule_ignores == expected_rules
        assert scan.syntax_ignore_lines == expected_syntax


def test_scan_all_directives_is_a_frozen_snapshot():
    import dataclasses

    from coop_review_core.suppressions import scan_all_directives

    scan = scan_all_directives("-- coop-sql-review:ignore SQL-A\n", "coop-sql-review")
    assert dataclasses.is_dataclass(scan)
    with pytest.raises(dataclasses.FrozenInstanceError):
        scan.rule_ignores = {}
