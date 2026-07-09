"""Scan-progress display (stderr-only, opt-in).

A thin wrapper over ``click.progressbar`` so a check over hundreds of files shows
it's working. Deliberately stderr-only: the text/JSON report goes to stdout, so
progress never pollutes a redirected report or the deterministic output. Shown
only when stderr is an interactive TTY; in CI or when piped, every method is a
cheap no-op (no control characters in logs).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import click

__all__ = ["Tick", "should_enable", "Progress"]

# A tick callback: called once per processed item. The optional argument is the
# item's label (e.g. file path), accepted and ignored so callers pass uniformly.
Tick = Callable[..., None]

_NOOP: Tick = lambda *_args, **_kwargs: None  # noqa: E731


def should_enable(quiet: bool) -> bool:
    """Progress shows only for a human watching: not quiet, stderr a TTY."""
    if quiet:
        return False
    try:
        return bool(sys.stderr.isatty())
    except (AttributeError, ValueError):
        return False


class Progress:
    """Drives a labelled progress bar / status lines on stderr when enabled."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def line(self, message: str) -> None:
        """Print a one-off status line (only when enabled)."""
        if self.enabled:
            click.echo(message, err=True)

    @contextmanager
    def bar(self, label: str, total: int) -> Iterator[Tick]:
        """Yield a tick callable for a phase of ``total`` items.

        Disabled, or an empty phase, yields a no-op and renders nothing. The
        tick accepts (and ignores) an optional label argument so callers can
        pass the current file path uniformly.
        """
        if not self.enabled or total <= 0:
            yield _NOOP
            return
        with click.progressbar(length=total, label=label, file=sys.stderr, show_eta=False) as bar:
            yield lambda *_args, **_kwargs: bar.update(1)
