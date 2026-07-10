# Changelog

All notable changes to **coop-review-core** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]
### Removed
- **BREAKING (library API): `upgrade.apply_plan` (and its private `_run` subprocess
  executor) is removed** (issue #5; Aaron's call: remove). Both shipped linters print
  the commands from `upgrade_command` instead of self-applying, so `apply_plan` was
  retained-but-dead API with no known callers. Removing a public name makes the next
  release **0.5.0**, and both linters must drop their `apply_plan` re-import and raise
  their `coop-review-core>=0.4,<0.5` pins in the same generation. `build_plan`,
  `upgrade_command`, and the rest of the plan/check machinery are unchanged.
