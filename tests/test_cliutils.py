"""The shared CLI helper layer (issue #10)."""

from pathlib import Path

import click
import pytest

from coop_review_core.cliutils import (
    apply_syntax_error_policy,
    config_write_path,
    display_path,
    force_utf8_console,
    run_upgrade,
    should_open_report,
    stdio_interactive,
    use_color,
    with_upgrade_options,
    write_extra_report,
)
from coop_review_core.diagnostics import SYNTAX_ERROR, Diagnostic
from coop_review_core.upgrade import DependencyStatus, UpgradePlan

TOOL = "coop-sql-review"


class _NoTty:
    """A stream whose isatty raises (e.g. a closed/captured stream)."""

    def isatty(self):
        raise ValueError("closed")


class _Tty:
    def isatty(self):
        return True


# --- display_path ---------------------------------------------------------------


def test_display_path_relative_inside_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inner = tmp_path / "sub" / "a.sql"
    assert display_path(inner) == "sub/a.sql"  # POSIX separators on every OS


def test_display_path_absolute_outside_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "." if (tmp_path / ".").exists() else tmp_path)
    outside = Path("/somewhere/else/a.sql")
    assert display_path(outside) == outside.resolve().as_posix()


# --- TTY / color detection ---------------------------------------------------------


def test_stdio_interactive_true_only_when_both_are_ttys(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("sys.stdout", _Tty())
    assert stdio_interactive() is True
    monkeypatch.setattr("sys.stdout", _NoTty())
    assert stdio_interactive() is False  # isatty raising -> False, never a crash


def test_use_color_explicit_flag_always_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(True, "out.txt") is True
    assert use_color(False, None) is False


def test_use_color_auto_never_to_a_file_and_honors_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stdout", _Tty())
    assert use_color(None, "report.txt") is False  # writing to a file
    assert use_color(None, None) is True  # interactive stdout
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(None, None) is False


# --- config_write_path (the fixed sql-review variant) --------------------------------


def test_config_write_path_explicit_config_wins(tmp_path):
    pkg = tmp_path / "pkg"
    got = config_write_path("team-rules.yml", tmp_path / "rules.yml", package_dir=pkg)
    assert got == Path("team-rules.yml")


def test_config_write_path_writes_back_to_the_config_actually_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    read_cfg = tmp_path / "standards" / "rules.yml"
    read_cfg.parent.mkdir()
    read_cfg.write_text("rules: {}\n", encoding="utf-8")
    # The run read a real config outside the package -> write back to IT, so the
    # ignore does not land in a brand-new ./rules.yml that would shadow it.
    assert config_write_path(None, read_cfg, package_dir=pkg) == read_cfg


def test_config_write_path_never_writes_inside_the_installed_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "site-packages" / "coop_x_review"
    bundled_cfg = pkg / "data" / "rules.yml"
    bundled_cfg.parent.mkdir(parents=True)
    bundled_cfg.write_text("rules: {}\n", encoding="utf-8")
    got = config_write_path(None, bundled_cfg, package_dir=pkg)
    assert got == tmp_path / "rules.yml"
    assert not got.resolve().is_relative_to(pkg.resolve())


def test_config_write_path_missing_config_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = config_write_path(None, tmp_path / "nope.yml", package_dir=tmp_path / "pkg")
    assert got == tmp_path / "rules.yml"


# --- apply_syntax_error_policy ---------------------------------------------------------


def _syntax_diag(file="a.sql", line=2, severity="error"):
    return Diagnostic(severity=severity, category=SYNTAX_ERROR, file=file, line=line, message="broken")


def _other_diag():
    return Diagnostic(severity="warning", category="parse_degraded", file="a.sql", line=0, message="meh")


def test_policy_error_mode_keeps_everything():
    diags = [_syntax_diag(), _other_diag()]
    assert apply_syntax_error_policy(diags, "error", {"a.sql": "SELECT"}, TOOL) == diags


def test_policy_error_mode_fast_path_returns_same_list_object():
    diags = [_other_diag()]
    assert apply_syntax_error_policy(diags, "error", {}, TOOL) is diags


def test_policy_off_drops_only_syntax_diagnostics():
    kept = apply_syntax_error_policy([_syntax_diag(), _other_diag()], "off", {}, TOOL)
    assert kept == [_other_diag()]


def test_policy_warning_demotes_but_keeps_visible():
    kept = apply_syntax_error_policy([_syntax_diag(severity="error")], "warning", {}, TOOL)
    assert [d.severity for d in kept] == ["warning"]
    assert kept[0].category == SYNTAX_ERROR  # still reported - a gap is never silent


def test_policy_inline_ignore_syntax_drops_regardless_of_mode():
    text = "line one\n-- coop-sql-review:ignore syntax\nbroken here\n"
    # Directive on line 2; the diagnostic at line 3 (line below) and line 2 are covered.
    for mode in ("error", "warning"):
        kept = apply_syntax_error_policy(
            [_syntax_diag(line=3), _syntax_diag(file="b.sql", line=3)], mode, {"a.sql": text}, TOOL
        )
        assert [d.file for d in kept] == ["b.sql"]  # only the un-ignored file's remains


def test_policy_rule_id_only_directive_does_not_silence_syntax():
    text = "-- coop-sql-review:ignore SQL-A\nbroken\n"
    kept = apply_syntax_error_policy([_syntax_diag(line=2)], "error", {"a.sql": text}, TOOL)
    assert len(kept) == 1


# --- write_extra_report -------------------------------------------------------------------


def test_write_extra_report_writes_lf_and_announces_on_stderr(tmp_path, capsys):
    target = tmp_path / "report.html"
    write_extra_report(str(target), "<html>\n</html>\n", "HTML")
    assert target.read_bytes() == b"<html>\n</html>\n"  # LF, never CRLF
    err = capsys.readouterr().err
    assert f"HTML report written to {target.resolve().as_posix()}" in err


def test_write_extra_report_unwritable_sink_is_a_click_exception(tmp_path):
    with pytest.raises(click.ClickException):
        write_extra_report(str(tmp_path), "content", "HTML")  # a directory is unwritable


# --- should_open_report ----------------------------------------------------------------


def test_should_open_report_only_for_html(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("sys.stdout", _Tty())
    assert should_open_report("json", None) is False
    assert should_open_report("json", True) is False  # even an explicit --open
    assert should_open_report("html", None) is True  # interactive auto-open


def test_should_open_report_explicit_flag_beats_tty_detection(monkeypatch):
    monkeypatch.setattr("sys.stdin", _Tty())
    monkeypatch.setattr("sys.stdout", _Tty())
    assert should_open_report("html", False) is False
    monkeypatch.setattr("sys.stdout", _NoTty())
    assert should_open_report("html", True) is True
    assert should_open_report("html", None) is False  # non-interactive auto-suppresses


# --- force_utf8_console -----------------------------------------------------------------


def test_force_utf8_console_never_raises_under_test_capture():
    force_utf8_console()  # captured streams aren't reconfigurable; must swallow


# --- run_upgrade + options ------------------------------------------------------------------


def _plan(**overrides) -> UpgradePlan:
    kwargs = dict(
        package_name="coop-x-review",
        install_method="pip",
        checkout=None,
        tool_installed="1.0.0",
        tool_note="latest release is 1.1.0",
        dependencies=[
            DependencyStatus(name="click", installed="8.1.0", latest="8.2.0", kind="safe"),
            DependencyStatus(name="PyYAML", installed="6.0", latest=None, kind="unknown"),
        ],
    )
    kwargs.update(overrides)
    return UpgradePlan(**kwargs)


def test_run_upgrade_reports_then_prints_the_command(capsys):
    run_upgrade(False, tool_name="coop-x-review", plan=_plan())
    out = capsys.readouterr().out
    assert "coop-x-review 1.0.0 (pip) — latest release is 1.1.0" in out
    assert "update available -> 8.2.0" in out
    assert "could not check (offline?)" in out
    assert "exit coop-x-review and run:" in out
    assert "    python -m pip install -U coop-x-review" in out


def test_run_upgrade_check_only_stops_before_the_command(capsys):
    run_upgrade(True, tool_name="coop-x-review", plan=_plan())
    out = capsys.readouterr().out
    assert "coop-x-review 1.0.0" in out
    assert "pip install" not in out


def test_run_upgrade_shlex_quotes_paths_with_spaces(capsys):
    plan = _plan(install_method="git-checkout", checkout=Path("/tmp/my checkout"), needs_pull=False)
    run_upgrade(False, tool_name="coop-x-review", plan=plan)
    out = capsys.readouterr().out
    assert "python -m pip install -U '/tmp/my checkout'" in out  # shlex.join keeps it pasteable


def test_with_upgrade_options_adds_the_check_flag_per_command():
    @click.command()
    @with_upgrade_options
    def one(check_only):
        pass

    @click.command()
    @with_upgrade_options
    def two(check_only):
        pass

    for cmd in (one, two):
        (param,) = [p for p in cmd.params if p.name == "check_only"]
        assert param.is_flag
    # Fresh Option instances per application - the shared list is safe to reuse.
    assert one.params[0] is not two.params[0]
