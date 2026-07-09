"""Unified config discovery: explicit > env > walk-up (tool-named, then the
deprecated rules.yml) > bundled (issue #12)."""

from pathlib import Path

import pytest

from coop_review_core.config import (
    StandardsError,
    config_env_var,
    discover_config,
    tool_config_filename,
)

TOOL = "coop-sql-review"


def _discover(start, *, explicit=None, env=None, bundled=None, tool=TOOL):
    return discover_config(tool, explicit=explicit, env=env or {}, start=start, bundled_default=bundled)


@pytest.fixture
def repo(tmp_path):
    """A fake repo root (bounded by .git) with a nested working directory."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "sql" / "silver"
    nested.mkdir(parents=True)
    return tmp_path


# --- name derivation -----------------------------------------------------------


def test_env_var_and_filename_derive_from_the_tool_name():
    assert config_env_var("coop-sql-review") == "COOP_SQL_REVIEW_CONFIG"
    assert config_env_var("coop-dax-review") == "COOP_DAX_REVIEW_CONFIG"
    assert tool_config_filename("coop-sql-review") == "coop-sql-review.yml"
    assert tool_config_filename("coop-dax-review") == "coop-dax-review.yml"


# --- tier 1: explicit -------------------------------------------------------------


def test_explicit_beats_everything(repo):
    cfg = repo / "team.yml"
    cfg.write_text("rules: {}\n", encoding="utf-8")
    (repo / tool_config_filename(TOOL)).write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo, explicit=str(cfg), env={config_env_var(TOOL): str(cfg)})
    assert found.path == cfg
    assert found.source == "explicit"
    assert found.notes == ()


def test_explicit_missing_is_a_friendly_standards_error(repo):
    with pytest.raises(StandardsError, match="config file not found: nope.yml"):
        _discover(repo, explicit="nope.yml")


# --- tier 2: env var ----------------------------------------------------------------


def test_env_var_beats_the_walk(repo):
    env_cfg = repo / "ci.yml"
    env_cfg.write_text("rules: {}\n", encoding="utf-8")
    (repo / tool_config_filename(TOOL)).write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo, env={config_env_var(TOOL): str(env_cfg)})
    assert found.path == env_cfg
    assert found.source == "env"


def test_env_var_pointing_nowhere_is_an_error_not_a_silent_fallback(repo):
    with pytest.raises(StandardsError, match="COOP_SQL_REVIEW_CONFIG"):
        _discover(repo, env={config_env_var(TOOL): str(repo / "gone.yml")})


def test_empty_env_var_counts_as_unset(repo):
    bundled = repo / "bundled" / "rules.yml"
    found = _discover(repo, env={config_env_var(TOOL): ""}, bundled=bundled)
    assert found.source == "bundled"


def test_only_this_tools_env_var_applies(repo):
    other = repo / "dax.yml"
    other.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo, env={"COOP_DAX_REVIEW_CONFIG": str(other)}, bundled=None)
    assert found.source == "none"


# --- tier 3: the walk -------------------------------------------------------------


def test_tool_named_file_found_in_the_start_directory(repo):
    cfg = repo / "sql" / "silver" / tool_config_filename(TOOL)
    cfg.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo / "sql" / "silver")
    assert found.path == cfg
    assert found.source == "tool-file"
    assert found.notes == ()


def test_walk_up_finds_the_repo_root_config_from_a_nested_cwd(repo):
    cfg = repo / tool_config_filename(TOOL)
    cfg.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo / "sql" / "silver")
    assert found.path == cfg
    assert found.source == "tool-file"


def test_legacy_rules_yml_still_works_with_a_deprecation_note(repo):
    cfg = repo / "sql" / "silver" / "rules.yml"
    cfg.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo / "sql" / "silver")
    assert found.path == cfg
    assert found.source == "rules-yml"
    assert len(found.notes) == 1
    assert "deprecated" in found.notes[0]
    assert tool_config_filename(TOOL) in found.notes[0]  # tells the user the new name


def test_same_dir_shadowing_tool_named_wins_and_notes_the_shadow(repo):
    tool_cfg = repo / tool_config_filename(TOOL)
    tool_cfg.write_text("rules: {}\n", encoding="utf-8")
    legacy = repo / "rules.yml"
    legacy.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo)
    assert found.path == tool_cfg
    assert found.source == "tool-file"
    assert len(found.notes) == 1
    assert "shadowed" in found.notes[0]
    assert "rules.yml" in found.notes[0]


def test_per_directory_precedence_a_nearer_rules_yml_beats_a_farther_tool_file(repo):
    (repo / tool_config_filename(TOOL)).write_text("rules: {}\n", encoding="utf-8")
    near = repo / "sql" / "rules.yml"
    near.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo / "sql" / "silver")
    assert found.path == near  # nearest directory wins; within it, tool-named first
    assert found.source == "rules-yml"


def test_walk_never_crosses_a_git_boundary_upward(tmp_path):
    outside = tmp_path / "rules.yml"  # a config OUTSIDE the repo
    outside.write_text("rules: {}\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    nested = repo_root / "src"
    nested.mkdir()
    found = _discover(nested, bundled=None)
    assert found.source == "none"  # the outside config must never silently apply


def test_the_git_boundary_directory_itself_is_still_checked(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    cfg = repo_root / "rules.yml"
    cfg.write_text("rules: {}\n", encoding="utf-8")
    found = _discover(repo_root / "." if (repo_root / ".").exists() else repo_root)
    assert found.path == cfg


def test_a_git_file_is_a_boundary_too(tmp_path):
    # git worktrees / submodules use a .git FILE, not a directory.
    outside = tmp_path / "rules.yml"
    outside.write_text("rules: {}\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    found = _discover(worktree, bundled=None)
    assert found.source == "none"


def test_walk_stops_at_the_filesystem_root(tmp_path):
    # From the real filesystem root there are no parents left: the walk must
    # terminate (no infinite loop) and fall through. An improbable tool name
    # guarantees no real file on this machine matches.
    bundled = tmp_path / "bundled-rules.yml"
    found = _discover(Path(Path(tmp_path).anchor), bundled=bundled, tool="coop-zz-nonexistent-review-zz")
    assert found.source == "bundled"
    assert found.path == bundled


# --- tier 4: bundled fallback ---------------------------------------------------------


def test_bundled_fallback_returned_as_is_even_when_missing(repo):
    bundled = repo / "site-packages" / "tool" / "data" / "rules.yml"  # does not exist
    found = _discover(repo / "sql" / "silver", bundled=bundled)
    assert found.path == bundled  # the loaders treat a missing file as the empty config
    assert found.source == "bundled"


def test_nothing_anywhere_yields_none(repo):
    found = _discover(repo / "sql" / "silver", bundled=None)
    assert found == found.__class__(path=None, source="none")
