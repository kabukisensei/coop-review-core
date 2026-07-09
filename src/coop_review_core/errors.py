"""The common base for every user-facing error this library raises.

``except CoopReviewError:`` catches any core-originated, user-facing failure
(:class:`~coop_review_core.config.StandardsError`,
:class:`~coop_review_core.suppressions.BaselineError`,
:class:`~coop_review_core.upgrade.UpgradeError`, and any future sibling)
without importing each type from its module. Every subclass keeps its direct
``Exception`` ancestry, so existing ``except StandardsError:`` handlers in the
consumers are untouched. Messages are printable as-is — a consumer CLI wraps
them in its own friendly one-liner (e.g. ``click.UsageError``), never a
traceback.
"""

from __future__ import annotations

__all__ = ["CoopReviewError"]


class CoopReviewError(Exception):
    """Base class for every user-facing error raised by coop-review-core."""
