# AGENTS.md

Canonical guide for autonomous agents working in this repo. `CLAUDE.md` only
imports this file; keep this one authoritative.

## Purpose

`coop-review-core` is the shared engine for the **`coop-*-review`** family of
offline, advisory standards linters —
[`coop-sql-review`](https://github.com/kabukisensei/coop-sql-review),
[`coop-dax-review`](https://github.com/kabukisensei/coop-dax-review), and future
siblings. It holds the tool-agnostic building blocks so an infrastructure fix
lands once instead of drifting between copies. It is a **library only**: no CLI,
no entry points, no parsers, no rules, no standards document — those stay in
each linter.

Hard properties to preserve:

- Deterministic and offline everywhere except `upgrade.py` (the only module
  allowed to touch the network).
- Advisory: nothing here ever blocks a build.
- Runtime dependencies are exactly `PyYAML>=6.0` and `click>=8.1`. Python
  `>=3.10` — write 3.10-compatible syntax even though local venvs run newer
  interpreters (ruff enforces `target-version = "py310"`).

## Layout

| Path | What it is |
|---|---|
| `src/coop_review_core/` | the package (seven files; module map below) |
| `tests/` | pytest suite; `conftest.py` prepends `src/` to `sys.path` so tests run uninstalled |
| `.github/workflows/ci.yml` | on push to `main` / PR: ruff lint + format check, pytest on Python 3.10–3.13 × ubuntu/windows |
| `.github/workflows/publish.yml` | tag-triggered: gate → build → PyPI → GitHub Release |
| `Makefile` | `setup` / `test` / `lint` / `build` / `release-check` |
| `.venv/`, `test_env/`, `dist/`, `.*_cache/` | local artifacts, all gitignored — never source |

`test_env/` (when present) is an **ephemeral scratch venv** left over from local
release testing. It is not source; delete or recreate it freely and never
commit it.

## Module map (`src/coop_review_core/`)

| Module | Responsibility |
|---|---|
| `__init__.py` | package docstring + `__version__` — the single version source (see Release). |
| `progress.py` | stderr-only, TTY-gated scan progress (`Progress`, `should_enable`, `Tick`); a cheap no-op when quiet, piped, or in CI. |
| `diagnostics.py` | the `Diagnostic` model + category constants for *processing* problems (parse failures, rule crashes, stale baseline/ignore entries) so nothing fails silently. |
| `severity.py` | severity ordering (`SEVERITIES`, `severity_rank`, `at_or_above`) + `fingerprint(*parts)` — the stable, line-independent 12-hex-char finding id. |
| `suppressions.py` | inline `<tool>:ignore` directives (`scan_directives`, `is_inline_suppressed`; fail-closed on malformed rule ids) + the JSON fingerprint baseline (`write_baseline`, `load_baseline`). |
| `upgrade.py` | self-update planning/applying (`build_plan`, `upgrade_command`, `apply_plan`). The ONLY networked module (PyPI JSON, `git fetch`); network/subprocess collaborators are injectable so tests stay offline. |
| `config.py` | the rules.yml layer (`RuleConfig`, `apply_config`, the `ignore:` finding list + its `add_ignores` writer) and standards resolution (`resolve_standards_path`, `standards_info`, `StandardsError`). |

`tests/` roughly mirrors the modules (`test_config.py`, `test_diagnostics.py`,
`test_ignores.py`, `test_severity.py`, `test_suppressions.py`, `test_upgrade.py`) —
not one-to-one: `progress.py` has no dedicated test file, and `test_ignores.py`
covers `config.py`'s `ignore:` list rather than a module named `ignores`.

## Parameterization contract — what a downstream linter supplies

Core is tool-agnostic; every tool-specific value is a parameter. Verified
against both current linters:

| The linter supplies | Consumed by |
|---|---|
| its **tool name** (e.g. `"coop-sql-review"` — the inline-directive marker and baseline tag) | `scan_directives(text, tool)`, `write_baseline(path, fingerprints, tool)`, `baseline_payload(fingerprints, tool)` |
| its **package name + running `__version__`** | `build_plan(package_name, current_version, ...)` |
| its **bundled standards path** (a `Path` to its own `data/standards.md`) | `resolve_standards_path(explicit, bundled)` |
| its own **`Rule` dataclass** — any dataclass carrying `id`, `severity`, `default_enabled`, `params` fields | `apply_config(rules, config)` (copies via `dataclasses.replace`, so extra fields like `title` / `check` are fine) |
| the stable **identity parts** of each finding — e.g. `(rule_id, object, message)`; never line number or severity | `fingerprint(*parts)` |

The linter keeps its own parsers, rules, `Finding`/`Result` model, report/CLI,
and `standards.md`.

Established consumption pattern (copy it when bootstrapping a new sibling): a
thin, same-named shim module per core module that bakes in the constants and
re-exports the rest. In `coop-sql-review`: `suppressions.py` sets
`TOOL = "coop-sql-review"` and wraps `scan_directives`/`write_baseline`;
`standards.py` pins `BUNDLED_STANDARDS`; `upgrade.py` pins `PACKAGE_NAME` and
forwards `__version__`; `progress.py`/`diagnostics.py` are pure re-exports.

Do-not-break list (public contract; both linters and users' on-disk config
files depend on these — breaking any of them is NOT a minor release):

- the `id` / `severity` / `default_enabled` / `params` field names `apply_config` reads;
- the `fingerprint` algorithm and 12-char length — a change invalidates every user's baseline and rules.yml `ignore:` list;
- the directive grammar `<tool>:ignore [RULE-IDS | *] [reason: ...]` and its fail-closed behavior;
- the baseline JSON shape `{"tool": ..., "fingerprints": [...]}`;
- the rules.yml schema (`rules:` map with `enabled` / `severity` / `params`; top-level `ignore:` list).

## Runbook

All commands from the repo root. The `Makefile` wraps the canonical commands
(POSIX; on Windows run the underlying commands with `.venv\Scripts\python`
instead of `.venv/bin/python`).

### Set up

```sh
make setup
```

Expected: pip install succeeds; the last line prints `coop-review-core <version>`.
Verify: `.venv/bin/python -m pip show coop-review-core | grep Editable` prints
`Editable project location: <this repo>`.

### Test and lint (run after every change)

```sh
make test
```

Expected: every test passes — `61 passed` as of 0.2.0 (the count grows; any
failure means stop and fix before anything else).

```sh
make lint
```

Expected: `All checks passed!` then `<N> files already formatted`. On format
drift run `.venv/bin/ruff format .` and re-run `make lint`.

### Build (mirrors publish.yml's build step)

```sh
make build
```

Expected: `dist/` holds exactly two files —
`coop_review_core-<version>.tar.gz` and `coop_review_core-<version>-py3-none-any.whl` —
where `<version>` equals `__version__`.

### Test the linters against local core edits (PYTHONPATH shadow)

The consumer venvs (`~/Developer/coop-sql-review`, `~/Developer/coop-dax-review`)
hold a **non-editable installed copy** of the last released core, so local edits
here are invisible to them until core is re-published and reinstalled. To run a
consumer's tests or CLI against your local, unpublished core — from the
consumer repo:

```sh
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python -m pytest -q
# CLI variant:  ...same PYTHONPATH... .venv/bin/python -m coop_sql_review check <path>
```

Verify the shadow took BEFORE trusting any result:

```sh
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python \
  -c "import coop_review_core; print(coop_review_core.__file__)"
```

Expected: a path under `.../coop-review-core/src/`, NOT the consumer's
`site-packages`.

Never pip-install the local core checkout into a consumer's venv to test — it
strands that venv off the released version and breaks the consumer's bare
`pytest` later. If it happened, restore with
`.venv/bin/python -m pip install -U coop-review-core`.

## Version + release discipline

- `__version__` in `src/coop_review_core/__init__.py` is the **only** place the
  version lives. `pyproject.toml` declares `dynamic = ["version"]` and
  `[tool.hatch.version] path = "src/coop_review_core/__init__.py"`, so hatchling
  reads it at build time. Never add `version =` under `[project]`; never write
  the version anywhere else.
- A release is a `vX.Y.Z` tag push. `publish.yml` then runs: (1) the gate —
  extract `__version__` and hard-fail unless the tag matches it exactly;
  (2) build sdist+wheel and smoke-test the wheel in a fresh venv; (3) publish to
  PyPI via trusted publishing (GitHub OIDC through the `pypi` environment — no
  PyPI token exists anywhere); (4) create the GitHub Release with generated notes.

Release steps, in order:

1. Bump `__version__` — one line, one file.
2. `make release-check` — expect `OK: version X.Y.Z is release-ready`.
   `FAIL: tag vX.Y.Z already exists` means the bump was forgotten.
3. Commit and push the bump (only when the human asked for a release).
4. `git tag vX.Y.Z && git push origin vX.Y.Z` — the tag push IS the publish
   trigger.
5. Verify: the `Publish to PyPI` workflow run succeeds and
   `pip index versions coop-review-core` (or the PyPI page) lists X.Y.Z.
6. Downstream: refresh each consumer venv
   (`.venv/bin/python -m pip install -U coop-review-core`), then release the
   tools — their pyprojects pin `coop-review-core>=<version>`, so the order
   across the suite is always core first.

TODO(aaron): confirm whether the `coop release` helper in coop-agent should
drive this repo's releases too.

## Never do

- Never create or push a `v*` tag unless explicitly instructed — the tag push
  publishes to PyPI immediately.
- Never move, delete, or reuse an existing `v*` tag; PyPI refuses re-uploads of
  a version. A botched release means a new patch version.
- Never bump the version anywhere except `src/coop_review_core/__init__.py`.
- Never add network access outside `upgrade.py`.
- Never add a runtime dependency casually — the linters inherit every one.
- Never use Python syntax newer than 3.10 (`requires-python = ">=3.10"`).
- Never commit `dist/`, `.venv/`, `test_env/`, or cache dirs (all gitignored).
- Never break an item on the do-not-break list in a minor release.
