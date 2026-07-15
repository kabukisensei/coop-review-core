"""coop-review-core: shared infrastructure for the coop-*-review standards linters.

Tool-agnostic building blocks each linter parameterizes with its own package name,
tool name, and standards file:

- :mod:`coop_review_core.progress`     — stderr, TTY-gated scan progress.
- :mod:`coop_review_core.diagnostics`  — the Diagnostic model + category constants.
- :mod:`coop_review_core.severity`     — severity ordering + the finding fingerprint.
- :mod:`coop_review_core.suppressions` — inline ``<tool>:ignore`` directives + a baseline.
- :mod:`coop_review_core.upgrade`      — self-update planning (the only networked part).
- :mod:`coop_review_core.config`       — the rules.yml config layer (rule toggles,
  severity/params overrides, and the human-readable ``ignore:`` finding list +
  its :func:`~coop_review_core.config.add_ignores` writer) + standards resolution.
- :mod:`coop_review_core.cliutils`     — the shared CLI helper layer.
- :mod:`coop_review_core.report`       — console/HTML report chrome, the machine-JSON
  envelope, the SARIF 2.1.0 emitter, and the single bundled logo.

- :mod:`coop_review_core.errors`       — :class:`CoopReviewError`, the common base of
  every user-facing error core raises (StandardsError, BaselineError, UpgradeError).

Each linter keeps its own parsers, rules, Finding/Result model, and standards.md.
"""

from coop_review_core.errors import CoopReviewError

__all__ = ["CoopReviewError"]

__version__ = "0.8.0"
