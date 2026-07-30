# Changelog

All notable changes to `falsify-giskard` are documented here.

## [0.3.0] — 2026-07-30

### Changed (breaking)
- **Manifests conform to the published PRML v0.1 JSON Schema** (falsify
  0.3.12 aligned all validators with it): `claim_id` defaults to a generated
  **UUIDv7** (was `"<scenario>:<metric>"`, which the schema rejects; custom
  claim_ids must be UUIDv7), and `giskard_scenario` rides under
  **`metric_args`** instead of as a top-level key
  (`additionalProperties: false`).
- Hashes of manifests produced by 0.2.x do not match 0.3.0 output; re-lock to
  move to conforming manifests. Minimum `falsify` dependency is now 0.3.12.

## [0.2.0] — 2026-06-18

### Changed (breaking)
- **Manifests now use the real PRML v0.1 schema** (nine required fields:
  `version`, `claim_id`, `created_at`, `metric`, `comparator`, `threshold`,
  `dataset.{id,hash}`, `seed`, `producer.id`) instead of the previous flat,
  ad-hoc layout. Manifests written by 0.1.x will not verify against 0.2.0 and
  must be re-locked. Field migration:
  - `threshold_direction` (flat) → `comparator`
  - `dataset_hash` (flat) → `dataset.hash` — **must now be 64 lowercase hex**
    (a `sha256:`-prefixed value is rejected); dataset name → `dataset.id`
  - new `producer_id` kwarg → `producer.id` (defaults to `"unknown"`)
  - `pre_registered` → `created_at`
  - `prml_version` dropped (now `version: prml/0.1`)
  - new `claim_id` (defaults to `"{giskard_scenario or dataset}:{metric}"`,
    overridable via the `claim_id` kwarg)
  - `giskard_scenario` is retained as an extra (non-schema) top-level key
- Emitted verdicts now use the PRML field name `comparator` (no
  `threshold_direction` in output).
- Hash/canonicalisation/validation/predicate logic is now delegated to the
  published **`falsify_prml`** reference implementation (new `falsify>=0.3.8`
  dependency) — no divergent in-tree core. Committed hashes are now the
  canonical PRML SHA-256 (bare 64-hex, no `sha256:` prefix), byte-identical to
  the `falsify` CLI and the JS/Go/Rust reference implementations.
- `verify_scenario_result()` gained an optional `expected_hash` kwarg: pass the
  lock-time hash to get real tamper-evidence (TAMPERED on mismatch).

### Added
- `falsify` (>= 0.3.8) is now a required dependency, providing `falsify_prml`.

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
