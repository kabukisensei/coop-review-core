"""The shared report layer: console/HTML chrome, the logo asset, and the
machine-JSON envelope (issue #9)."""

import base64
import json

from coop_review_core.diagnostics import Diagnostic
from coop_review_core.report import (
    ANSI,
    BADGE,
    BADGE_COLOR,
    HTML_STYLE,
    LOGO_PATH,
    build_envelope,
    chip,
    diagnostic_json,
    envelope_text,
    esc,
    log_text,
    logo_data_uri,
    sty,
    verdict,
)

# --- console chrome -------------------------------------------------------------


def test_badges_are_ascii_and_aligned():
    assert set(BADGE) == set(BADGE_COLOR) == {"error", "warning", "info"}
    for text in BADGE.values():
        assert len(text) == 5
        assert text.isascii()


def test_sty_no_color_returns_text_unchanged():
    assert sty("hello", "red", "bold", color=False) == "hello"
    assert sty("hello", color=True) == "hello"  # no codes -> unchanged


def test_sty_wraps_with_ansi_codes_and_reset():
    styled = sty("hello", "red", "bold", color=True)
    assert styled == ANSI["red"] + ANSI["bold"] + "hello" + ANSI["reset"]
    assert styled.isascii()  # ANSI escapes are ASCII -> cp1252-safe


# --- HTML chrome ------------------------------------------------------------------


def test_html_style_is_the_brand_block():
    # The palette the twins shipped byte-identically: navy brand, red-orange
    # accent, the green gradient — and no leading/trailing whitespace.
    for token in ("#004068", "#e84028", "#407838", "#80a840", "#b0d030"):
        assert token in HTML_STYLE
    assert HTML_STYLE == HTML_STYLE.strip()


def test_logo_data_uri_embeds_the_bundled_png():
    assert LOGO_PATH.is_file(), "the logo must ship with core (single bundled copy)"
    uri = logo_data_uri()
    assert uri.startswith("data:image/png;base64,")
    payload = base64.b64decode(uri.split(",", 1)[1])
    assert payload == LOGO_PATH.read_bytes()
    assert logo_data_uri() == uri  # deterministic


def test_esc_escapes_html_and_quotes_and_coerces():
    assert esc('<b a="x">') == "&lt;b a=&quot;x&quot;&gt;"
    assert esc(42) == "42"


def test_chip_known_and_unknown_severity():
    assert chip("error") == '<span class="chip error">error</span>'
    assert chip("bogus") == '<span class="chip info">bogus</span>'  # unknown styles as info


def test_html_script_and_filter_bar_are_ascii_safe():
    from coop_review_core.report import HTML_SCRIPT, filter_bar_html

    assert HTML_SCRIPT.isascii()
    assert filter_bar_html().isascii()
    assert "document.addEventListener" in HTML_SCRIPT
    assert 'id="searchFilter"' in filter_bar_html()


# --- verdict --------------------------------------------------------------------


def test_verdict_clean_run():
    v = verdict({"error": 0, "warning": 0, "info": 0}, has_findings=False, has_error_diagnostic=False)
    assert v == {"clean": True, "highest_severity": None}


def test_verdict_highest_severity_orders_error_first():
    v = verdict({"error": 1, "warning": 2, "info": 3}, has_findings=True, has_error_diagnostic=False)
    assert v == {"clean": False, "highest_severity": "error"}
    v = verdict({"error": 0, "warning": 0, "info": 3}, has_findings=True, has_error_diagnostic=False)
    assert v == {"clean": False, "highest_severity": "info"}


def test_verdict_error_diagnostic_breaks_clean_even_with_zero_findings():
    v = verdict({"error": 0, "warning": 0, "info": 0}, has_findings=False, has_error_diagnostic=True)
    assert v == {"clean": False, "highest_severity": "error"}


# --- the JSON envelope -------------------------------------------------------------

_STANDARDS = {"path": "docs/standards.md", "sha256": "abc123"}


def _sample_envelope(schema_version: int = 3, checked_key: str = "files_checked") -> dict:
    findings = [
        {
            "rule_id": "SQL-X",
            "severity": "warning",
            "file": "a.sql",
            "line": 3,
            "object": "dbo.t",
            "message": "msg",
            "standard_ref": "§1",
            "fingerprint": "deadbeef0123",
        }
    ]
    summary = {"error": 0, "warning": 1, "info": 0}
    diag = Diagnostic(severity="warning", category="parse_degraded", file="a.sql", line=0, message="m")
    return build_envelope(
        tool="coop-sql-review",
        schema_version=schema_version,
        version="9.9.9",
        standards=_STANDARDS,
        checked_key=checked_key,
        checked=1,
        verdict=verdict(summary, has_findings=True, has_error_diagnostic=False),
        findings=findings,
        summary=summary,
        agent_review=[],
        diagnostics=[diagnostic_json(diag)],
    )


def test_envelope_reproduces_the_twins_shape_exactly():
    envelope = _sample_envelope()
    # The exact key set the shipped twins emit today (sql spelling).
    assert set(envelope) == {
        "tool",
        "schema_version",
        "version",
        "standards",
        "files_checked",
        "verdict",
        "findings",
        "summary",
        "agent_review",
        "diagnostics",
    }
    assert envelope["standards"] == {"path": "docs/standards.md", "sha256": "abc123"}
    assert envelope["schema_version"] == 3  # injected per tool, never baked in
    # The dax spelling differs only by the checked-count key + its schema_version.
    dax = _sample_envelope(schema_version=2, checked_key="models_checked")
    assert "models_checked" in dax and "files_checked" not in dax
    assert dax["schema_version"] == 2


def test_envelope_standards_defaults_to_empty_strings():
    envelope = build_envelope(
        tool="t",
        schema_version=1,
        version="0",
        standards={},
        checked_key="files_checked",
        checked=0,
        verdict={"clean": True, "highest_severity": None},
        findings=[],
        summary={"error": 0, "warning": 0, "info": 0},
        agent_review=[],
        diagnostics=[],
    )
    assert envelope["standards"] == {"path": "", "sha256": ""}


def test_envelope_text_is_deterministic_sorted_ascii_with_trailing_newline():
    envelope = _sample_envelope()
    text = envelope_text(envelope)
    assert text == envelope_text(_sample_envelope())  # byte-identical across builds
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert text.isascii()
    assert text == json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    assert json.loads(text) == envelope  # round-trips


def test_diagnostic_json_carries_every_field():
    diag = Diagnostic(
        severity="error", category="syntax_error", file="x.sql", line=7, message="bad", rule_id="R-1"
    )
    assert diagnostic_json(diag) == {
        "severity": "error",
        "category": "syntax_error",
        "file": "x.sql",
        "line": 7,
        "message": "bad",
        "rule_id": "R-1",
    }


# --- the diagnostics log -----------------------------------------------------------


def test_log_text_empty_and_populated_match_the_twins_format():
    assert log_text([], tool="coop-sql-review", checked=2, unit="file") == (
        "coop-sql-review diagnostics log - 2 file(s) checked\nNo diagnostics.\n"
    )
    diag = Diagnostic(severity="warning", category="parse_degraded", file="a.sql", line=4, message="m")
    text = log_text([diag], tool="coop-dax-review", checked=1, unit="model")
    assert text == ("coop-dax-review diagnostics log - 1 model(s) checked\n" + diag.as_line() + "\n")


# --- SARIF (issue #11) ---------------------------------------------------------------


def _sample_sarif(**overrides) -> str:
    from coop_review_core.report import to_sarif

    kwargs = dict(
        tool_name="coop-sql-review",
        information_uri="https://github.com/kabukisensei/coop-sql-review",
        version="9.9.9",
        driver_rules=[
            {
                "id": "SQL-A",
                "name": "SQL-A",
                "shortDescription": {"text": "rule a"},
                "defaultConfiguration": {"level": "warning"},
            }
        ],
        findings=[
            {
                "rule_id": "SQL-A",
                "severity": "warning",
                "file": "a.sql",
                "line": 3,
                "message": "m1",
                "fingerprint": "aaaaaaaaaaaa",
            },
            {
                "rule_id": "SQL-GONE",
                "severity": "bogus",
                "file": "b.sql",
                "line": 0,
                "message": "m2",
                "fingerprint": "bbbbbbbbbbbb",
            },
        ],
        agent_review=[
            {
                "rule_id": "SQL-A",
                "note": "judge me",
                "file": "c.sql",
                "line": 9,
                "fingerprint": "cccccccccccc",
            }
        ],
        diagnostics=[
            Diagnostic(severity="error", category="syntax_error", file="d.sql", line=2, message="broken"),
            Diagnostic(severity="warning", category="parse_degraded", file="d.sql", line=0, message="meh"),
        ],
        diagnostics_rule_description="A processing problem.",
    )
    kwargs.update(overrides)
    return to_sarif(**kwargs)


def test_sarif_skeleton_and_determinism():
    text = _sample_sarif()
    assert text == _sample_sarif()  # byte-identical across calls
    assert text.endswith("\n") and text.isascii()
    log = json.loads(text)
    assert log["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    assert log["version"] == "2.1.0"
    driver = log["runs"][0]["tool"]["driver"]
    assert driver["name"] == "coop-sql-review"
    assert driver["version"] == "9.9.9"
    assert driver["informationUri"] == "https://github.com/kabukisensei/coop-sql-review"


def test_sarif_severity_to_level_mapping_and_rule_index():
    log = json.loads(_sample_sarif())
    results = log["runs"][0]["results"]
    finding_row, unknown_row, agent_row, diag_row = results
    assert finding_row["level"] == "warning"
    assert finding_row["ruleIndex"] == 0  # matched in the driver rules table
    assert finding_row["locations"][0]["physicalLocation"]["region"] == {"startLine": 3}
    assert unknown_row["level"] == "note"  # unknown severity -> note
    assert "ruleIndex" not in unknown_row  # no metadata row for an unknown rule id
    assert "region" not in unknown_row["locations"][0]["physicalLocation"]  # line 0 omits it
    assert agent_row["level"] == "note"  # judgment items never block
    assert agent_row["message"] == {"text": "judge me"}


def test_sarif_diagnostics_become_the_synthetic_rule_errors_only():
    log = json.loads(_sample_sarif())
    driver_rules = log["runs"][0]["tool"]["driver"]["rules"]
    assert driver_rules[-1]["id"] == "syntax-error"
    assert driver_rules[-1]["shortDescription"] == {"text": "A processing problem."}
    assert driver_rules[-1]["defaultConfiguration"] == {"level": "error"}
    results = log["runs"][0]["results"]
    diag_rows = [r for r in results if r["ruleId"] == "syntax-error"]
    assert len(diag_rows) == 1  # the warning-severity diagnostic is NOT emitted
    assert diag_rows[0]["ruleIndex"] == 1  # appended after the tool's own rules
    assert diag_rows[0]["level"] == "error"
    assert "partialFingerprints" not in diag_rows[0]


def test_sarif_fingerprint_key_defaults_frozen_and_is_injectable():
    from coop_review_core.report import SARIF_FINGERPRINT_KEY

    # coop-sql-review's shipped key: frozen for GitHub alert continuity. Renaming
    # the DEFAULT would orphan every existing code-scanning alert on its flip.
    assert SARIF_FINGERPRINT_KEY == "coopFingerprint/v2"
    log = json.loads(_sample_sarif())
    row = log["runs"][0]["results"][0]
    assert row["partialFingerprints"] == {"coopFingerprint/v2": "aaaaaaaaaaaa"}
    custom = json.loads(_sample_sarif(fingerprint_key="daxFingerprint/v1"))
    assert custom["runs"][0]["results"][0]["partialFingerprints"] == {"daxFingerprint/v1": "aaaaaaaaaaaa"}


# --- to_junit (JUnit XML) ------------------------------------------------------


def _sample_junit(**kw):
    from coop_review_core.report import to_junit

    findings = [
        {"rule_id": "R-B", "severity": "warning", "file": "b.sql", "line": 5, "message": "warn me"},
        {"rule_id": "R-A", "severity": "error", "file": "a.sql", "line": 3, "message": 'bad <x> & "y"'},
    ]
    diags = [
        Diagnostic(severity="error", category="syntax_error", file="c.sql", line=1, message="boom"),
        Diagnostic(severity="warning", category="parse_degraded", file="d.sql", line=2, message="meh"),
    ]
    return to_junit(
        tool_name="coop-x",
        version="1.2.3",
        findings=findings,
        diagnostics=diags,
        checked=4,
        unit="file",
        **kw,
    )


def test_to_junit_is_wellformed_ascii_and_byte_stable():
    import xml.etree.ElementTree as ET

    xml = _sample_junit()
    ET.fromstring(xml)  # raises if not well-formed
    assert xml == _sample_junit()  # deterministic
    assert xml.endswith("\n")
    xml.encode("ascii")  # ensure_ascii-safe
    assert "timestamp" not in xml  # no timestamps -> byte-identical across runs


def test_to_junit_maps_severity_and_diagnostics():
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_sample_junit())
    # 2 findings + the error diagnostic (the warning diagnostic is dropped, like to_sarif)
    assert root.get("tests") == "3"
    assert root.get("failures") == "2"  # R-A error + the syntax-error diagnostic
    assert root.get("skipped") == "1"  # R-B warning
    cases = {tc.get("classname"): tc for tc in root.iter("testcase")}
    assert cases["R-A"].find("failure") is not None
    assert cases["R-B"].find("skipped") is not None
    assert cases["syntax-error"].find("failure") is not None
    assert cases["R-A"].find("failure").text == 'bad <x> & "y"'  # XML-escaped, decodes back


def test_to_junit_sorts_deterministically_regardless_of_input_order():
    import xml.etree.ElementTree as ET

    from coop_review_core.report import to_junit

    xml = to_junit(
        tool_name="t",
        version="1",
        findings=[
            {"rule_id": "Z", "severity": "error", "file": "z.sql", "line": 1, "message": "m"},
            {"rule_id": "A", "severity": "error", "file": "a.sql", "line": 1, "message": "m"},
        ],
        checked=1,
        unit="file",
    )
    ids = [tc.get("classname") for tc in ET.fromstring(xml).iter("testcase")]
    assert ids == ["A", "Z"]

def test_to_junit():
    from coop_review_core.report import to_junit
    from coop_review_core.diagnostics import Diagnostic
    findings = [
        {"rule_id": "R1", "severity": "error", "file": "f1.sql", "line": 10, "message": "msg1"},
        {"rule_id": "R2", "severity": "warning", "file": "f2.sql", "line": 20, "message": "msg2"},
        {"rule_id": "R3", "severity": "info", "file": "f3.sql", "line": 30, "message": "msg3"}
    ]
    diagnostics = [
        Diagnostic("error", "category", "f4.sql", 40, "diag_error"),
        Diagnostic("warning", "category", "f5.sql", 50, "diag_warn")
    ]
    agent = [
        {"rule_id": "R4", "file": "f6.sql", "line": 60, "note": "agent_note"}
    ]
    xml = to_junit(tool_name="tool", version="1.0", findings=findings, agent_review=agent, diagnostics=diagnostics, checked=6, unit="files")
    
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    
    assert root.tag == "testsuites"
    assert root.attrib["failures"] == "2" # R1 error + diagnostic error
    assert root.attrib["tests"] == "5" # 3 findings + 1 diagnostic + 1 agent
    
    suite = root.find("testsuite")
    assert suite.attrib["failures"] == "2"
    
    cases = suite.findall("testcase")
    assert len(cases) == 5
    
    # check if well-formed XML and string contents
    assert 'message="warning: msg2"' in xml
    assert '<failure message="msg1" type="error">msg1</failure>' in xml
    assert 'classname="syntax-error"' in xml
