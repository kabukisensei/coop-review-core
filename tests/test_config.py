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
