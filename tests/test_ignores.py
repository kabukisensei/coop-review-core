"""The rules.yml ``ignore:`` writer (``add_ignores``): it appends findings to the
one writable config file, de-duplicates by fingerprint, preserves everything else
in the file, and writes deterministically so re-runs are byte-stable."""

import pytest
import yaml

from coop_review_core.config import RuleConfig, StandardsError, add_ignores


def test_add_ignores_creates_file_and_records_fingerprints(tmp_path):
    cfg = tmp_path / "rules.yml"
    added = add_ignores(cfg, [{"fingerprint": "abc123", "rule": "SQL-X", "where": "a.sql:3", "note": "why"}])
    assert added == 1
    assert cfg.exists()
    # It round-trips: the tool reads back exactly what it wrote.
    assert RuleConfig.load(cfg).ignored_fingerprints == {"abc123"}


def test_add_ignores_preserves_rules_block_and_comments(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "# my house style\nrules:\n  SQL-NO-SELECT-STAR:\n    enabled: false  # noisy here\n",
        encoding="utf-8",
    )
    add_ignores(cfg, [{"fingerprint": "abc123", "rule": "SQL-Y"}])
    text = cfg.read_text(encoding="utf-8")
    assert "# my house style" in text  # comment untouched
    assert "enabled: false  # noisy here" in text  # rules: block + inline comment untouched
    assert "ignore:" in text and "abc123" in text
    # Both sections still parse together.
    config = RuleConfig.load(cfg)
    assert config.disabled == {"SQL-NO-SELECT-STAR"}
    assert config.ignored_fingerprints == {"abc123"}


def test_add_ignores_dedupes_and_is_idempotent(tmp_path):
    cfg = tmp_path / "rules.yml"
    add_ignores(cfg, [{"fingerprint": "aaa", "rule": "R1"}, {"fingerprint": "bbb", "rule": "R2"}])
    first = cfg.read_text(encoding="utf-8")
    # Re-adding the same fingerprints adds nothing and rewrites byte-identically.
    added = add_ignores(cfg, [{"fingerprint": "aaa", "rule": "R1"}, {"fingerprint": "bbb", "rule": "R2"}])
    assert added == 0
    assert cfg.read_text(encoding="utf-8") == first
    # A genuinely new one is appended; the existing note is preserved.
    added = add_ignores(cfg, [{"fingerprint": "aaa", "note": "changed"}, {"fingerprint": "ccc"}])
    assert added == 1  # only ccc is new
    entries = {e["fingerprint"]: e for e in yaml.safe_load(cfg.read_text())["ignore"]}
    assert set(entries) == {"aaa", "bbb", "ccc"}
    assert "note" not in entries["aaa"]  # existing entry wins (it had no note)


def test_add_ignores_quotes_awkward_values(tmp_path):
    cfg = tmp_path / "rules.yml"
    add_ignores(
        cfg, [{"fingerprint": "x", "note": "reason: with colon & symbols", "where": "with space.sql"}]
    )
    reloaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))["ignore"][0]
    assert reloaded["note"] == "reason: with colon & symbols"  # awkward text round-trips intact
    assert reloaded["where"] == "with space.sql"


def test_add_ignores_round_trips_yaml_pitfalls(tmp_path):
    # Values that a naive bare emit would corrupt: the DAX measure style
    # ``[Category: Name]`` (a mid-value ": " is a YAML mapping indicator), a
    # trailing colon, a comment indicator " #", a leading "[", and a YAML keyword.
    cfg = tmp_path / "rules.yml"
    pitfalls = [
        {"fingerprint": "a", "where": "Sales/[Sales: Enterprise Revenue YTD]"},
        {"fingerprint": "b", "where": "[Measure]", "note": "watch out # not a comment"},
        {"fingerprint": "c", "note": "ends with colon:"},
        {"fingerprint": "d", "note": "yes"},
        {"fingerprint": "e", "where": "file.sql:12"},  # colon-not-space stays bare + valid
    ]
    add_ignores(cfg, pitfalls)
    # It must re-parse without error and preserve every value exactly.
    from coop_review_core.config import RuleConfig

    assert RuleConfig.load(cfg).ignored_fingerprints == {"a", "b", "c", "d", "e"}
    by_fp = {e["fingerprint"]: e for e in yaml.safe_load(cfg.read_text(encoding="utf-8"))["ignore"]}
    assert by_fp["a"]["where"] == "Sales/[Sales: Enterprise Revenue YTD]"
    assert by_fp["b"]["note"] == "watch out # not a comment"
    assert by_fp["c"]["note"] == "ends with colon:"
    assert by_fp["d"]["note"] == "yes"
    assert by_fp["e"]["where"] == "file.sql:12"


def test_add_ignores_uses_lf_newlines(tmp_path):
    cfg = tmp_path / "rules.yml"
    add_ignores(cfg, [{"fingerprint": "x"}])
    assert b"\r\n" not in cfg.read_bytes()  # LF only, like every other file the tools write


def test_add_ignores_normalizes_crlf_input_to_lf(tmp_path):
    # A hand-edited rules.yml with Windows line endings must not yield a mixed-EOL
    # file when we splice in the ignore block.
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes(b"rules:\r\n  SQL-Z:\r\n    enabled: false\r\n")
    add_ignores(cfg, [{"fingerprint": "x"}])
    assert b"\r\n" not in cfg.read_bytes()  # normalized end-to-end
    config = RuleConfig.load(cfg)
    assert config.disabled == {"SQL-Z"} and config.ignored_fingerprints == {"x"}


def test_add_ignores_quotes_numeric_looking_values(tmp_path):
    # Numeric-looking strings must stay strings: a bare emit would reload as an
    # int/float (and "007" would lose its leading zero), silently breaking the
    # fingerprint match. Every value round-trips identically.
    cfg = tmp_path / "rules.yml"
    values = ["123", "007", "1.23", "1e5", "0x1f", "9_000"]
    add_ignores(cfg, [{"fingerprint": v} for v in values])
    assert RuleConfig.load(cfg).ignored_fingerprints == set(values)
    loaded = {str(e["fingerprint"]): e for e in yaml.safe_load(cfg.read_text())["ignore"]}
    for v in values:
        assert v in loaded  # each parsed back as the exact string, no coercion
    # A numeric note/where round-trips too.
    cfg2 = tmp_path / "r2.yml"
    add_ignores(cfg2, [{"fingerprint": "z", "where": "42", "note": "007"}])
    e = yaml.safe_load(cfg2.read_text())["ignore"][0]
    assert e["where"] == "42" and e["note"] == "007"


def test_add_ignores_refuses_duplicate_ignore_blocks(tmp_path):
    # A merge conflict / hand-edit can leave two top-level `ignore:` keys; YAML
    # keeps only the last on load, so a blind rewrite would silently drop the
    # other block. We fail safe instead of corrupting the file.
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - fingerprint: old1\nignore:\n  - fingerprint: old2\n", encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    with pytest.raises(StandardsError, match="more than one top-level 'ignore:'"):
        add_ignores(cfg, [{"fingerprint": "new1"}])
    assert cfg.read_text(encoding="utf-8") == before  # untouched — no data lost


def test_add_ignores_keeps_a_trailing_top_level_section(tmp_path):
    cfg = tmp_path / "rules.yml"
    # ignore: comes first, a rules: section follows it — the writer must not eat rules:.
    cfg.write_text(
        "ignore:\n  - fingerprint: old1\nrules:\n  SQL-Z:\n    enabled: false\n",
        encoding="utf-8",
    )
    add_ignores(cfg, [{"fingerprint": "new1"}])
    config = RuleConfig.load(cfg)
    assert config.ignored_fingerprints == {"old1", "new1"}
    assert config.disabled == {"SQL-Z"}  # the trailing rules: block survived
