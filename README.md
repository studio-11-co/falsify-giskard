# falsify-giskard

PRML pre-registration for [Giskard](https://github.com/Giskard-AI/giskard-oss) scenario results.

[![PRML v0.1](https://img.shields.io/badge/PRML-v0.1-39D98A.svg)](https://spec.falsify.dev/v0.1)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Commit a Giskard eval claim (a metric and threshold) to a SHA-256 *before* the run, then verify the realised `ScenarioResult` against it.

## Why

Giskard runs a scenario of checks and reports pass/fail plus per-check metrics. But the report records what happened, not what was promised before the run. Pre-registering the claim means quietly relaxing a threshold or swapping a model after seeing results breaks the hash, so a passing scenario becomes tamper-evident.

This is the Giskard counterpart to [`falsify-inspect`](https://github.com/studio-11-co/falsify-inspect) and uses the same PRML v0.1 manifest format.

## Install

```bash
pip install falsify-giskard
```

## Quickstart

```python
from falsify_giskard import preregister, verify_scenario_result

# 1. Before the run — commit the claim
h, manifest = preregister(
    metric="pass_rate",            # or the name of a Giskard Metric (e.g. "groundedness")
    threshold=0.9,
    threshold_direction=">=",
    dataset="support-qa-v1",
    dataset_hash="sha256:abc...",
    seed=42,
    giskard_scenario="grounded-answers",
    output_path="grounded.prml.yaml",
)
print(h)  # sha256:...

# 2. Run your Giskard scenario as usual
result = await scenario.run()

# 3. After the run — verify
verdict = verify_scenario_result(result, "grounded.prml.yaml")
assert verdict["status"] == "PASS"   # PASS / FAIL / TAMPERED
```

### Metrics

- `metric="pass_rate"` verifies the fraction of (non-skipped) checks that passed.
- `metric="<name>"` verifies the value of a Giskard `Metric` with that `name`
  (for example a `semantic_similarity` or `groundedness` score).

### Verdicts

- **PASS** — the manifest hash matches and the observed metric satisfies the committed threshold.
- **FAIL** — the hash matches but the observed metric misses the threshold.
- **TAMPERED** — the manifest file no longer matches its committed hash (it was altered after commit).

For durable tamper-evidence, commit the returned hash to git or to the public registry at [registry.falsify.dev](https://registry.falsify.dev) right after pre-registration, so the claim is anchored somewhere immutable.

## License

MIT. The PRML specification is CC BY 4.0.
