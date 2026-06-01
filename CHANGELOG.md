# Changelog

All notable changes to `falsify-giskard` are documented here.

## [0.1.0] — 2026-06-01

Initial release.

### Added
- `preregister()` — commit a Giskard eval claim (metric, comparator, threshold, dataset hash, seed) to a PRML v0.1 manifest + SHA-256 before the run.
- `verify_scenario_result()` — verify a Giskard `ScenarioResult` against a committed manifest, returning a PASS / FAIL / TAMPERED verdict.
- `extract_observed()` — pull `pass_rate` (fraction of non-skipped checks passing) or a named Giskard `Metric` value from a `ScenarioResult`.
- `load_committed_manifest()` and the `GiskardManifest` dataclass.

### Notes
- Canonicalisation mirrors the PRML v0.1 rules used across the falsify tooling.
- `giskard-checks` is an optional dependency; the core verification works on the result object's public shape.
