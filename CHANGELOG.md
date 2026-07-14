# Changelog

All notable changes to **coop-review-core** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]
### Fixed
- Inline directive grammar now matches its documentation: `<tool>:ignore * reason: ...`
  is a wildcard (silences every rule on the line) in the rule view too, not just the
  syntax view (issue #16). Previously the rule view judged the raw tail, so a `*` with a
  reason attached suppressed nothing while the syntax view treated the same line as a
  wildcard — internally inconsistent, and the docs actively encourage attaching a reason.
  This suppresses strictly more than before (a previously-inert directive now fires), so
  it is not a breaking change to the fail-closed contract; `ignore reason: ...` with no
  `*`/id still suppresses nothing.

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
