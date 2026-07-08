"""The rules.yml config layer + standards resolution (structural over any Rule)."""

import hashlib
from dataclasses import dataclass, field

import pytest

from coop_review_core.config import (
    RuleConfig,
    StandardsError,
    apply_config,
    default_config_path,
    resolve_standards_path,
    standards_info,
)


@dataclass
class FakeRule:
    """A stand-in for each linter's own Rule dataclass (structural typing)."""

    id: str
    severity: str = "info"
    default_enabled: bool = True
    params: dict = field(default_factory=dict)


def test_load_parses_all_sections(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "rules:\n"
        "  A:\n    enabled: false\n"
        "  B:\n    severity: error\n"
        "  C:\n    params: { min: 5 }\n"
        "  D:\n    enabled: true\n",
        encoding="utf-8",
    )
    config = RuleConfig.load(cfg)
    assert config.disabled == {"A"}
    assert config.enabled == {"D"}
    assert config.severity_overrides == {"B": "error"}
    assert config.params == {"C": {"min": 5}}
    assert config.configured == {"A", "B", "C", "D"}


def test_apply_config_is_structural_over_any_rule():
    rules = [FakeRule("A"), FakeRule("B"), FakeRule("OFF", default_enabled=False)]
    config = RuleConfig(disabled={"A"}, severity_overrides={"B": "error"}, params={"B": {"x": 1}})
    out = {r.id: r for r in apply_config(rules, config)}
    assert "A" not in out  # disabled -> dropped
    assert out["B"].severity == "error"  # overridden (non-mutating copy)
    assert out["B"].params == {"x": 1}
    assert "OFF" not in out  # off by default, not enabled


def test_off_by_default_can_be_forced_on():
    out = apply_config([FakeRule("OFF", default_enabled=False)], RuleConfig(enabled={"OFF"}))
    assert [r.id for r in out] == ["OFF"]


def test_invalid_severity_raises(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  A:\n    severity: critical\n", encoding="utf-8")
    with pytest.raises(StandardsError):
        RuleConfig.load(cfg)


def test_unknown_rule_ids():
    assert RuleConfig(configured={"REAL", "TYPO"}).unknown_rule_ids({"REAL"}) == ["TYPO"]


def test_load_parses_ignore_section(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "rules:\n  A:\n    enabled: false\n"
        "ignore:\n"
        "  - fingerprint: abc123\n    rule: X\n    where: a.sql:3\n    note: legacy\n"
        "  - deadbeef\n",  # a bare string is treated as a fingerprint
        encoding="utf-8",
    )
    config = RuleConfig.load(cfg)
    assert config.disabled == {"A"}  # rules: still parsed alongside ignore:
    assert config.ignored_fingerprints == {"abc123", "deadbeef"}


def test_ignore_entry_without_fingerprint_is_skipped(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - note: no fingerprint here\n  - fingerprint: keep1\n", encoding="utf-8")
    # A malformed entry silences nothing (never everything) rather than crashing.
    assert RuleConfig.load(cfg).ignored_fingerprints == {"keep1"}


def test_empty_ignore_when_absent(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  A:\n    enabled: false\n", encoding="utf-8")
    assert RuleConfig.load(cfg).ignored_fingerprints == set()


def test_empty_config_when_absent(tmp_path):
    assert RuleConfig.load(None) == RuleConfig()
    assert RuleConfig.load(tmp_path / "nope.yml") == RuleConfig()


def test_resolve_standards_path(tmp_path):
    bundled = tmp_path / "bundled.md"
    bundled.write_text("x", encoding="utf-8")
    assert resolve_standards_path(None, bundled) == bundled
    explicit = tmp_path / "explicit.md"
    explicit.write_text("y", encoding="utf-8")
    assert resolve_standards_path(str(explicit), bundled) == explicit
    with pytest.raises(StandardsError):
        resolve_standards_path("/nope/missing.md", bundled)


def test_standards_info_and_default_config_path(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("hello", encoding="utf-8")
    info = standards_info(p)
    assert info["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert info["path"].endswith("s.md")
    assert default_config_path(p) == tmp_path / "rules.yml"


# -- issue #4: core owns the friendly rules.yml loader ------------------------


def test_rule_config_loads_from_text():
    from coop_review_core.config import RuleConfig

    cfg = RuleConfig.loads("rules:\n  A-B:\n    enabled: false\n  C-D:\n    enabled: true\n")
    assert cfg.disabled == {"A-B"} and cfg.enabled == {"C-D"}
    assert RuleConfig.loads("") == RuleConfig()  # empty text -> empty config
    assert RuleConfig.loads("   \n") == RuleConfig()


def test_load_config_friendly_returns_config_and_raw_mapping(tmp_path):
    from coop_review_core.config import load_config_friendly

    p = tmp_path / "rules.yml"
    p.write_text("rules:\n  A-B:\n    severity: warning\nsyntax_errors: off\n", encoding="utf-8")
    cfg, raw = load_config_friendly(p)
    assert cfg.severity_overrides == {"A-B": "warning"}
    # the raw top-level mapping is returned so a tool checks its own knob WITHOUT re-reading
    assert raw.get("syntax_errors") is False  # YAML 1.1 coerces bare `off` -> False


def test_load_config_friendly_absent_is_empty(tmp_path):
    from coop_review_core.config import RuleConfig, load_config_friendly

    cfg, raw = load_config_friendly(tmp_path / "nope.yml")
    assert cfg == RuleConfig() and raw == {}


def test_load_config_friendly_reports_each_problem(tmp_path):
    from coop_review_core.config import load_config_friendly

    def _bad(text, match, *, raw=False):
        p = tmp_path / "rules.yml"
        (p.write_bytes(text) if raw else p.write_text(text, encoding="utf-8"))
        with pytest.raises(StandardsError, match=match):
            load_config_friendly(p)

    _bad("[]", "top level must be a mapping")
    _bad("rules: []", r"`rules:` must be a mapping")
    _bad("a: b: c\n- x", "invalid YAML")
    _bad("rules:\n  A-B:\n    severity: loud\n", "invalid severity")
    _bad(b"\xff\xfer\x00u\x00", "not UTF-8", raw=True)  # UTF-16-ish / NUL-riddled


def test_parse_syntax_errors_knob():
    from coop_review_core.config import parse_syntax_errors_knob

    assert parse_syntax_errors_knob("error") == "error"
    assert parse_syntax_errors_knob("Warning") == "warning"  # case-insensitive
    assert parse_syntax_errors_knob(False) == "off"  # YAML 1.1 bare `off`
    assert parse_syntax_errors_knob("off") == "off"
    with pytest.raises(StandardsError, match="must be one of"):
        parse_syntax_errors_knob(True)  # truthy `on` has no mode
    with pytest.raises(StandardsError, match="must be one of"):
        parse_syntax_errors_knob("nope")
