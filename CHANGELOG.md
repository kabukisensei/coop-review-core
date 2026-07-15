# Changelog

All notable changes to **coop-review-core** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]
### Added
- `report.to_junit`: a deterministic JUnit XML emitter next to `to_sarif` (issue #30), for
  Azure DevOps' native `PublishTestResults@2` task (a Tests tab, failure counts, and
  run-over-run trends — no marketplace extension, unlike SARIF). Same plain-data contract as
  `to_sarif`: each finding is a `<testcase classname="<rule_id>" name="<file>:<line>">` —
  error severity → `<failure>`, warning/info → `<skipped>` (advisory); each error diagnostic
  → `<failure>` under the synthetic diagnostics rule. No timestamps, sorted, XML-escaped via
  stdlib `xml.sax.saxutils` (no new runtime dep), ASCII-safe, trailing LF — byte-identical
  across runs and OSes. Both linters gain a `--junit PATH` sink on top (consumer follow-up,
  after the next core release raises their pins).

## [0.6.0] - 2026-07-14
### Added
- `coop_review_core.delta`: run-to-run comparison of two review envelopes (issue #29).
  `diff_envelopes(old, new)` keys two same-tool envelopes on each finding's
  line-independent `fingerprint` and returns an `EnvelopeDelta` — `new_findings`,
  `fixed_findings` (whole finding dicts, for display), a `persisting` count,
  per-severity `summary_delta`, and the two `standards.sha256` values with a
  `standards_changed` flag so a rules change is surfaced rather than silently skewing
  the diff. `delta_text(delta, *, color)` and `delta_markdown(delta)` render it
  deterministically (sorted, LF, ASCII) using core's badge/style chrome; a cross-tool
  compare raises `DeltaError`. This is the shared half of the "what changed since last
  review?" feature — consumers add a `--diff-against FILE` flag on top, and coop-agent's
  `coop review` can snapshot the previous JSON before overwriting it.

## [0.5.0] - 2026-07-14
### Fixed
- Inline directive grammar now matches its documentation: `<tool>:ignore * reason: ...`
  is a wildcard (silences every rule on the line) in the rule view too, not just the
  syntax view (issue #16). Previously the rule view judged the raw tail, so a `*` with a
  reason attached suppressed nothing while the syntax view treated the same line as a
  wildcard — internally inconsistent, and the docs actively encourage attaching a reason.
  This suppresses strictly more than before (a previously-inert directive now fires), so
  it is not a breaking change to the fail-closed contract; `ignore reason: ...` with no
  `*`/id still suppresses nothing.
- Directive line numbers no longer drift on files containing form feeds / NEL / unicode
  line separators (issue #17): `scan_all_directives` normalizes CRLF and lone CR to `\n`
  and splits on `\n` only (not `str.splitlines`), so directive line numbers match
  consumers' `\n`-based line counting.
- `add_ignores` maps read/parse failures of the target (unreadable, non-UTF-8, invalid
  YAML) to a friendly one-line `StandardsError` instead of a raw `UnicodeDecodeError` /
  `yaml.YAMLError` traceback (issue #19), and now maps **write** failures (unwritable or
  locked target, a parent that is a file) the same way (issue #22) — completing the
  writer's error contract so a consumer's `--save-ignores` never leaks a traceback.
- `RuleConfig.load` / `loads` honor their documented leniency on a non-mapping `rules:`
  or rule-settings value instead of crashing with a raw `AttributeError` (issue #20).
- `pip_install_origin` returns a real filesystem path for editable installs recorded with
  a `file://` URL — it url-decodes percent-encoding and uses `url2pathname` for the
  Windows `/C:/…` drive form, so the printed upgrade command points at a path that exists
  (issue #18).
- A git-checkout upgrade plan no longer raises an uncaught `FileNotFoundError` when git is
  not installed; `build_plan` degrades gracefully (issue #21).

### Removed
- **BREAKING (library API): `upgrade.apply_plan` (and its private `_run` subprocess
  executor) is removed** (issue #5; Aaron's call: remove). Both shipped linters print
  the commands from `upgrade_command` instead of self-applying, so `apply_plan` was
  retained-but-dead API with no known callers. Removing a public name makes the next
  release **0.5.0**, and both linters must drop their `apply_plan` re-import and raise
  their `coop-review-core>=0.4,<0.5` pins in the same generation. `build_plan`,
  `upgrade_command`, and the rest of the plan/check machinery are unchanged.

## [0.4.0] - 2026-07-09
### Added
- `coop_review_core.report`: the hoisted, byte-identical shared report layer (console
  chrome, the branded HTML style + single bundled logo, and the machine-JSON envelope).
- `coop_review_core.report.to_sarif`: a SARIF 2.1.0 emitter, giving `coop-dax-review`
  SARIF output for free (frozen `partialFingerprints` key `coopFingerprint/v2`).
- `coop_review_core.cliutils`: the hoisted shared CLI helper layer.
- Unified config discovery: tool-named files, git-style walk-up, and env override.
- `CoopReviewError` base class, `__all__` per module, and the pin / deprecation policy.
- `py.typed` marker; tightened public signatures.
- The family-wide exit-code contract, documented in AGENTS.md.
### Changed
- Single-pass `scan_all_directives`; both directive scanners are now views over it.

## [0.3.1] - 2026-07-09
### Fixed
- Coerce `rules.yml` rule keys to `str` in `RuleConfig._from_data`.
- Read `rules.yml` with `utf-8-sig` in `add_ignores`, matching the loaders.
- Fix the fail-open reason-tail split in directive scanning.

## [0.3.0] - 2026-07-08
### Added
- AGENTS.md with the parameterization contract, plus the `Makefile` dev/release helpers.
### Changed
- Hardened the agent docs for headless-Linux / weak-model management.

## [0.2.0] - 2026-07-01
### Added
- The `rules.yml` `ignore:` finding list and its `add_ignores` writer.

## [0.1.2] - 2026-06-29
### Fixed
- Fail-closed inline suppressions and PEP 440-safe version comparison (re-release of
  the 0.1.1 fixes).

## [0.1.1] - 2026-06-25
### Fixed
- PEP 440-safe version comparison.
- Fail-closed inline suppressions.

## [0.1.0] - 2026-06-21
### Added
- Initial release: shared infrastructure for the `coop-*-review` linters (progress,
  diagnostics, severity/fingerprint, inline + baseline suppressions, self-update, and
  the `rules.yml` config layer).
