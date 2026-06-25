"""Self-update logic (no network): classification + the per-install-method command shapes."""

import subprocess
from pathlib import Path

from coop_review_core import upgrade as upmod
from coop_review_core.upgrade import (
    DependencyStatus,
    UpgradePlan,
    apply_plan,
    build_plan,
    classify_update,
    detect_install_method,
    direct_dependencies,
    is_vcs_spec,
    pip_install_origin,
    upgrade_command,
)

NAME = "coop-x-review"


def _recording_runner(record):
    def runner(cmd, **_kwargs):
        record.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return runner


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


def test_classify_update_prerelease_is_not_safe():
    # A PEP 440 pre/dev suffix must not fold its digits into the release tuple
    # and masquerade as a newer (safe) version — that would be a bogus
    # downgrade-to-rc recommendation. Such a "latest" is the same release => current.
    assert classify_update("1.0.0", "1.0.0rc1") != "safe"
    assert classify_update("1.0.0", "1.0.0rc1") == "current"
    assert classify_update("2.0.0", "2.0.0.dev3") != "safe"
    assert classify_update("2.0.0", "2.0.0.dev3") == "current"


def test_classify_update_numeric_ordering_preserved():
    # Clean numeric versions still order correctly (1.10 > 1.9, not string-compared).
    assert classify_update("1.9", "1.10") == "safe"
    assert classify_update("1.10", "1.9") == "current"
    assert classify_update("1.0.0", "1.0.1") == "safe"
    assert classify_update("1.2.3", "1.2.3") == "current"


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
    repo = Path("/repo")  # str(repo) renders per-OS (\repo on Windows) — match that, not a literal
    plan = _plan("git-checkout", checkout=repo, tool_note="2 new commit(s) available")
    assert upgrade_command(plan) == [
        ["git", "-C", str(repo), "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", str(repo)],
    ]


def test_upgrade_command_git_checkout_up_to_date_reinstalls_only():
    repo = Path("/repo")
    plan = _plan("git-checkout", checkout=repo, tool_note="checkout is up to date with its upstream")
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", str(repo)]]


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


# -- apply_plan (the executing path; tools print instead, but it's public core API) ----------


def test_apply_plan_pipx_pypi_uses_upgrade():
    record = []
    apply_plan(_plan("pipx"), runner=_recording_runner(record))
    assert record[0][:2] == ["pipx", "upgrade"]


def test_apply_plan_pipx_vcs_uses_reinstall_not_force():
    record = []
    apply_plan(_plan("pipx", pip_spec="git+https://e/x.git@main"), runner=_recording_runner(record))
    assert record[0][:2] == ["pipx", "reinstall"]


def test_apply_plan_pip_url_force_reinstalls():
    record = []
    apply_plan(_plan("pip", pip_spec="git+https://e/x.git"), runner=_recording_runner(record))
    assert "--force-reinstall" in record[0]


def test_apply_plan_pip_safe_dependency_bump_pins_below_next_major():
    record = []
    plan = _plan("pip")
    plan.dependencies.append(DependencyStatus("widget", "1.0.0", "1.2.0", "safe"))
    apply_plan(plan, runner=_recording_runner(record))
    # second command bumps the safe dep, pinned below its next major (1.x -> <2)
    assert any("widget<2" in tok for tok in record[1])


# -- install detection / origin (newly parameterized by package_name) ------------------------


def test_pip_install_origin_parses_vcs(monkeypatch):
    class _Dist:
        def read_text(self, _name):
            return '{"url":"https://e/x.git","vcs_info":{"vcs":"git","requested_revision":"main"}}'

    monkeypatch.setattr(upmod.metadata, "distribution", lambda _n: _Dist())
    assert pip_install_origin("pkg") == "git+https://e/x.git@main"


def test_pip_install_origin_parses_editable(monkeypatch):
    class _Dist:
        def read_text(self, _name):
            return '{"url":"file:///home/u/proj","dir_info":{"editable":true}}'

    monkeypatch.setattr(upmod.metadata, "distribution", lambda _n: _Dist())
    assert pip_install_origin("pkg") == "-e /home/u/proj"


def test_pip_install_origin_none_for_plain_pypi(monkeypatch):
    class _Dist:
        def read_text(self, _name):
            raise FileNotFoundError

    monkeypatch.setattr(upmod.metadata, "distribution", lambda _n: _Dist())
    assert pip_install_origin("pkg") is None


def test_direct_dependencies_excludes_extras(monkeypatch):
    monkeypatch.setattr(upmod.metadata, "requires", lambda _n: ["click>=8.1", "pytest>=8.0; extra == 'dev'"])
    assert direct_dependencies("pkg") == ["click"]


def test_detect_install_method_finds_git_checkout(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('name = "mypkg"\n', encoding="utf-8")
    (tmp_path / ".git").mkdir()
    venv = tmp_path / ".venv"
    venv.mkdir()
    monkeypatch.setattr(upmod.sys, "prefix", str(venv))
    method, checkout = detect_install_method("mypkg")
    assert method == "git-checkout"
    assert (checkout / "pyproject.toml").exists()
