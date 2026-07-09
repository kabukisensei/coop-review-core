"""Shared CLI helpers for the coop-*-review linters (issue #10).

The same-named helpers both linters carried privately — and had already started
drifting (the ``--save-ignores`` shadow-file fix landed in one twin only) — live
here ONCE. Everything is a thin, tool-parameterized edge utility: display paths,
TTY/color detection, the extra-report sinks, the config write-back rule, the
``syntax_errors`` policy, the UTF-8 console shim, and the shared ``upgrade`` /
``update`` command body. Anything importing a tool's own models (questionary
pickers, finding labels) stays tool-side.

click is already a core runtime dependency; this module adds none. The
:mod:`coop_review_core.upgrade` module (the only networked one) is imported
LAZILY inside :func:`run_upgrade`, so a linter's ``check`` path that imports
this module keeps its offline guarantee.
"""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import click

from coop_review_core.diagnostics import SYNTAX_ERROR, Diagnostic
from coop_review_core.suppressions import is_syntax_ignored, scan_syntax_ignores

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps upgrade.py lazily imported
    from coop_review_core.upgrade import UpgradePlan

__all__ = [
    "display_path",
    "stdio_interactive",
    "use_color",
    "config_write_path",
    "apply_syntax_error_policy",
    "write_extra_report",
    "should_open_report",
    "force_utf8_console",
    "run_upgrade",
    "UPGRADE_OPTIONS",
    "with_upgrade_options",
]


def display_path(path: Path) -> str:
    """POSIX-style path, relative to cwd when possible (deterministic, OS-stable)."""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def stdio_interactive() -> bool:
    """True when BOTH stdin and stdout are interactive TTYs (a human at a terminal)."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def use_color(color_flag: bool | None, output_path: str | None) -> bool:
    """Whether to colorize the terminal report. An explicit ``--color`` /
    ``--no-color`` wins; otherwise auto: color only when writing to an
    interactive stdout (never to a file) and ``NO_COLOR`` is unset."""
    if color_flag is not None:
        return color_flag
    if output_path or os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def config_write_path(config_path: str | None, cfg_path: Path, *, package_dir: Path) -> Path:
    """Where to WRITE ignores: ``--config`` if given; else the config THIS run
    actually read from (``cfg_path``) when it exists — so ``--save-ignores``
    appends to the file that configured the run (e.g. a standards-side
    ``rules.yml``) instead of a brand-new ``./rules.yml`` that would silently
    SHADOW it on the next run. Never write inside the installed package
    (``package_dir`` — the tool passes its own package directory, where the
    bundled-standards sibling lives); fall back to ``./rules.yml`` there, and
    when no config file exists.

    This is the FIXED coop-sql-review variant; coop-dax-review's private copy
    still unconditionally wrote ``./rules.yml`` and picks up the fix on adoption.
    """
    if config_path:
        return Path(config_path)
    if cfg_path.is_file() and not cfg_path.resolve().is_relative_to(Path(package_dir).resolve()):
        return cfg_path
    return Path.cwd() / "rules.yml"


def apply_syntax_error_policy(
    diagnostics: list[Diagnostic], mode: str, texts: Mapping[str, str], tool: str
) -> list[Diagnostic]:
    """Apply the ``syntax_errors`` knob + inline ``<tool>:ignore syntax`` to
    SYNTAX_ERROR diagnostics, leaving every other diagnostic untouched.

    - ``off``: drop all syntax-error diagnostics.
    - inline ``<tool>:ignore syntax`` on the error's line / the line above:
      drop that one (regardless of the knob).
    - ``warning``: demote the rest to ``warning`` (still reported).
    - ``error`` (default): keep as-is.

    ``texts`` is the ``{display_path: raw_text}`` map filled during parsing, so
    an inline directive is found at the exact line numbers the diagnostics carry.
    """
    if mode == "error" and not any(d.category == SYNTAX_ERROR for d in diagnostics):
        return diagnostics  # fast path: nothing to do
    ignores = {file: scan_syntax_ignores(text, tool) for file, text in texts.items()}
    kept: list[Diagnostic] = []
    for diag in diagnostics:
        if diag.category != SYNTAX_ERROR:
            kept.append(diag)
            continue
        if mode == "off" or is_syntax_ignored(diag.line, ignores.get(diag.file, set())):
            continue
        if mode == "warning" and diag.severity != "warning":
            diag = replace(diag, severity="warning")
        kept.append(diag)
    return kept


def write_extra_report(path: str, content: str, label: str) -> None:
    """Write an extra report file (in addition to the main output) and announce
    its path on stderr. Never opens a browser — these are scriptable sinks.
    An unwritable sink is a one-line :class:`click.ClickException` (exit 1)."""
    target = Path(path)
    try:
        target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise click.ClickException(f"could not write report to {path}: {exc}") from exc
    click.echo(f"{label} report written to {target.resolve().as_posix()}", err=True)


def should_open_report(fmt: str, open_report: bool | None) -> bool:
    """Whether to open the just-written report in a browser.

    Only ever applies to the HTML report (the only browser-viewable format).
    An explicit ``--open``/``--no-open`` overrides the default; otherwise we
    auto-open only in an interactive terminal — so an agent or CI run, which
    just reads the file we name, never triggers a browser pop-up.
    """
    if fmt != "html":
        return False
    if open_report is not None:
        return open_report
    return stdio_interactive()


def force_utf8_console() -> None:
    """Emit UTF-8 on every platform so non-ASCII in messages (the § section
    marks, em-dashes) never raise UnicodeEncodeError on a legacy Windows
    console (cp1252/cp437). errors='replace' guarantees we never crash on
    output; worst case an old console shows a replacement glyph."""
    for stream in (sys.stdout, sys.stderr):
        try:
            # newline="" disables write-time \n -> \r\n translation, so the JSON
            # contract (and the text report) stay byte-identical (LF) across OSes
            # even when redirected to a file on Windows.
            stream.reconfigure(encoding="utf-8", errors="replace", newline="")
        except (AttributeError, ValueError, OSError):
            pass  # not a reconfigurable text stream (e.g. under test capture)


def run_upgrade(check_only: bool, *, tool_name: str, plan: UpgradePlan) -> None:
    """The shared body behind a linter's ``upgrade`` / ``update`` commands.

    Reports the tool + dependency freshness from an already-built ``plan``
    (the tool's own ``build_plan()`` — the only networked call — stays
    tool-side), then prints the exact command(s) to run. It never applies the
    upgrade itself: a running program can't reliably replace its own files
    (on Windows its console-script .exe is locked), so the user runs the
    printed command in a fresh terminal. ``check_only`` stops after the
    freshness report. Commands are rendered with :func:`shlex.join`, so a
    path with spaces stays copy-pasteable.
    """
    from coop_review_core.upgrade import upgrade_command  # lazy: keep check paths import-clean

    click.echo(f"{tool_name} {plan.tool_installed} ({plan.install_method}) — {plan.tool_note}")
    if plan.dependencies:
        click.echo("\nDependencies:")
        for dep in plan.dependencies:
            latest = dep.latest or "?"
            label = {
                "current": "up to date",
                "safe": f"update available -> {latest}",
                "major": f"MAJOR update available -> {latest} (review before applying)",
                "unknown": "could not check (offline?)",
            }[dep.kind]
            click.echo(f"  {dep.name:20} {dep.installed:12} {label}")
    if check_only:
        return
    click.echo(f"\nThis tool does not update itself. To update, exit {tool_name} and run:\n")
    for command in upgrade_command(plan):
        click.echo(f"    {shlex.join(command)}")


# The shared option set for `upgrade` / `update`. Each application of the
# decorator instantiates a fresh click Option, so one list serves any number of
# commands (exactly how the twins already share theirs).
UPGRADE_OPTIONS = [
    click.option(
        "--check",
        "check_only",
        is_flag=True,
        help="Only report whether an update is available; don't print the upgrade command.",
    ),
]


def with_upgrade_options(func):
    """Apply :data:`UPGRADE_OPTIONS` to a command function (order-preserving)."""
    for option in reversed(UPGRADE_OPTIONS):
        func = option(func)
    return func
