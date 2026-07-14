"""The rules.yml ``ignore:`` writer (``add_ignores``): it appends findings to the
one writable config file, de-duplicates by fingerprint, preserves everything else
in the file, and writes deterministically so re-runs are byte-stable."""

from pathlib import Path

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


def test_add_ignores_round_trips_a_bom_prefixed_file(tmp_path):
    # A PowerShell-redirected rules.yml carries a UTF-8 BOM. Every loader reads
    # utf-8-sig; add_ignores must too — a BOM glued to a first-line `ignore:` key
    # used to evade both the duplicate-block guard and the splice anchor, so a
    # DUPLICATE top-level ignore: block was appended (and YAML then silently
    # dropped one of them on load).
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes(b"\xef\xbb\xbfignore:\n  - fingerprint: old1\n")
    add_ignores(cfg, [{"fingerprint": "new1"}])
    raw = cfg.read_bytes()
    assert raw.count(b"ignore:") == 1  # spliced into the ONE existing block
    assert not raw.startswith(b"\xef\xbb\xbf")  # writer stays BOM-less, like the loaders
    assert RuleConfig.load(cfg).ignored_fingerprints == {"old1", "new1"}


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


def test_add_ignores_preserves_a_top_level_comment_after_the_block(tmp_path):
    # issue #2: a column-0 comment right after the ignore block is a user note and
    # must survive a rewrite (it used to be consumed by the block end-scan).
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "rules:\n  X-A-B:\n    enabled: false\n\n"
        "ignore:\n  - fingerprint: aaa\n"
        "# reviewed by team 2026-07\n\n"
        "other: true\n",
        encoding="utf-8",
    )
    add_ignores(cfg, [{"fingerprint": "bbb", "rule": "X-A-B"}])
    out = cfg.read_text(encoding="utf-8")
    assert "# reviewed by team 2026-07" in out
    assert "other: true" in out
    assert "bbb" in out
    # still valid YAML with both fingerprints
    data = yaml.safe_load(out)
    assert {e["fingerprint"] for e in data["ignore"]} == {"aaa", "bbb"}
    assert data["other"] is True


def test_add_ignores_preserves_a_trailing_eof_comment_after_the_block(tmp_path):
    # issue #2: the same end-scan also ate an EOF comment when ignore: was last.
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "ignore:\n  - fingerprint: aaa\n# end-of-file note\n",
        encoding="utf-8",
    )
    add_ignores(cfg, [{"fingerprint": "bbb"}])
    out = cfg.read_text(encoding="utf-8")
    assert "# end-of-file note" in out
    assert yaml.safe_load(out)["ignore"] and {e["fingerprint"] for e in yaml.safe_load(out)["ignore"]} == {
        "aaa",
        "bbb",
    }


def test_add_ignores_maps_invalid_yaml_to_friendly_standards_error(tmp_path):
    # The target of a --save-ignores run may be a file this run never validated
    # (config_write_path can select a path the run didn't read). Its read+parse
    # must honor the family contract: a friendly one-line StandardsError, never a
    # raw yaml.YAMLError traceback escaping to the user.
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - fingerprint: aaa\n  bad: [unbalanced\n", encoding="utf-8")
    with pytest.raises(StandardsError, match="invalid YAML") as excinfo:
        add_ignores(cfg, [{"fingerprint": "bbb"}])
    assert "\n" not in str(excinfo.value)  # one line, printable as-is


def test_add_ignores_maps_utf16_target_to_friendly_standards_error(tmp_path):
    # A UTF-16 target (e.g. a PowerShell-created file) must not raise a raw
    # UnicodeDecodeError with a codec traceback — it maps to the same friendly
    # not-UTF-8 StandardsError the loaders use. Both the BOM and BOM-less
    # (NUL-sniffed) forms are covered.
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes("ignore:\n  - fingerprint: aaa\n".encode("utf-16"))  # UTF-16 with BOM
    with pytest.raises(StandardsError, match="not UTF-8") as excinfo:
        add_ignores(cfg, [{"fingerprint": "bbb"}])
    assert "\n" not in str(excinfo.value)

    cfg2 = tmp_path / "r2.yml"
    cfg2.write_bytes("ignore:\n".encode("utf-16-le"))  # UTF-16 without a BOM (NUL sniff)
    with pytest.raises(StandardsError, match="not UTF-8"):
        add_ignores(cfg2, [{"fingerprint": "bbb"}])


def test_add_ignores_drops_an_indented_comment_inside_the_block(tmp_path):
    # documented behavior: a comment INDENTED with the entries is owned by the
    # writer and rewritten away (only top-level comments are preserved).
    cfg = tmp_path / "rules.yml"
    cfg.write_text(
        "ignore:\n  - fingerprint: aaa\n  # inner note about aaa\n\nother: true\n",
        encoding="utf-8",
    )
    add_ignores(cfg, [{"fingerprint": "bbb"}])
    out = cfg.read_text(encoding="utf-8")
    assert "# inner note about aaa" not in out  # intentionally dropped
    assert "other: true" in out  # the top-level key is still preserved
    assert {e["fingerprint"] for e in yaml.safe_load(out)["ignore"]} == {"aaa", "bbb"}


def test_add_ignores_maps_an_unreadable_target_to_friendly_standards_error(tmp_path, monkeypatch):
    # An existing but unreadable target (locked file, revoked permissions) hits the
    # read-path OSError branch: it must surface as a friendly one-line StandardsError,
    # never a raw PermissionError traceback out of a consumer's --save-ignores (#22).
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - fingerprint: aaa\n", encoding="utf-8")

    def _boom(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", _boom)
    with pytest.raises(StandardsError) as excinfo:
        add_ignores(cfg, [{"fingerprint": "bbb"}])
    assert "\n" not in str(excinfo.value)  # one line, printable as-is


def test_add_ignores_maps_an_unwritable_target_to_friendly_standards_error(tmp_path):
    # The write-back (mkdir + write_text) can fail too — a read-only dir, or an
    # ancestor that is a file. That OSError maps to the same friendly StandardsError
    # as the read path, so --save-ignores exits with one line, never a traceback (#22).
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file, not a directory\n", encoding="utf-8")
    cfg = blocker / "rules.yml"  # parent is a file -> mkdir/write_text raises OSError
    with pytest.raises(StandardsError, match="cannot write ignores") as excinfo:
        add_ignores(cfg, [{"fingerprint": "bbb"}])
    assert "\n" not in str(excinfo.value)
