# coop-review-core

Shared infrastructure for the **`coop-*-review`** family of offline, advisory standards linters
([`coop-sql-review`](https://github.com/kabukisensei/coop-sql-review),
[`coop-dax-review`](https://github.com/kabukisensei/coop-dax-review), and future siblings).

It holds the tool-agnostic building blocks that were otherwise duplicated across each linter, so an
infrastructure fix lands **once** instead of being copy-pasted (and silently drifting) between repos.
Each linter keeps its own parsers, rules, `Finding`/`Result` model, and `standards.md`; it
parameterizes the core with its own package name, tool name, and standards file.

## What's in it

| Module | What it provides |
|---|---|
| `coop_review_core.progress` | Stderr-only, TTY-gated scan progress (`Progress`, `should_enable`). |
| `coop_review_core.diagnostics` | The `Diagnostic` model + processing-problem category constants. |
| `coop_review_core.severity` | Severity ordering (`SEVERITIES`, `severity_rank`, `at_or_above`) + the stable, line-independent `fingerprint`. |
| `coop_review_core.suppressions` | Inline `<tool>:ignore` directives + a fingerprint baseline (`scan_directives`, `is_inline_suppressed`, `write_baseline`, `load_baseline`). |
| `coop_review_core.upgrade` | Self-update planning — the only networked part (`build_plan`, `upgrade_command`, `apply_plan`). |
| `coop_review_core.config` | The `rules.yml` config layer + standards resolution (`RuleConfig`, `apply_config`, `resolve_standards_path`, `standards_info`). |

Everything is **deterministic and offline** except `upgrade` (PyPI metadata / `git fetch`), and
nothing here ever blocks a build.

## How a linter uses it

```python
from coop_review_core.config import RuleConfig, apply_config, resolve_standards_path
from coop_review_core.suppressions import scan_directives, is_inline_suppressed
from coop_review_core.upgrade import build_plan, upgrade_command

std = resolve_standards_path(user_path, BUNDLED_STANDARDS)          # tool passes its own bundled copy
rules = apply_config(all_rules(), RuleConfig.load(config_path))     # works on the tool's own Rule type
directives = scan_directives(file_text, tool="coop-sql-review")     # tool passes its own marker
plan = build_plan("coop-sql-review", __version__)                  # tool passes its name + version
```

`apply_config` is *structural*: it works on any rule dataclass with `id` / `severity` /
`default_enabled` / `params` fields, so each linter keeps its own `Rule`.

## Develop

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Release = bump `__version__` in `src/coop_review_core/__init__.py` (the single source — `pyproject`
derives it), then tag `vX.Y.Z`; `publish.yml` builds, publishes to PyPI via trusted publishing, and
cuts a GitHub Release.
