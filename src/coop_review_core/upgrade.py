"""Tool self-update and dependency freshness.

The ONE part of a linter that intentionally touches the network (PyPI metadata,
`git fetch`). A linter's `check` path never imports this module, so its offline
guarantee is untouched.

Tool-agnostic: pass the package name and the running version into
:func:`build_plan`; the resulting :class:`UpgradePlan` carries the package name
so :func:`upgrade_command` / :func:`apply_plan` need no globals. Pure logic
(classification, planning) is separated from side effects (network fetcher and
subprocess runner are injectable) so tests never need the network.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"
NETWORK_TIMEOUT_SECONDS = 10
# A pip spec from a version control system: "git+…", "hg+…", "svn+…", "bzr+…".
# Detect by scheme prefix, NOT a bare "+" substring — a local/editable path can
# legitimately contain "+" (e.g. /home/u/c++proj) and must not be mistaken for VCS.
_VCS_SPEC_RE = re.compile(r"^(git|hg|svn|bzr)\+")


def is_vcs_spec(spec: str | None) -> bool:
    """True when ``spec`` is a VCS install source (``git+https://…`` etc.)."""
    return bool(spec and _VCS_SPEC_RE.match(spec))


class UpgradeError(Exception):
    """A user-facing upgrade problem; the message is printable as-is."""


@dataclass
class DependencyStatus:
    name: str
    installed: str
    latest: str | None  # None = lookup failed
    kind: str  # "current" | "safe" | "major" | "unknown"


@dataclass
class UpgradePlan:
    package_name: str
    install_method: str  # "pipx" | "uv-tool" | "git-checkout" | "pip"
    checkout: Path | None
    tool_installed: str
    tool_note: str
    dependencies: list[DependencyStatus] = field(default_factory=list)
    pip_spec: str | None = None  # for "pip": the URL/VCS spec to reinstall from

    @property
    def safe_updates(self) -> list[DependencyStatus]:
        return [d for d in self.dependencies if d.kind == "safe"]

    @property
    def major_updates(self) -> list[DependencyStatus]:
        return [d for d in self.dependencies if d.kind == "major"]

    @property
    def is_vcs_install(self) -> bool:
        """Installed from a VCS spec (``git+…``). Such an install has no PyPI
        version to compare against — its source is a moving branch — so an
        upgrade should always re-pull rather than be skipped as 'up to date'.
        """
        return is_vcs_spec(self.pip_spec)


# -- pure helpers -------------------------------------------------------------


def _version_tuple(version: str) -> tuple[int, ...]:
    # Parse ONLY the leading numeric release segment (e.g. "1.0.0" out of
    # "1.0.0rc1"). Folding a PEP 440 pre/dev/post suffix's digits into the tuple
    # would make a pre-release sort ABOVE its final release (rc1 -> (...,1)),
    # wrongly classifying a downgrade-to-rc as a "safe" upgrade. stdlib `re` only
    # (no `packaging` dependency).
    match = re.match(r"\d+(?:\.\d+)*", version)
    return tuple(int(part) for part in match.group(0).split("."))[:4] if match else ()


def _major(version: str) -> int | None:
    match = re.match(r"\s*(\d+)", version)
    return int(match.group(1)) if match else None


def classify_update(installed: str, latest: str | None) -> str:
    """'current' | 'safe' (newer, same major) | 'major' | 'unknown'."""
    if latest is None:
        return "unknown"
    installed_major, latest_major = _major(installed), _major(latest)
    if installed_major is None or latest_major is None:
        return "unknown"
    if latest_major > installed_major:
        return "major"
    if latest_major == installed_major and _version_tuple(latest) > _version_tuple(installed):
        return "safe"
    return "current"


def direct_dependencies(package_name: str) -> list[str]:
    """Names of ``package_name``'s direct runtime dependencies (extras excluded)."""
    try:
        requirements = metadata.requires(package_name) or []
    except metadata.PackageNotFoundError:
        return []
    names: set[str] = set()
    for requirement in requirements:
        if ";" in requirement and "extra" in requirement.split(";", 1)[1]:
            continue
        match = re.match(r"[A-Za-z0-9._-]+", requirement.strip())
        if match:
            names.add(match.group(0))
    return sorted(names, key=str.lower)


def pip_install_origin(package_name: str) -> str | None:
    """The spec to reinstall from when the install came from a URL/VCS.

    pip records the original source in PEP 610 ``direct_url.json``. A bare
    ``pip install -U <name>`` would hit PyPI (where the package may not be
    published yet) and silently no-op, so for a git/url install we must reinstall
    from the recorded URL instead. Returns None for a normal PyPI install (or
    when the metadata is unavailable).
    """
    try:
        raw = metadata.distribution(package_name).read_text("direct_url.json")
    except (metadata.PackageNotFoundError, FileNotFoundError, OSError):
        return None
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except ValueError:
        return None
    url = info.get("url")
    if not url:
        return None
    if "vcs_info" in info:
        vcs = info["vcs_info"]
        ref = vcs.get("requested_revision")
        spec = f"{vcs.get('vcs', 'git')}+{url}"
        return f"{spec}@{ref}" if ref else spec  # keep the pinned branch/ref
    if info.get("dir_info", {}).get("editable"):
        return f"-e {url[len('file://') :] if url.startswith('file://') else url}"
    return url  # local directory or a direct archive URL


def detect_install_method(package_name: str) -> tuple[str, Path | None]:
    """How this interpreter's copy of ``package_name`` was installed.

    Returns (method, checkout_path); checkout_path is set only for
    "git-checkout" — a venv living inside a clone of the project.
    """
    prefix = Path(sys.prefix).resolve()
    as_posix = prefix.as_posix()
    if "/pipx/venvs/" in as_posix:
        return "pipx", None
    if "/uv/tools/" in as_posix:
        return "uv-tool", None
    needle = f'name = "{package_name}"'
    for candidate in [prefix, *prefix.parents]:
        pyproject = candidate / "pyproject.toml"
        try:
            if pyproject.is_file() and needle in pyproject.read_text(encoding="utf-8", errors="replace"):
                if (candidate / ".git").exists():
                    return "git-checkout", candidate
                return "pip", None
        except OSError:
            continue
    return "pip", None


# -- side-effecting collaborators (injectable for tests) ----------------------


def fetch_latest_version(name: str) -> str | None:
    """Latest release on PyPI, or None when unknown (404 / no network)."""
    try:
        with urllib.request.urlopen(
            PYPI_JSON_URL.format(name=name), timeout=NETWORK_TIMEOUT_SECONDS
        ) as response:
            return json.load(response)["info"]["version"]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def _run(command: list[str], runner=subprocess.run) -> subprocess.CompletedProcess:
    completed = runner(command, capture_output=True, text=True)
    if completed.returncode != 0:
        tail = "\n".join((completed.stderr or "").splitlines()[-5:])
        raise UpgradeError(f"`{' '.join(command)}` failed:\n{tail}")
    return completed


# -- planning & applying -------------------------------------------------------


def _git_checkout_note(checkout: Path, runner=subprocess.run) -> str:
    has_upstream = (
        runner(
            ["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "@{upstream}"],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    if not has_upstream:
        return (
            "running from a git checkout with no upstream remote — upgrading "
            "reinstalls from the local working tree"
        )
    fetched = runner(["git", "-C", str(checkout), "fetch", "--quiet"], capture_output=True, text=True)
    if fetched.returncode != 0:
        return "running from a git checkout; `git fetch` failed (offline?)"
    behind = runner(
        ["git", "-C", str(checkout), "rev-list", "--count", "HEAD..@{upstream}"],
        capture_output=True,
        text=True,
    )
    count = (behind.stdout or "").strip()
    if behind.returncode == 0 and count.isdigit() and int(count) > 0:
        return f"{count} new commit(s) available on the upstream branch"
    return "checkout is up to date with its upstream"


def build_plan(
    package_name: str,
    current_version: str,
    fetch=fetch_latest_version,
    runner=subprocess.run,
    installed_version_of=metadata.version,
    origin=pip_install_origin,
) -> UpgradePlan:
    """Plan an upgrade for ``package_name`` running at ``current_version``.

    Network/subprocess collaborators are injectable so this stays testable offline.
    """
    method, checkout = detect_install_method(package_name)
    pip_spec = origin(package_name) if method in ("pip", "pipx", "uv-tool") else None

    if method == "git-checkout" and checkout is not None:
        tool_note = _git_checkout_note(checkout, runner)
    elif is_vcs_spec(pip_spec):
        tool_note = f"installed from {pip_spec}; upgrading re-pulls the latest commit"
    else:
        latest = fetch(package_name)
        if latest is None:
            tool_note = "could not determine the latest release (not on PyPI yet, or offline)"
        else:
            kind = classify_update(current_version, latest)
            tool_note = (
                f"latest release is {latest}"
                if kind != "current"
                else f"already on the latest release ({latest})"
            )

    plan = UpgradePlan(
        package_name=package_name,
        install_method=method,
        checkout=checkout,
        tool_installed=current_version,
        tool_note=tool_note,
        pip_spec=pip_spec,
    )

    for name in direct_dependencies(package_name):
        try:
            installed = installed_version_of(name)
        except metadata.PackageNotFoundError:
            continue
        latest = fetch(name)
        plan.dependencies.append(
            DependencyStatus(
                name=name,
                installed=installed,
                latest=latest,
                kind=classify_update(installed, latest),
            )
        )
    return plan


def upgrade_command(plan: UpgradePlan) -> list[list[str]]:
    """The command(s) a user should run themselves to upgrade the tool.

    ``upgrade``/``update`` print these rather than executing them: a running
    program can't reliably replace its own files (on Windows its console-script
    .exe is locked), so the user runs them in a fresh terminal. Mirrors what
    ``apply_plan`` would run, but with display-friendly tokens (``python`` rather
    than this interpreter's absolute path). Most install methods need a single
    command; a git checkout may need two (pull, then reinstall).
    """
    name = plan.package_name
    if plan.install_method == "pipx":
        verb = "reinstall" if plan.is_vcs_install else "upgrade"
        return [["pipx", verb, name]]
    if plan.install_method == "uv-tool":
        if plan.is_vcs_install:
            return [["uv", "tool", "install", "--force", plan.pip_spec or name]]
        return [["uv", "tool", "upgrade", name]]
    if plan.install_method == "git-checkout" and plan.checkout is not None:
        commands: list[list[str]] = []
        # Only pull when there's something to pull: a checkout with no upstream
        # (or already up to date) would make `git pull --ff-only` error / no-op.
        if "new commit(s)" in plan.tool_note:
            commands.append(["git", "-C", str(plan.checkout), "pull", "--ff-only"])
        # Always reinstall from the checkout: for a NON-editable clone `git pull`
        # updates the source tree but not the installed package.
        commands.append(["python", "-m", "pip", "install", "-U", str(plan.checkout)])
        return commands
    if plan.pip_spec:
        spec_tokens = ["-e", plan.pip_spec[3:]] if plan.pip_spec.startswith("-e ") else [plan.pip_spec]
        return [["python", "-m", "pip", "install", "-U", "--force-reinstall", *spec_tokens]]
    return [["python", "-m", "pip", "install", "-U", name]]


def apply_plan(plan: UpgradePlan, runner=subprocess.run) -> list[list[str]]:
    """Run the upgrade: the tool first, then non-breaking dependency bumps.

    Major dependency upgrades are never applied automatically — they are
    reported so a human can review release notes first. (Linters that follow the
    "print, don't self-apply" policy use :func:`upgrade_command` instead.)
    """
    name = plan.package_name
    executed: list[list[str]] = []

    if plan.install_method == "pipx":
        # `pipx reinstall` (NOT `install --force`): re-pulls the recorded spec,
        # preserves the pinned @ref, and works under pipx's uv backend.
        command = ["pipx", "reinstall", name] if plan.is_vcs_install else ["pipx", "upgrade", name]
    elif plan.install_method == "uv-tool":
        command = (
            ["uv", "tool", "install", "--force", plan.pip_spec]
            if plan.is_vcs_install
            else ["uv", "tool", "upgrade", name]
        )
    elif plan.install_method == "git-checkout" and plan.checkout is not None:
        if "new commit(s)" in plan.tool_note:
            pull = ["git", "-C", str(plan.checkout), "pull", "--ff-only"]
            _run(pull, runner)
            executed.append(pull)
        command = [sys.executable, "-m", "pip", "install", "-q", "-U", str(plan.checkout)]
    elif plan.pip_spec:
        spec_tokens = ["-e", plan.pip_spec[3:]] if plan.pip_spec.startswith("-e ") else [plan.pip_spec]
        command = [sys.executable, "-m", "pip", "install", "-q", "-U", "--force-reinstall", *spec_tokens]
    else:
        command = [sys.executable, "-m", "pip", "install", "-q", "-U", name]
    _run(command, runner)
    executed.append(command)

    if plan.install_method in ("pip", "git-checkout") and plan.safe_updates:
        specs = [f"{dep.name}<{(_major(dep.latest) or 0) + 1}" for dep in plan.safe_updates]
        dep_command = [sys.executable, "-m", "pip", "install", "-q", "-U", *specs]
        _run(dep_command, runner)
        executed.append(dep_command)

    return executed
