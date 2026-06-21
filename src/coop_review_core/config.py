"""The rules.yml config layer + standards-file resolution.

Tool-agnostic. ``apply_config`` works *structurally* on any rule dataclass that
has ``id`` / ``severity`` / ``default_enabled`` / ``params`` (it copies rules
with :func:`dataclasses.replace`), so each linter keeps its own ``Rule`` type.
``resolve_standards_path`` takes the linter's own bundled-standards path.

A ``rules.yml`` (sibling of the standards file, or ``--config``) can:
- disable a rule (``enabled: false``) or force-on an off-by-default one (``enabled: true``),
- override a rule's ``severity`` (validated against the known severities),
- set per-rule ``params:`` (e.g. thresholds) that the rule reads at run time.

Editing it changes behavior with no rebuild.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from coop_review_core.severity import SEVERITIES


class StandardsError(Exception):
    """A user-facing problem locating or reading the standards file."""


def resolve_standards_path(explicit: str | None, bundled: Path) -> Path:
    """The standards file to use: ``explicit`` if given, else the linter's ``bundled`` copy."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise StandardsError(f"standards file not found: {path}")
        return path
    return bundled


def standards_info(path: Path) -> dict[str, str]:
    """``{'path': ..., 'sha256': ...}`` for the JSON contract (POSIX path)."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    return {"path": path.as_posix(), "sha256": digest}


def default_config_path(standards_path: Path) -> Path:
    """Conventional rules.yml location: alongside the standards file."""
    return standards_path.parent / "rules.yml"


@dataclass
class RuleConfig:
    """Which rules are on, severity overrides, and per-rule params (from rules.yml)."""

    disabled: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)  # force-on for off-by-default rules
    severity_overrides: dict[str, str] = field(default_factory=dict)
    params: dict[str, dict] = field(default_factory=dict)  # per-rule tunables (e.g. thresholds)
    configured: set[str] = field(default_factory=set)  # every rule id mentioned in the file

    @classmethod
    def load(cls, path: Path | None) -> "RuleConfig":
        """Load a rules.yml, or return an empty (all-enabled) config."""
        if path is None or not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = data.get("rules", {}) if isinstance(data, dict) else {}
        disabled: set[str] = set()
        enabled: set[str] = set()
        overrides: dict[str, str] = {}
        params: dict[str, dict] = {}
        for rule_id, settings in (rules or {}).items():
            settings = settings or {}
            if settings.get("enabled") is False:
                disabled.add(rule_id)
            elif settings.get("enabled") is True:
                enabled.add(rule_id)  # turn on an off-by-default rule
            severity = settings.get("severity")
            if severity:
                # Validate up front: an unknown severity sorts below `info` and
                # would silently drop the rule's findings at the default floor,
                # which violates the "never silently dropped" contract.
                if severity not in SEVERITIES:
                    raise StandardsError(
                        f"rules.yml: rule '{rule_id}' has invalid severity '{severity}'; "
                        f"expected one of {', '.join(SEVERITIES)}"
                    )
                overrides[rule_id] = severity
            if isinstance(settings.get("params"), dict):
                params[rule_id] = settings["params"]
        return cls(
            disabled=disabled,
            enabled=enabled,
            severity_overrides=overrides,
            params=params,
            configured=set(rules or {}),
        )

    def unknown_rule_ids(self, known: set[str]) -> list[str]:
        """Configured rule ids that don't match any real rule (typos / removed rules)."""
        return sorted(self.configured - known)


def apply_config(rules: list, config: RuleConfig) -> list:
    """Select active rules and apply severity / params overrides (non-mutating).

    A rule runs unless it is explicitly disabled, or it is off-by-default and not
    explicitly enabled in the config. Works on any rule dataclass with the
    ``id`` / ``severity`` / ``default_enabled`` / ``params`` fields.
    """
    out: list = []
    for rule in rules:
        if rule.id in config.disabled:
            continue
        if not rule.default_enabled and rule.id not in config.enabled:
            continue
        if rule.id in config.severity_overrides:
            rule = replace(rule, severity=config.severity_overrides[rule.id])
        if rule.id in config.params:
            rule = replace(rule, params={**rule.params, **config.params[rule.id]})
        out.append(rule)
    return out
