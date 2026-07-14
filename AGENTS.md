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

## Environment

- Everything here runs fully headless on Linux (and macOS/Windows) — no GUI, no OS-specific
  tools, no network except `upgrade.py`'s own code paths.
- Python: create the venv with **Python 3.13** (any of 3.10–3.13 works; **3.14 breaks editable
  installs** — its venvs don't process the `.pth`, so imports fail). `make setup` uses whatever
  `python3` resolves to; if `python3 --version` prints 3.14+, rebuild the venv explicitly:
  `rm -rf .venv && python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- Before starting any work: `git fetch && git pull --ff-only`. If the pull fails, or
  `git status --porcelain` prints changes you didn't make yourself, **stop and report** — never
  stash, reset, or commit around them (another agent or human may share this tree).
- Secrets: **none in this repo and none needed** — publishing uses GitHub OIDC trusted
  publishing (no PyPI token exists anywhere), and the library itself is offline.

## Layout

| Path | What it is |
|---|---|
| `src/coop_review_core/` | the package (module map below) |
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
| `__init__.py` | package docstring + `__version__` — the single version source (see Release) — and the `CoopReviewError` re-export. |
| `errors.py` | `CoopReviewError`, the common base of every user-facing error core raises (`StandardsError`, `BaselineError`, `UpgradeError` all subclass it). |
| `progress.py` | stderr-only, TTY-gated scan progress (`Progress`, `should_enable`, `Tick`); a cheap no-op when quiet, piped, or in CI. |
| `diagnostics.py` | the `Diagnostic` model + category constants for *processing* problems (parse failures, rule crashes, stale baseline/ignore entries) so nothing fails silently. |
| `severity.py` | severity ordering (`SEVERITIES`, `severity_rank`, `at_or_above`) + `fingerprint(*parts)` — the stable, line-independent 12-hex-char finding id. |
| `suppressions.py` | inline `<tool>:ignore` directives (`scan_directives`, `is_inline_suppressed`; fail-closed on malformed rule ids) + the JSON fingerprint baseline (`write_baseline`, `load_baseline`). |
| `upgrade.py` | self-update planning (`build_plan`, `upgrade_command`). The ONLY networked module (PyPI JSON, `git fetch`); network/subprocess collaborators are injectable so tests stay offline. |
| `config.py` | the rules.yml layer (`RuleConfig`, `apply_config`, the `ignore:` finding list + its `add_ignores` writer) and standards resolution (`resolve_standards_path`, `standards_info`, `StandardsError`). |
| `cliutils.py` | the shared CLI helper layer (issue #10): `display_path`, `stdio_interactive`, `use_color`, `config_write_path` (the write-back-to-what-was-read rule; never inside the package), `apply_syntax_error_policy`, `write_extra_report`, `should_open_report`, `force_utf8_console`, `run_upgrade` + `with_upgrade_options`. Imports `upgrade.py` lazily, so a linter's `check` path stays offline-import-clean. |
| `report.py` | the shared report layer (issue #9): console chrome (`BADGE`/`BADGE_COLOR`/`ANSI`/`sty`), the branded `HTML_STYLE` + `logo_data_uri` (the ONE bundled `data/cooptimize-logo.png`), `esc`/`chip`, and the machine-JSON envelope (`verdict`, `build_envelope`, `envelope_text`, `diagnostic_json`, `log_text`). Renders from plain data — never a tool's `Result`. |
| `data/` | package data shipped in the wheel: `cooptimize-logo.png` (the family's single logo copy). |

`tests/` roughly mirrors the modules (`test_cliutils.py`, `test_config.py`,
`test_diagnostics.py`, `test_discover_config.py`, `test_ignores.py`,
`test_progress.py`, `test_report.py`, `test_severity.py`, `test_suppressions.py`,
`test_upgrade.py`) — but not one-to-one: `test_ignores.py` and
`test_discover_config.py` both cover parts of `config.py` (the `ignore:` list and
config discovery) rather than modules of those names, and `test_api_surface.py`
audits `__all__` / the do-not-break surface across the package rather than a
single module.

## Parameterization contract — what a downstream linter supplies

Core is tool-agnostic; every tool-specific value is a parameter. Verified
against both current linters:

| The linter supplies | Consumed by |
|---|---|
| its **tool name** (e.g. `"coop-sql-review"` — the inline-directive marker and baseline tag; the config filename `<tool>.yml` and env var `COOP_<TOOL>_CONFIG` are DERIVED from this same value via `tool_config_filename` / `config_env_var`) | `scan_directives(text, tool)`, `write_baseline(path, fingerprints, tool)`, `baseline_payload(fingerprints, tool)`, `discover_config(tool, explicit=, env=, start=, bundled_default=)` |
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
- the rules.yml schema (`rules:` map with `enabled` / `severity` / `params`; top-level `ignore:` list);
- `CoopReviewError` as the common base of `StandardsError` / `BaselineError` / `UpgradeError`
  (consumers may catch it as "any core failure" — re-parenting any of the three off it is a break);
- the family-wide **exit-code contract** (0 advisory / 1 friendly tool failure / 2 usage +
  `--strict` / 130 interrupt — the table in "Exit-code contract" below).

**Pin / deprecation policy** (issue #8; `__all__` in every module mirrors the public surface —
anything underscore-prefixed or absent from `__all__` is private and may change without notice):

- Core **never removes or breaks a public name that a shipped consumer wheel imports at module
  load** while uncapped `>=` pins on it exist — removing such a name would break every
  already-installed consumer wheel on its next `pip install -U coop-review-core`. Removal
  requires a **breaking** core release AND a released generation of every consumer that no
  longer imports the name, behind a cap that excludes the removing release; until then a
  deprecated name stays importable. `apply_plan` was the standing example: dead once both
  linters went print-only (`upgrade_command`), removed for 0.5.0 (issue #5) — safe because
  the shipped generations pin `>=0.4,<0.5`, and each linter drops its re-import before
  raising that cap.
- Consumers SHOULD additionally cap their pin going forward (`coop-review-core>=0.4,<0.5`) and
  bump the cap with each core release — belt-and-braces on top of the core-side rule, and it
  matches the documented core-first release train.

## Exit-code contract (family-wide)

Every `coop-*-review` CLI implements the same exit-code discipline (verified against both
shipped linters' `cli.py`; core has no CLI, so this section is the canonical statement the tool
repos reference instead of restating). **This table is part of the do-not-break list** —
consumers' CI wrappers and agent harnesses route on these values:

| Exit | Meaning |
|---|---|
| 0 | Success. Advisory by default — findings do NOT change the exit code unless the caller opts in with `--strict`. |
| 1 | Tool failure surfaced as a friendly one-line `ClickException` — e.g. an unwritable output sink (`-o`, `--html`/`--md`/`--sarif`, `--log-file`, `--write-baseline`) or an unreadable standards file. Never a traceback. |
| 2 | Usage error (bad flags, missing explicit `--config`, malformed rules.yml/baseline) — and the `--strict` trip: findings remain after the `--min-severity` floor, nothing was checked (zero files/models), or an error-severity diagnostic remains. |
| 130 | Interrupted (Ctrl-C), via click's `Abort` and a raw `KeyboardInterrupt` alike. |

Two clarifications:

- 0-vs-2 is the advisory guarantee: findings never gate a build unless the caller opts in with
  `--strict` — and `--strict` fails at 2, not 1, because a strict trip is a *policy* outcome
  (the tool worked and found things), not a tool failure.
- A sibling may document a narrow specialization, never a redefinition: `coop-data-doc`
  documents exit 1 as "stale docs" for its check mode — a documented, opt-in gate — but no tool
  may, e.g., return 1 for findings.

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
`Editable project location: <this repo>`. If the final import fails instead,
`python3` is probably 3.14+ — rebuild the venv with 3.13 (see Environment).

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

The coop-* repos are assumed cloned **side by side under one parent directory**
(on Aaron's Mac: `~/Developer`) — every `$HOME/Developer` below means that
parent; substitute yours if it differs. The consumer venvs (the
`coop-sql-review` / `coop-dax-review` checkouts next to this repo)
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
- A feature change must update this repo's own docs (README.md / AGENTS.md) in
  the same change — the README's module table went a full release stale (it
  missed every 0.4.0 addition) because nothing enforced this.

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
7. Suite definition-of-done: when this is part of a suite release, the release
   is **not done** until the `coop-website` repo is synced + pushed —
   `versions.json` updated first, then both of its check scripts print `PASS`
   (exact procedure: coop-website's `AGENTS.md`, "Release-time procedure").

TODO(aaron): confirm whether the `coop release` helper in coop-agent should
drive this repo's releases too.

## Never do

- Never create or push a `v*` tag unless explicitly instructed — the tag push
  publishes to PyPI immediately. "Explicitly instructed" means Aaron asked for
  a release **naming the version, in the current conversation**. Never infer a
  release from a clean working tree, a version bump you notice, or green CI —
  a real incident (2026-07-02): an agent cut a spurious empty release off a
  "clean tree" signal while another agent shared the same tree.
- Never move, delete, or reuse an existing `v*` tag; PyPI refuses re-uploads of
  a version. A botched release means a new patch version.
- Never bump the version anywhere except `src/coop_review_core/__init__.py`.
- Never add network access outside `upgrade.py`.
- Never add a runtime dependency casually — the linters inherit every one.
- Never use Python syntax newer than 3.10 (`requires-python = ">=3.10"`).
- Never commit `dist/`, `.venv/`, `test_env/`, or cache dirs (all gitignored).
- Never break an item on the do-not-break list in a minor release.

## Working the backlog (agents)

This repo's work queue is its GitHub issues labeled **`agent:ready`**:
`gh issue list --label agent:ready --state open`. Each issue is self-contained
(Context / Problem / Proposed fix / Acceptance criteria). Rules of engagement:

- Read this file fully first; take ONE issue at a time (oldest first unless one
  blocks another).
- Implement to the acceptance criteria; run the full test suite + lint before
  every commit; commit with `Fixes #N` so the issue closes on push.
- Never push tags, release, or bump versions — Aaron releases (see the release
  rules above).
- An open issue WITHOUT the `agent:ready` label is waiting on a human decision —
  leave it alone.
- The queue may be empty here — core work lands in bursts. Anything you add or
  change must respect the do-not-break list and pin policy above.
