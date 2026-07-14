"""The run-to-run envelope delta engine (``delta.py``, issue #29): fingerprint-keyed
new / fixed / persisting classification and its console + Markdown renderers."""

import pytest

from coop_review_core.delta import (
    DeltaError,
    EnvelopeDelta,
    delta_markdown,
    delta_text,
    diff_envelopes,
)
from coop_review_core.report import build_envelope, verdict


def _finding(fp, *, rule="R-1", sev="warning", file="a.sql", obj="dbo.T", msg="msg", **extra):
    return {
        "rule_id": rule,
        "severity": sev,
        "file": file,
        "object": obj,
        "message": msg,
        "fingerprint": fp,
        **extra,
    }


def _env(findings, *, tool="coop-sql-review", summary=None, sha="STD-1"):
    return {
        "tool": tool,
        "standards": {"path": "standards.md", "sha256": sha},
        "findings": findings,
        "summary": summary or {},
    }


def test_diff_classifies_new_fixed_persisting():
    old = _env([_finding("a"), _finding("b"), _finding("c")])
    new = _env([_finding("b"), _finding("c"), _finding("d")])
    d = diff_envelopes(old, new)
    assert [f["fingerprint"] for f in d.new_findings] == ["d"]
    assert [f["fingerprint"] for f in d.fixed_findings] == ["a"]
    assert d.persisting == 2
    assert d.new_count == 1 and d.fixed_count == 1


def test_diff_moved_finding_is_persisting_not_new_and_fixed():
    # Same fingerprint, everything else changed (line shift, reworded message): the
    # fingerprint is line/path-independent, so it is unchanged — never fixed+new.
    old = _env([_finding("x", file="old.sql", msg="was here")])
    new = _env([_finding("x", file="new.sql", msg="moved but same identity")])
    d = diff_envelopes(old, new)
    assert d.persisting == 1
    assert d.new_findings == [] and d.fixed_findings == []


def test_diff_summary_delta_is_per_severity_new_minus_old():
    old = _env([], summary={"error": 1, "warning": 5, "info": 2})
    new = _env([], summary={"error": 3, "warning": 2})  # info omitted -> 0
    d = diff_envelopes(old, new)
    assert d.summary_delta == {"error": 2, "warning": -3, "info": -2}


def test_diff_flags_a_standards_change():
    old = _env([_finding("a")], sha="STD-OLD")
    new = _env([_finding("a")], sha="STD-NEW")
    d = diff_envelopes(old, new)
    assert d.standards_changed is True
    assert d.old_standards_sha256 == "STD-OLD" and d.new_standards_sha256 == "STD-NEW"


def test_diff_same_standards_not_flagged():
    d = diff_envelopes(_env([_finding("a")]), _env([_finding("a")]))
    assert d.standards_changed is False


def test_diff_rejects_mismatched_tools():
    old = _env([], tool="coop-sql-review")
    new = _env([], tool="coop-dax-review")
    with pytest.raises(DeltaError, match="different tools"):
        diff_envelopes(old, new)


def test_diff_handles_empty_envelopes():
    d = diff_envelopes(_env([]), _env([]))
    assert d.new_count == 0 and d.fixed_count == 0 and d.persisting == 0
    assert d.summary_delta == {"error": 0, "warning": 0, "info": 0}


def test_diff_skips_findings_without_a_fingerprint():
    bad = {"rule_id": "R-1", "severity": "info", "message": "no fp"}
    d = diff_envelopes(_env([]), _env([bad, _finding("real")]))
    assert [f["fingerprint"] for f in d.new_findings] == ["real"]


def test_diff_is_deterministic_and_sorted_by_severity_then_rule():
    new = _env(
        [
            _finding("1", rule="R-Z", sev="info"),
            _finding("2", rule="R-A", sev="error"),
            _finding("3", rule="R-B", sev="error"),
        ]
    )
    d = diff_envelopes(_env([]), new)
    # error before info; within error, R-A before R-B.
    assert [f["rule_id"] for f in d.new_findings] == ["R-A", "R-B", "R-Z"]


def test_new_findings_carry_the_whole_finding_dict_for_display():
    new = _env([_finding("a", rule="SQL-X", msg="do the thing", standard_ref="§9")])
    d = diff_envelopes(_env([]), new)
    assert d.new_findings[0]["standard_ref"] == "§9"
    assert d.new_findings[0]["message"] == "do the thing"


def test_delta_text_summarizes_and_lists_new_and_fixed():
    old = _env([_finding("a", rule="SQL-OLD", msg="fixed one")])
    new = _env([_finding("b", rule="SQL-NEW", sev="error", msg="new one")])
    out = delta_text(diff_envelopes(old, new))
    assert "coop-sql-review - 1 new, 1 fixed, 0 unchanged" in out
    assert "NEW (1)" in out and "FIXED (1)" in out
    assert "SQL-NEW" in out and "SQL-OLD" in out
    assert "summary delta:" in out
    assert out.endswith("\n")


def test_delta_text_is_ascii_only_and_color_free_by_default():
    new = _env([_finding("a", sev="error")])
    out = delta_text(diff_envelopes(_env([]), new))
    out.encode("ascii")  # raises if any non-ASCII slipped in
    assert "\033[" not in out  # no ANSI when color defaults off


def test_delta_text_color_adds_ansi():
    new = _env([_finding("a", sev="error")])
    out = delta_text(diff_envelopes(_env([]), new), color=True)
    assert "\033[" in out


def test_delta_text_notes_a_standards_change():
    old = _env([_finding("a")], sha="OLDSHA1234")
    new = _env([_finding("a")], sha="NEWSHA5678")
    out = delta_text(diff_envelopes(old, new))
    assert "standards changed" in out


def test_delta_markdown_structure():
    old = _env([_finding("a", rule="SQL-OLD")])
    new = _env([_finding("b", rule="SQL-NEW", sev="error")])
    md = delta_markdown(diff_envelopes(old, new))
    assert md.startswith("### coop-sql-review - run-to-run delta")
    assert "**1 new**, **1 fixed**, 0 unchanged." in md
    assert "#### New (1)" in md and "#### Fixed (1)" in md
    assert "`SQL-NEW`" in md and "`SQL-OLD`" in md
    assert "| severity | delta |" in md
    assert md.endswith("\n")


def test_renderers_are_deterministic():
    old = _env([_finding("a"), _finding("b", rule="R-2")])
    new = _env([_finding("c", sev="error"), _finding("d", rule="R-3")])
    d = diff_envelopes(old, new)
    assert delta_text(d) == delta_text(d)
    assert delta_markdown(d) == delta_markdown(d)


def test_diff_works_on_real_build_envelope_output():
    # Integration: two envelopes built exactly as the linters build them, with the
    # dax-shaped finding (a `model` key) to prove the tool-agnostic location render.
    def env(findings, summary, sha):
        return build_envelope(
            tool="coop-dax-review",
            schema_version=3,
            version="0.14.0",
            standards={"path": "s.md", "sha256": sha},
            checked_key="models_checked",
            checked=1,
            verdict=verdict(summary, has_findings=bool(findings), has_error_diagnostic=False),
            findings=findings,
            summary=summary,
            agent_review=[],
            diagnostics=[],
        )

    f_old = {
        "rule_id": "DAX-A",
        "severity": "warning",
        "model": "Sales",
        "object": "[M1]",
        "message": "old",
        "fingerprint": "old1",
    }
    f_keep = {
        "rule_id": "DAX-B",
        "severity": "info",
        "model": "Sales",
        "object": "[M2]",
        "message": "keep",
        "fingerprint": "keep1",
    }
    f_new = {
        "rule_id": "DAX-C",
        "severity": "error",
        "model": "Sales",
        "object": "[M3]",
        "message": "new",
        "fingerprint": "new1",
    }
    old = env([f_old, f_keep], {"warning": 1, "info": 1}, "SHA-A")
    new = env([f_keep, f_new], {"error": 1, "info": 1}, "SHA-A")

    d = diff_envelopes(old, new)
    assert isinstance(d, EnvelopeDelta)
    assert [f["fingerprint"] for f in d.new_findings] == ["new1"]
    assert [f["fingerprint"] for f in d.fixed_findings] == ["old1"]
    assert d.persisting == 1
    assert d.summary_delta == {"error": 1, "warning": -1, "info": 0}
    # the dax location render uses model :: object
    assert "Sales :: [M3]" in delta_text(d)
    assert "Sales :: [M3]" in delta_markdown(d)
