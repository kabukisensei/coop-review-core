"""coop-review-core: shared infrastructure for the coop-*-review standards linters.

Tool-agnostic building blocks each linter parameterizes with its own package name,
tool name, and standards file:

- :mod:`coop_review_core.progress`     — stderr, TTY-gated scan progress.
- :mod:`coop_review_core.diagnostics`  — the Diagnostic model + category constants.
- :mod:`coop_review_core.severity`     — severity ordering + the finding fingerprint.
- :mod:`coop_review_core.suppressions` — inline ``<tool>:ignore`` directives + a baseline.
- :mod:`coop_review_core.upgrade`      — self-update planning (the only networked part).
- :mod:`coop_review_core.config`       — the rules.yml config layer + standards resolution.

Each linter keeps its own parsers, rules, Finding/Result model, and standards.md.
"""

__version__ = "0.1.0"
