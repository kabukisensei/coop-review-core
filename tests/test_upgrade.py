"""Self-update logic (no network): classification + the per-install-method command shapes."""

from pathlib import Path

from coop_review_core.upgrade import (
    UpgradePlan,
    build_plan,
    classify_update,
    is_vcs_spec,
    upgrade_command,
)

NAME = "coop-x-review"


def _plan(method, *, checkout=None, pip_spec=None, tool_note="note") -> UpgradePlan:
    return UpgradePlan(
        package_name=NAME,
        install_method=method,
        checkout=checkout,
        tool_installed="0.1.0",
        tool_note=tool_note,
        pip_spec=pip_spec,
    )


def test_classify_update():
    assert classify_update("1.0.0", None) == "unknown"
    assert classify_update("1.0.0", "1.0.0") == "current"
    assert classify_update("1.0.0", "1.2.0") == "safe"
    assert classify_update("1.0.0", "2.0.0") == "major"


def test_is_vcs_spec_by_scheme_not_substring():
    assert is_vcs_spec("git+https://example/x.git")
    assert not is_vcs_spec("/home/u/c++proj")
    assert not is_vcs_spec(None)


def test_upgrade_command_pipx_pypi_and_vcs():
    assert upgrade_command(_plan("pipx")) == [["pipx", "upgrade", NAME]]
    assert upgrade_command(_plan("pipx", pip_spec="git+https://e/x.git@main")) == [
        ["pipx", "reinstall", NAME]
    ]


def test_upgrade_command_uv_tool():
    assert upgrade_command(_plan("uv-tool")) == [["uv", "tool", "upgrade", NAME]]
    assert upgrade_command(_plan("uv-tool", pip_spec="git+https://e/x.git@main")) == [
        ["uv", "tool", "install", "--force", "git+https://e/x.git@main"]
    ]


def test_upgrade_command_pip_pypi_url_and_editable():
    assert upgrade_command(_plan("pip")) == [["python", "-m", "pip", "install", "-U", NAME]]
    assert upgrade_command(_plan("pip", pip_spec="git+https://e/x.git@main")) == [
        ["python", "-m", "pip", "install", "-U", "--force-reinstall", "git+https://e/x.git@main"]
    ]
    assert upgrade_command(_plan("pip", pip_spec="-e /home/u/proj")) == [
        ["python", "-m", "pip", "install", "-U", "--force-reinstall", "-e", "/home/u/proj"]
    ]


def test_upgrade_command_git_checkout_pull_then_reinstall():
    plan = _plan("git-checkout", checkout=Path("/repo"), tool_note="2 new commit(s) available")
    assert upgrade_command(plan) == [
        ["git", "-C", "/repo", "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", "/repo"],
    ]


def test_upgrade_command_git_checkout_up_to_date_reinstalls_only():
    plan = _plan("git-checkout", checkout=Path("/repo"), tool_note="checkout is up to date with its upstream")
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", "/repo"]]


def test_build_plan_offline_with_injected_collaborators():
    # No real network/subprocess: inject the fetcher and origin.
    plan = build_plan(
        NAME,
        "0.1.0",
        fetch=lambda name: "0.2.0",
        installed_version_of=lambda name: "1.0.0",
        origin=lambda pkg: None,
    )
    assert plan.package_name == NAME
    assert plan.tool_installed == "0.1.0"
    assert "latest release is 0.2.0" in plan.tool_note  # newer release detected
