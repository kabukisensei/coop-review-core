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
| `coop_review_core.upgrade` | Self-update planning — the only networked part (`build_plan`, `upgrade_command`). |
| `coop_review_core.config` | The `rules.yml` config layer with unified discovery (`RuleConfig`, `apply_config`, `discover_config`) + standards resolution (`resolve_standards_path`, `standards_info`). |
| `coop_review_core.cliutils` | Shared CLI helpers (`display_path`, `config_write_path`, `write_extra_report`, `run_upgrade` + `with_upgrade_options`). |
| `coop_review_core.report` | Shared report chrome — console badges/ANSI + the branded HTML style — plus the machine-JSON envelope, the SARIF 2.1.0 emitter (`to_sarif`), the JUnit XML emitter (`to_junit`, for Azure DevOps), and the single bundled Cooptimize logo (`logo_data_uri`). |
| `coop_review_core.delta` | Run-to-run envelope comparison (`diff_envelopes` → `EnvelopeDelta`: new / fixed / persisting, keyed on each finding's `fingerprint`) with `delta_text` / `delta_markdown` renderers — "what changed since last review?". |
| `coop_review_core.errors` | `CoopReviewError`, the common base of every user-facing error core raises. |

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
make setup   # python3 -m venv .venv && pip install -e ".[dev]"
make test    # .venv/bin/pytest -q
make lint    # .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

(No `make`? Each target is a one-liner — see the `Makefile`.) Use Python 3.10–3.13 for the venv
— 3.14 doesn't process the editable install's `.pth`. If `python3` is 3.14+, create the venv
explicitly: `python3.13 -m venv .venv`.

### Testing core changes against the linters

The consumer repos (`coop-sql-review`, `coop-dax-review`, assumed cloned side by side with this
one under a single parent directory — substitute your parent for `$HOME/Developer` below) hold a
**non-editable installed copy**
of core in their `.venv`s, so an edit here is invisible to them until core is re-published and
reinstalled. To run a consumer's tests (or CLI) against your local, unpublished core, shadow its
installed copy — from the consumer repo:

```sh
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python -m pytest -q
```

`PYTHONPATH` beats `site-packages`, so the first entry shadows the installed core with this repo's
`src`; `$PWD/src` keeps the consumer's own package importable next to it. Confirm the shadow took
with `... -c "import coop_review_core; print(coop_review_core.__file__)"` — it must print a path
under this repo, not the consumer's `site-packages`.

Release = bump `__version__` in `src/coop_review_core/__init__.py` (the single source — `pyproject`
derives it), run `make release-check`, then tag `vX.Y.Z`; `publish.yml` refuses a tag that doesn't
match `__version__`, builds, publishes to PyPI via trusted publishing, and cuts a GitHub Release.
The tag push **is** the publish — releases happen only on an explicit request naming the version
(agents: see `AGENTS.md`, "Version + release discipline").
