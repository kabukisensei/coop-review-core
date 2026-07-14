"""Self-update logic (no network): classification + the per-install-method command shapes."""

from pathlib import Path

from coop_review_core import upgrade as upmod
from coop_review_core.upgrade import (
    DependencyStatus,
    UpgradePlan,
    build_plan,
    classify_update,
    detect_install_method,
    direct_dependencies,
    is_vcs_spec,
    pip_install_origin,
    upgrade_command,
)
from coop_review_core.upgrade import (
    _git_checkout_note,  # private, but the ONLY producer of needs_pull=True
)

NAME = "coop-x-review"


def _plan(method, *, checkout=None, pip_spec=None, tool_note="note", needs_pull=False) -> UpgradePlan:
    return UpgradePlan(
        package_name=NAME,
        install_method=method,
        checkout=checkout,
        tool_installed="0.1.0",
        tool_note=tool_note,
        pip_spec=pip_spec,
        needs_pull=needs_pull,
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


def test_classify_update_trailing_zero_difference_is_current():
    # Per PEP 440, trailing-zero-only differences are the SAME version, not an
    # upgrade — release tuples are length-normalized before comparison.
    assert classify_update("1.2", "1.2.0") == "current"
    assert classify_update("1.2.0", "1.2") == "current"
    assert classify_update("1", "1.0.0") == "current"


def test_classify_update_fifth_segment_difference_is_detected():
    # Release segments beyond the 4th are no longer truncated, so a version that
    # differs only in a 5th segment is a real (safe) update, not "current".
    assert classify_update("1.2.3.4.0", "1.2.3.4.9") == "safe"


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
    plan = _plan("git-checkout", checkout=repo, tool_note="2 new commit(s) available", needs_pull=True)
    assert upgrade_command(plan) == [
        ["git", "-C", str(repo), "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", str(repo)],
    ]


def test_upgrade_command_git_checkout_up_to_date_reinstalls_only():
    repo = Path("/repo")
    plan = _plan("git-checkout", checkout=repo, tool_note="checkout is up to date with its upstream")
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", str(repo)]]


def test_upgrade_command_pull_is_driven_by_needs_pull_not_note_wording():
    # The pull step is gated on the structured `needs_pull` flag, not the display
    # note: a reworded note still pulls when needs_pull is set, and a note that
    # happens to contain "new commit(s)" does NOT pull when needs_pull is False.
    repo = Path("/repo")
    reworded = _plan("git-checkout", checkout=repo, tool_note="upstream is ahead", needs_pull=True)
    assert upgrade_command(reworded) == [
        ["git", "-C", str(repo), "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", str(repo)],
    ]
    stale_note = _plan("git-checkout", checkout=repo, tool_note="2 new commit(s) available", needs_pull=False)
    assert upgrade_command(stale_note) == [["python", "-m", "pip", "install", "-U", str(repo)]]


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


def test_pip_install_origin_editable_decodes_percent_encoded_path(monkeypatch):
    # PEP 610 file URLs are percent-encoded, so a checkout path with a space
    # arrives as `%20`. Slicing off `file://` used to leave the literal `%20`
    # in the printed `-e` command, pointing at a nonexistent directory. It must
    # be url-decoded to a real filesystem path.
    class _Dist:
        def read_text(self, _name):
            return '{"url":"file:///home/u/My%20Projects/pkg","dir_info":{"editable":true}}'

    monkeypatch.setattr(upmod.metadata, "distribution", lambda _n: _Dist())
    assert pip_install_origin("pkg") == "-e /home/u/My Projects/pkg"


def test_pip_install_origin_editable_windows_url_converts_to_drive_path():
    # On Windows the PEP 610 file URL uses the `/C:/...` form; slicing off
    # `file://` yielded `-e /C:/Users/...`, which pip can't resolve. The
    # URL-splitting + nturl2path path (exercised directly, so the assertion is
    # platform-independent) must produce a real `C:\...` drive path.
    import urllib.parse
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # nturl2path deprecated 3.19+
        import nturl2path

    url = "file:///C:/Users/u/My%20Proj/pkg"
    converted = nturl2path.url2pathname(urllib.parse.urlsplit(url).path)
    assert converted == r"C:\Users\u\My Proj\pkg"


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


def test_detect_install_method_pipx_and_uv_tool(monkeypatch):
    # The pipx / uv-tool prefix-detection branches: sys.prefix living under a
    # pipx venv or uv tool dir classifies without touching pyproject/git.
    monkeypatch.setattr(upmod.sys, "prefix", "/home/u/.local/pipx/venvs/coop-x-review")
    assert detect_install_method("coop-x-review") == ("pipx", None)
    monkeypatch.setattr(upmod.sys, "prefix", "/home/u/.local/share/uv/tools/coop-x-review")
    assert detect_install_method("coop-x-review") == ("uv-tool", None)


# -- _git_checkout_note: the only producer of needs_pull, exercised with a fake runner ---------


class _Result:
    """Stand-in for a subprocess.CompletedProcess (only the fields the code reads)."""

    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _scripted_runner(*results):
    """A fake subprocess runner returning the given _Result objects in call order,
    recording each invoked git subcommand for assertions."""
    calls: list[str] = []
    queue = list(results)

    def runner(argv, **_kwargs):
        # argv is ["git", "-C", <checkout>, <subcommand>, ...]; record the subcommand.
        calls.append(argv[3])
        return queue.pop(0)

    runner.calls = calls
    return runner


def test_git_checkout_note_no_upstream():
    # rev-parse @{upstream} fails -> no upstream; never fetches, needs_pull False.
    runner = _scripted_runner(_Result(returncode=1))
    note, needs_pull = _git_checkout_note(Path("/repo"), runner)
    assert needs_pull is False
    assert "no upstream" in note
    assert runner.calls == ["rev-parse"]  # short-circuits before fetch


def test_git_checkout_note_fetch_failed():
    # upstream exists but `git fetch` fails (offline) -> needs_pull False.
    runner = _scripted_runner(_Result(returncode=0), _Result(returncode=1))
    note, needs_pull = _git_checkout_note(Path("/repo"), runner)
    assert needs_pull is False
    assert "fetch" in note
    assert runner.calls == ["rev-parse", "fetch"]  # stops before rev-list


def test_git_checkout_note_behind_sets_needs_pull():
    # rev-list count > 0 -> the ONLY path that sets needs_pull=True.
    runner = _scripted_runner(_Result(0), _Result(0), _Result(0, stdout="2\n"))
    note, needs_pull = _git_checkout_note(Path("/repo"), runner)
    assert needs_pull is True
    assert "2 new commit(s)" in note
    assert runner.calls == ["rev-parse", "fetch", "rev-list"]


def test_git_checkout_note_up_to_date():
    # rev-list count 0 -> up to date, needs_pull False.
    runner = _scripted_runner(_Result(0), _Result(0), _Result(0, stdout="0\n"))
    note, needs_pull = _git_checkout_note(Path("/repo"), runner)
    assert needs_pull is False
    assert "up to date" in note


def test_git_checkout_note_missing_git_binary_degrades_gracefully():
    # git not on PATH -> subprocess.run raises FileNotFoundError (an OSError);
    # the note degrades like the offline case instead of crashing.
    def runner(*_a, **_k):
        raise FileNotFoundError("git")

    note, needs_pull = _git_checkout_note(Path("/repo"), runner)
    assert needs_pull is False
    assert "could not be run" in note


def test_build_plan_git_checkout_missing_git_returns_usable_plan(tmp_path, monkeypatch):
    # A git-checkout install on a machine without git must still yield a usable
    # UpgradePlan (needs_pull False), not a FileNotFoundError traceback out of
    # build_plan — the family's 'never a traceback' contract.
    monkeypatch.setattr(upmod, "detect_install_method", lambda _pkg: ("git-checkout", tmp_path))

    def runner(*_a, **_k):
        raise FileNotFoundError("git")

    plan = build_plan(NAME, "0.1.0", runner=runner, origin=lambda _p: None)
    assert plan.install_method == "git-checkout"
    assert plan.needs_pull is False
    assert "could not be run" in plan.tool_note


# -- build_plan: git-checkout / VCS / dependency-loop branches ---------------------------------


def test_build_plan_git_checkout_flows_needs_pull_through(tmp_path, monkeypatch):
    # A git-checkout install with an upstream that is ahead must set the plan's
    # needs_pull, driven by the injected runner (no real git).
    monkeypatch.setattr(upmod, "detect_install_method", lambda _pkg: ("git-checkout", tmp_path))
    runner = _scripted_runner(_Result(0), _Result(0), _Result(0, stdout="3\n"))
    plan = build_plan(NAME, "0.1.0", runner=runner, origin=lambda _p: None)
    assert plan.install_method == "git-checkout"
    assert plan.needs_pull is True
    assert "3 new commit(s)" in plan.tool_note


def test_build_plan_vcs_spec_note(monkeypatch):
    # A non-git-checkout install whose origin is a git+ spec re-pulls the latest commit.
    monkeypatch.setattr(upmod, "detect_install_method", lambda _pkg: ("pip", None))
    plan = build_plan(NAME, "0.1.0", origin=lambda _p: "git+https://e/x.git@main")
    assert plan.needs_pull is False
    assert "re-pulls the latest commit" in plan.tool_note


def test_build_plan_fetch_none_note(monkeypatch):
    # A plain-PyPI install whose fetch returns None reports the could-not-determine note.
    monkeypatch.setattr(upmod, "detect_install_method", lambda _pkg: ("pip", None))
    plan = build_plan(NAME, "0.1.0", fetch=lambda _n: None, origin=lambda _p: None)
    assert "could not determine the latest release" in plan.tool_note


def test_build_plan_dependency_loop_uses_injected_collaborators(monkeypatch):
    # The dependency loop: one dep is installed, one raises PackageNotFoundError and
    # is skipped -> exactly one DependencyStatus carrying the injected fetch's latest.
    monkeypatch.setattr(upmod, "detect_install_method", lambda _pkg: ("pip", None))
    monkeypatch.setattr(upmod, "direct_dependencies", lambda _pkg: ["click", "ghost"])

    def _installed(name):
        if name == "ghost":
            raise upmod.metadata.PackageNotFoundError(name)
        return "8.1.0"

    plan = build_plan(
        NAME,
        "0.1.0",
        fetch=lambda name: "9.0.0" if name != NAME else None,
        installed_version_of=_installed,
        origin=lambda _p: None,
    )
    assert len(plan.dependencies) == 1
    dep = plan.dependencies[0]
    assert isinstance(dep, DependencyStatus)
    assert (dep.name, dep.installed, dep.latest, dep.kind) == ("click", "8.1.0", "9.0.0", "major")
