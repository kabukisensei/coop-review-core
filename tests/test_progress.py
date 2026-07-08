"""Scan-progress display (issue #6 — progress.py had no test file).

Contract: stderr-only + opt-in. It shows only for a human watching (not quiet,
stderr a TTY); everywhere else every method is a cheap no-op that writes nothing
to stdout, so a redirected/piped report and the deterministic output stay clean.
"""

from coop_review_core.progress import _NOOP, Progress, should_enable


class _FakeStderr:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_should_enable_is_false_when_quiet(monkeypatch):
    monkeypatch.setattr("sys.stderr", _FakeStderr(True))  # even with a TTY…
    assert should_enable(quiet=True) is False  # …quiet wins


def test_should_enable_follows_the_stderr_tty(monkeypatch):
    monkeypatch.setattr("sys.stderr", _FakeStderr(True))
    assert should_enable(quiet=False) is True
    monkeypatch.setattr("sys.stderr", _FakeStderr(False))
    assert should_enable(quiet=False) is False


def test_should_enable_survives_a_broken_stderr(monkeypatch):
    class Broken:
        def isatty(self):
            raise ValueError("stream closed")

    monkeypatch.setattr("sys.stderr", Broken())
    assert should_enable(quiet=False) is False  # never propagate the error


def test_disabled_progress_writes_nothing(capsys):
    p = Progress(enabled=False)
    p.line("scanning…")
    with p.bar("parse", 5) as tick:
        tick("a/file.sql")  # optional label accepted and ignored
        tick()  # and callable with no args, too
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_enabled_line_goes_to_stderr_only(capsys):
    Progress(enabled=True).line("scanning 42 files")
    out = capsys.readouterr()
    assert "scanning 42 files" in out.err
    assert out.out == ""  # never stdout — the report lives there


def test_enabled_bar_ticks_without_error_and_never_touches_stdout(capsys):
    p = Progress(enabled=True)
    with p.bar("parse", 3) as tick:
        for _ in range(3):
            tick("some/file.sql")  # label ignored; no crash
    assert capsys.readouterr().out == ""


def test_enabled_empty_phase_is_a_noop(capsys):
    p = Progress(enabled=True)
    with p.bar("parse", 0) as tick:  # total <= 0 -> no bar
        assert tick is _NOOP
        tick("ignored")
    assert capsys.readouterr().out == ""
