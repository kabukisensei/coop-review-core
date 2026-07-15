"""Tests for the suite summary module."""

import json

import pytest

from coop_review_core.suite import (
    SuiteError,
    load_envelopes,
    suite_html,
    suite_summary,
    suite_text,
)


@pytest.fixture
def envelopes_dir(tmp_path):
    d = tmp_path / ".coop" / "reviews"
    d.mkdir(parents=True)

    # SQL envelope
    sql = {
        "tool": "coop-sql-review",
        "files_checked": 42,
        "summary": {"error": 2, "warning": 1, "info": 0},
        "verdict": {"clean": False, "highest_severity": "error"},
        "standards": {"path": "a.yml", "sha256": "123"},
    }
    (d / "coop-sql-review.json").write_text(json.dumps(sql), encoding="utf-8")

    # DAX envelope
    dax = {
        "tool": "coop-dax-review",
        "measures_checked": 10,
        "summary": {"error": 0, "warning": 3, "info": 1},
        "verdict": {"clean": False, "highest_severity": "warning"},
        "standards": {"path": "b.yml", "sha256": "456"},
    }
    (d / "coop-dax-review.json").write_text(json.dumps(dax), encoding="utf-8")

    return d


def test_load_envelopes_reads_and_sorts_valid_files(envelopes_dir):
    paths = [envelopes_dir / "coop-sql-review.json", envelopes_dir / "coop-dax-review.json"]
    envs = load_envelopes(paths)
    assert len(envs) == 2
    # sorted by tool name
    assert envs[0]["tool"] == "coop-dax-review"
    assert envs[1]["tool"] == "coop-sql-review"


def test_load_envelopes_raises_suite_error_on_bad_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(SuiteError, match="invalid JSON"):
        load_envelopes([f])


def test_load_envelopes_raises_suite_error_on_missing_keys(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"verdict": {}}', encoding="utf-8")
    with pytest.raises(SuiteError, match="not a valid coop-review envelope"):
        load_envelopes([f])


def test_load_envelopes_raises_suite_error_on_utf16(tmp_path):
    f = tmp_path / "bad.json"
    f.write_bytes('{"tool": "a", "verdict": {}}'.encode("utf-16"))
    with pytest.raises(SuiteError, match="not UTF-8"):
        load_envelopes([f])


def test_suite_summary_aggregates_metrics(envelopes_dir):
    envs = load_envelopes([envelopes_dir / "coop-sql-review.json", envelopes_dir / "coop-dax-review.json"])
    summary = suite_summary(envs)

    assert summary["verdict"]["clean"] is False
    assert summary["verdict"]["highest_severity"] == "error"
    assert summary["summary"]["error"] == 2
    assert summary["summary"]["warning"] == 4
    assert summary["summary"]["info"] == 1

    assert summary["tools"]["coop-sql-review"]["checked"] == 42
    assert summary["tools"]["coop-sql-review"]["checked_key"] == "files_checked"
    assert summary["tools"]["coop-dax-review"]["checked"] == 10
    assert summary["tools"]["coop-dax-review"]["checked_key"] == "measures_checked"


def test_suite_summary_clean(tmp_path):
    f = tmp_path / "clean.json"
    f.write_text(
        json.dumps(
            {
                "tool": "clean-tool",
                "files_checked": 1,
                "summary": {"error": 0, "warning": 0, "info": 0},
                "verdict": {"clean": True, "highest_severity": None},
            }
        ),
        encoding="utf-8",
    )

    envs = load_envelopes([f])
    summary = suite_summary(envs)

    assert summary["verdict"]["clean"] is True
    assert summary["verdict"]["highest_severity"] is None


def test_suite_text_render(envelopes_dir):
    envs = load_envelopes([envelopes_dir / "coop-sql-review.json", envelopes_dir / "coop-dax-review.json"])
    summary = suite_summary(envs)

    text = suite_text(envs, summary, color=False)
    assert "== Suite Review: ISSUES FOUND (ERROR) ==" in text
    assert "ERROR    2" in text
    assert "WARN" in text
    assert "INFO " in text
    assert "coop-sql-review: 42 files(s)" in text
    assert "coop-dax-review: 10 measures(s)" in text


def test_suite_html_render(envelopes_dir):
    envs = load_envelopes([envelopes_dir / "coop-sql-review.json", envelopes_dir / "coop-dax-review.json"])
    summary = suite_summary(envs)

    html = suite_html(envs, summary, {"coop-sql-review": "sql.html"})
    assert "<title>Suite Review Summary</title>" in html
    assert "2 Error(s)" in html
    assert "4 Warning(s)" in html
    assert "1 Info(s)" in html
    assert "coop-sql-review" in html
    assert "coop-dax-review" in html
    assert 'href="sql.html"' in html
