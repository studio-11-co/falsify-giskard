"""End-to-end check against the REAL giskard-checks result types.

Builds genuine giskard `CheckResult` / `Metric` / `TestCaseResult` objects and
runs them through falsify-giskard, to confirm we read Giskard's actual data
model (not just SimpleNamespace mocks). Skipped when giskard is not installed.

The top-level ScenarioResult is wrapped in a lightweight container because the
real ScenarioResult requires a populated `final_trace`; our code only traverses
`result.steps[].results[]`, which here are genuine giskard objects.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from falsify_giskard import preregister, verify_scenario_result
from falsify_giskard.core import extract_observed

# A valid PRML dataset.hash: 64 lowercase hex chars (SHA-256 of the empty string).
HASH64 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _real_result():
    pytest.importorskip("giskard")
    from giskard.checks.core.result import (  # noqa: E402
        CheckResult,
        CheckStatus,
        Metric,
        TestCaseResult,
    )

    checks = [
        CheckResult(status=CheckStatus.PASS, metrics=[Metric(name="groundedness", value=0.91)]),
        CheckResult(status=CheckStatus.PASS),
        CheckResult(status=CheckStatus.FAIL),
    ]
    tc = TestCaseResult(results=checks, duration_ms=0)
    return SimpleNamespace(steps=[tc])


def test_real_types_pass_rate():
    result = _real_result()
    # 2 of 3 checks pass
    assert extract_observed(result, "pass_rate") == pytest.approx(2 / 3)


def test_real_types_named_metric():
    result = _real_result()
    assert extract_observed(result, "groundedness") == 0.91


def test_real_types_verify_pass(tmp_path):
    result = _real_result()
    path = tmp_path / "g.prml.yaml"
    preregister(
        metric="groundedness", threshold=0.8, threshold_direction=">=",
        dataset="d", dataset_hash=HASH64, seed=1, producer_id="acme/eval-bot",
        output_path=str(path),
    )
    v = verify_scenario_result(result, str(path))
    assert v["status"] == "PASS"
    assert v["observed_value"] == 0.91


def test_real_types_verify_fail(tmp_path):
    result = _real_result()
    path = tmp_path / "g.prml.yaml"
    preregister(
        metric="pass_rate", threshold=0.9, threshold_direction=">=",
        dataset="d", dataset_hash=HASH64, seed=1, producer_id="acme/eval-bot",
        output_path=str(path),
    )
    v = verify_scenario_result(result, str(path))  # observed 0.667 < 0.9
    assert v["status"] == "FAIL"
