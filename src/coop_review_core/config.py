"""The rules.yml config layer + standards-file resolution.

Tool-agnostic. ``apply_config`` works *structurally* on any rule dataclass that
has ``id`` / ``severity`` / ``default_enabled`` / ``params`` (it copies rules
with :func:`dataclasses.replace`), so each linter keeps its own ``Rule`` type.
``resolve_standards_path`` takes the linter's own bundled-standards path.

A ``rules.yml`` (sibling of the standards file, or ``--config``) can:
- disable a rule (``enabled: false``) or force-on an off-by-default one (``enabled: true``),
- override a rule's ``severity`` (validated against the known severities),
- set per-rule ``params:`` (e.g. thresholds) that the rule reads at run time,
- ``ignore:`` a list of specific findings by their stable ``fingerprint`` — a
  human-readable, line-independent way to silence known findings that survives
  edits (each entry keeps ``rule`` / ``where`` / ``note`` for the reader). The
  tool can append to this list for you (:func:`add_ignores`), and you can edit
  it by hand.

Editing it changes behavior with no rebuild.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypeVar

import yaml

from coop_review_core.errors import CoopReviewError
from coop_review_core.severity import SEVERITIES

__all__ = [
    "StandardsError",
    "resolve_standards_path",
    "standards_info",
    "default_config_path",
    "RuleConfig",
    "SYNTAX_ERROR_MODES",
    "parse_syntax_errors_knob",
    "load_config_friendly",
    "apply_config",
    "add_ignores",
]

# The optional keys an ``ignore:`` entry may carry, rendered in this order.
# ``fingerprint`` is the only match key; the rest are human context.
_IGNORE_KEYS = ("fingerprint", "rule", "where", "note")
# Values that a bare (unquoted) YAML scalar would coerce to a non-string.
_YAML_KEYWORDS = {"true", "false", "null", "yes", "no", "on", "off", "none", "~"}
# Leading characters that make a plain scalar ambiguous (indicators).
_YAML_LEADING_INDICATORS = set("-?:,[]{}#&*!|>'\"%@`")


class StandardsError(CoopReviewError):
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
    ignored_fingerprints: set[str] = field(default_factory=set)  # findings silenced via `ignore:`

    @classmethod
    def load(cls, path: Path | None) -> "RuleConfig":
        """Load a rules.yml from ``path``, or return an empty (all-enabled) config.

        A thin read-then-:meth:`loads` (single read, ``utf-8-sig`` so a BOM from a
        PowerShell redirect is tolerated). For the CLI's friendly-error contract —
        encoding sniff, one-line messages, and the raw mapping for extra-key checks
        — use :func:`load_config_friendly` instead (issue #4)."""
        if path is None or not Path(path).is_file():
            return cls()
        return cls.loads(Path(path).read_text(encoding="utf-8-sig"))

    @classmethod
    def loads(cls, text: str) -> "RuleConfig":
        """Build a RuleConfig from already-read rules.yml ``text`` (empty text ->
        empty config), so a caller that already has the text doesn't re-read the
        file. Lenient on shape (a non-mapping top level / ``rules:`` is treated as
        empty); still raises :class:`StandardsError` on an invalid ``severity``."""
        return cls._from_data(yaml.safe_load(text) if text.strip() else None)

    @classmethod
    def _from_data(cls, data: object) -> "RuleConfig":
        """Build a RuleConfig from parsed YAML ``data``. Shared by :meth:`loads`
        and :func:`load_config_friendly`; lenient on shape by design (the friendly
        loader does the strict shape validation before calling this)."""
        rules = data.get("rules", {}) if isinstance(data, dict) else {}
        disabled: set[str] = set()
        enabled: set[str] = set()
        overrides: dict[str, str] = {}
        params: dict[str, dict] = {}
        for raw_id, settings in (rules or {}).items():
            # YAML parses an unquoted numeric key (`123:`) as an int (and `on:`
            # as a bool, etc.). Coerce every rule id to str so the disabled/
            # enabled/overrides/params keys stay homogeneous and
            # unknown_rule_ids' sorted() can't raise a raw TypeError.
            rule_id = str(raw_id)
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
        ignore_section = data.get("ignore", []) if isinstance(data, dict) else []
        return cls(
            disabled=disabled,
            enabled=enabled,
            severity_overrides=overrides,
            params=params,
            configured={str(rule_id) for rule_id in (rules or {})},
            ignored_fingerprints={e["fingerprint"] for e in _read_ignore_entries(ignore_section)},
        )

    def unknown_rule_ids(self, known: set[str]) -> list[str]:
        """Configured rule ids that don't match any real rule (typos / removed rules)."""
        return sorted(self.configured - known)


# The `syntax_errors:` knob shared by the linters (issue #4/#1): a valid syntax
# diagnostic is kept as an error (default), demoted to a warning, or dropped.
SYNTAX_ERROR_MODES = ("error", "warning", "off")

# The friendly, one-line problem messages (no traceback) for a bad rules.yml.
# Kept verbatim from the tools' own `_load_rule_config` so their existing
# config-error tests keep passing after they switch to `load_config_friendly`.
_MSG_NOT_UTF8 = "the file is not UTF-8 - re-save it as UTF-8 (PowerShell '>' writes UTF-16)"
_MSG_TOP_LEVEL = "the top level must be a mapping (e.g. a `rules:` section)"
_MSG_RULES_MAPPING = "`rules:` must be a mapping of rule ids to settings, not a list"


def parse_syntax_errors_knob(raw: object, modes: tuple[str, ...] = SYNTAX_ERROR_MODES) -> str:
    """Resolve a ``syntax_errors:`` knob value to a mode string.

    YAML 1.1 coerces a bare unquoted ``off``/``no`` to the boolean ``False`` (and
    ``on``/``yes``/``true`` to ``True``), so ``syntax_errors: off`` arrives as
    ``False`` — mapped here to ``"off"`` so it works unquoted; a truthy form has no
    matching mode and is rejected. Raises :class:`StandardsError` on an unknown
    value (the caller wraps it in its own friendly one-liner)."""
    candidate = "off" if raw is False else str(raw).strip().lower()
    if candidate not in modes:
        raise StandardsError(f"`syntax_errors` must be one of {', '.join(modes)} (got '{raw}')")
    return candidate


def load_config_friendly(path: Path | None) -> tuple[RuleConfig, dict]:
    """The full validated rules.yml load for a CLI, click-free.

    ONE read (``utf-8-sig`` + a NUL sniff for UTF-16-without-a-BOM), and returns
    both the :class:`RuleConfig` AND the raw top-level mapping — so a tool can
    validate its own extra keys (e.g. a ``syntax_errors:`` knob, via
    :func:`parse_syntax_errors_knob`) WITHOUT re-reading or re-parsing the file
    (issue #4 closed the CLI-then-``RuleConfig.load`` double-read/TOCTOU window).

    Every failure mode raises :class:`StandardsError` with a friendly, one-line
    message (bad encoding, invalid YAML, a non-mapping top level, a non-mapping
    ``rules:``, an invalid severity, or an otherwise-unexpected structure); the
    caller wraps it (e.g. ``click.UsageError`` / exit 2). An absent path is the
    empty config with an empty mapping."""
    if path is None or not Path(path).is_file():
        return RuleConfig(), {}
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
        if "\x00" in text:  # UTF-16 without a BOM decodes as NUL-riddled "UTF-8"
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "null byte")
    except UnicodeDecodeError:
        raise StandardsError(_MSG_NOT_UTF8) from None
    except OSError as exc:
        raise StandardsError(str(exc)) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise StandardsError(f"invalid YAML - {' '.join(str(exc).split())}") from exc
    if data is not None and not isinstance(data, dict):
        raise StandardsError(_MSG_TOP_LEVEL)
    if isinstance(data, dict) and data.get("rules") is not None and not isinstance(data["rules"], dict):
        raise StandardsError(_MSG_RULES_MAPPING)
    try:
        config = RuleConfig._from_data(data)
    except StandardsError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # A malformed `ignore:` entry etc. still surfaces as the same friendly line.
        raise StandardsError(f"unexpected structure ({exc})") from exc
    return config, (data if isinstance(data, dict) else {})


# Each linter's own Rule dataclass flows through apply_config unchanged: the
# TypeVar keeps `list[Rule] -> list[Rule]` for the consumer's type checker.
# Plain TypeVar, not PEP 695 syntax — this package stays 3.10-compatible.
RuleT = TypeVar("RuleT")


def apply_config(rules: list[RuleT], config: RuleConfig) -> list[RuleT]:
    """Select active rules and apply severity / params overrides (non-mutating).

    A rule runs unless it is explicitly disabled, or it is off-by-default and not
    explicitly enabled in the config. Works on any rule dataclass with the
    ``id`` / ``severity`` / ``default_enabled`` / ``params`` fields.
    """
    out: list[RuleT] = []
    for original in rules:
        # Typed as Any inside: the contract is structural (any dataclass carrying
        # the four fields), which a plain TypeVar can't express to a type checker.
        rule: Any = original
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


# --- the `ignore:` list: human-readable, fingerprint-matched suppressions -----
#
# The list lives in rules.yml so a user has ONE writable config file. Matching is
# purely on ``fingerprint`` (stable + line-independent, see severity.fingerprint);
# ``rule`` / ``where`` / ``note`` are there so the reader knows what a line means.
# ``add_ignores`` rewrites ONLY the ``ignore:`` block and leaves the rest of the
# file — comments and the ``rules:`` section — byte-for-byte intact.


def _read_ignore_entries(section) -> list[dict]:
    """Normalize a raw ``ignore:`` value into a list of ``{fingerprint, ...}`` dicts.

    Lenient like the baseline loader: a bare string is treated as a fingerprint,
    a mapping must carry a ``fingerprint``; anything without one is skipped so a
    malformed entry silences nothing rather than everything.
    """
    if not isinstance(section, list):
        return []
    entries: list[dict] = []
    for raw in section:
        if isinstance(raw, str):
            fp = raw.strip()
            if fp:
                entries.append({"fingerprint": fp})
        elif isinstance(raw, dict):
            fp = str(raw.get("fingerprint") or "").strip()
            if not fp:
                continue
            entry = {"fingerprint": fp}
            for key in _IGNORE_KEYS[1:]:
                value = raw.get(key)
                if value not in (None, ""):
                    entry[key] = str(value)
            entries.append(entry)
    return entries


def _needs_quote(text: str) -> bool:
    """Whether a value must be double-quoted to round-trip as a YAML string.

    Guards the pitfalls that would otherwise corrupt or truncate the value:
    ``": "`` / a trailing ``":"`` (a mapping indicator — e.g. the DAX measure
    style ``[Category: Name]``), ``" #"`` (a comment indicator), a leading
    indicator/whitespace char, or any control character. The final round-trip
    catch-all quotes anything YAML would reload as a *non-identical* value — a
    number (``007`` -> ``7``, ``1.2`` -> a float), a bool/null, a date, etc. —
    so every string field survives a write+reload unchanged.
    """
    if text == "" or text != text.strip() or text[0] in _YAML_LEADING_INDICATORS:
        return True
    if text.lower() in _YAML_KEYWORDS:
        return True
    if ": " in text or text.endswith(":") or " #" in text:
        return True
    if any(ord(ch) < 0x20 for ch in text):
        return True
    try:
        return yaml.safe_load(text) != text
    except yaml.YAMLError:
        return True


def _yaml_scalar(value: str) -> str:
    """A single YAML scalar: bare when unambiguous, else double-quoted (JSON is
    valid YAML), so any ``note`` / ``where`` text round-trips deterministically."""
    text = str(value)
    return json.dumps(text, ensure_ascii=False) if _needs_quote(text) else text


def _render_ignore_block(entries: list[dict]) -> str:
    """Render the ``ignore:`` block deterministically (sorted, 2-space indent, LF).

    Sorted by (rule, where, fingerprint) so the file is stable + human-scannable;
    empty optional fields are omitted.
    """
    ordered = sorted(entries, key=lambda e: (e.get("rule", ""), e.get("where", ""), e["fingerprint"]))
    lines = ["ignore:"]
    for entry in ordered:
        lines.append(f"  - fingerprint: {_yaml_scalar(entry['fingerprint'])}")
        for key in _IGNORE_KEYS[1:]:
            if entry.get(key) not in (None, ""):
                lines.append(f"    {key}: {_yaml_scalar(entry[key])}")
    return "\n".join(lines) + "\n"


def _is_top_level_key(line: str) -> bool:
    """True for a line that starts a top-level YAML key (column 0, ``key:``)."""
    return bool(line) and not line[0].isspace() and re.match(r"[^\s#][^:]*:", line) is not None


def _ends_ignore_block(line: str) -> bool:
    """True for a line that ENDS the ``ignore:`` block: a top-level key, or a
    **column-0 comment** — a user's hand-written top-level note that follows the
    block and must be preserved. An INDENTED comment (aligned with the entries)
    is NOT an end marker: it is owned by the writer and rewritten with the block."""
    return _is_top_level_key(line) or (bool(line) and line[0] == "#")


def _replace_ignore_block(text: str, block: str) -> str:
    """Return ``text`` with its top-level ``ignore:`` block replaced by ``block``
    (or ``block`` appended if there is none). Everything outside the block —
    the ``rules:`` section, top-level keys, and **top-level (column-0) comments**,
    including one that immediately follows the block or sits at EOF — is preserved
    verbatim. A comment *indented inside* the block is part of the rewritten
    entries and is intentionally dropped."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"ignore\s*:", ln)), None)
    if start is None:
        if text and not text.endswith("\n"):
            text += "\n"
        if text.strip():  # keep a blank line between the existing content and the block
            text += "\n"
        return text + block
    # The block owns its `ignore:` line, its indented entries, and any trailing
    # blank lines — up to the first top-level key OR top-level comment.
    end = start + 1
    while end < len(lines) and not _ends_ignore_block(lines[end]):
        end += 1
    tail = lines[end:]
    # A following top-level key/comment stays readable with exactly one blank line.
    sep = "\n" if tail and tail[0].strip() else ""
    return "".join(lines[:start]) + block + sep + "".join(tail)


def add_ignores(config_path: Path, entries: list[dict]) -> int:
    """Merge ignore ``entries`` into the ``ignore:`` block of the rules.yml at
    ``config_path``, creating the file if needed. De-duplicates by ``fingerprint``
    (existing entries win, keeping their notes); returns how many NEW fingerprints
    were added. The write is deterministic (sorted, LF) and touches only the
    ``ignore:`` block. Each entry needs a ``fingerprint``; ``rule`` / ``where`` /
    ``note`` are optional context."""
    config_path = Path(config_path)
    # utf-8-sig, like every loader: a BOM (e.g. from a PowerShell redirect) glued
    # to a first-line `ignore:` key otherwise hides that line from both the
    # duplicate-block guard and the splice anchor below, so a second top-level
    # `ignore:` block gets appended. The write below stays BOM-less.
    text = config_path.read_text(encoding="utf-8-sig") if config_path.is_file() else ""
    # Refuse to touch a file with two top-level `ignore:` keys (a merge conflict
    # or a hand-edit): YAML keeps only the last on load, so a blind rewrite would
    # silently drop the other block's entries. Fail safe — the user resolves it.
    if sum(1 for ln in text.splitlines() if re.match(r"ignore\s*:", ln)) > 1:
        raise StandardsError(
            f"{config_path} has more than one top-level 'ignore:' key; "
            "merge them into one by hand before saving new ignores"
        )
    loaded = yaml.safe_load(text) if text.strip() else None
    existing = _read_ignore_entries(loaded.get("ignore") if isinstance(loaded, dict) else [])
    by_fp = {e["fingerprint"]: e for e in existing}
    added = 0
    for entry in entries:
        fp = str(entry.get("fingerprint") or "").strip()
        if not fp or fp in by_fp:
            continue
        clean = {"fingerprint": fp}
        for key in _IGNORE_KEYS[1:]:
            value = entry.get(key)
            if value not in (None, ""):
                clean[key] = str(value)
        by_fp[fp] = clean
        added += 1
    new_text = _replace_ignore_block(text, _render_ignore_block(list(by_fp.values())))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(new_text, encoding="utf-8", newline="\n")
    return added
