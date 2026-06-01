"""Tests for falsify-giskard core: preregister, extract_observed, verify.

Giskard's ScenarioResult is mocked with SimpleNamespace so these run without
giskard-checks installed. A real giskard-checks scenario is exercised
separately in test_giskard_e2e.py (skipped when giskard is absent).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from falsify_giskard import (
    GiskardManifest,
    load_committed_manifest,
    preregister,
    verify_scenario_result,
)
from falsify_giskard.core import extract_observed


def _check(passed: bool, *, skipped: bool = False, metrics=()):
    return SimpleNamespace(
        passed=passed,
        failed=(not passed and not skipped),
        skipped=skipped,
        metrics=[SimpleNamespace(name=n, value=v) for n, v in metrics],
    )


def _result(*checks):
    return SimpleNamespace(steps=[SimpleNamespace(results=list(checks))])


def _manifest(tmp_path, **over):
    kw = dict(
        metric="pass_rate",
        threshold=0.9,
        threshold_direction=">=",
        dataset="support-qa-v1",
        dataset_hash="sha256:abc",
        seed=42,
        giskard_scenario="grounded-answers",
    )
    kw.update(over)
    path = tmp_path / "x.prml.yaml"
    h, _ = preregister(output_path=str(path), **kw)
    return path, h


# -- pre-registration / manifest ----------------------------------------------


def test_preregister_roundtrip(tmp_path):
    path, h = _manifest(tmp_path)
    fields, committed_hash = load_committed_manifest(str(path))
    assert committed_hash == h
    assert fields["metric"] == "pass_rate"
    assert fields["threshold"] == 0.9
    assert fields["giskard_scenario"] == "grounded-answers"


def test_preregister_rejects_bad_comparator(tmp_path):
    with pytest.raises(ValueError):
        preregister(
            metric="pass_rate", threshold=0.9, threshold_direction="=>",
            dataset="d", dataset_hash="sha256:a", seed=1,
        )


# -- extract_observed ----------------------------------------------------------


def test_extract_pass_rate():
    r = _result(_check(True), _check(True), _check(True), _check(False))
    assert extract_observed(r, "pass_rate") == 0.75


def test_extract_pass_rate_excludes_skipped():
    r = _result(_check(True), _check(True), _check(False, skipped=True))
    assert extract_observed(r, "pass_rate") == 1.0  # 2/2 non-skipped


def test_extract_named_metric():
    r = _result(_check(True, metrics=[("semantic_similarity", 0.83)]))
    assert extract_observed(r, "semantic_similarity") == 0.83


def test_extract_missing_metric_returns_none():
    r = _result(_check(True, metrics=[("groundedness", 0.9)]))
    assert extract_observed(r, "not_there") is None


# -- verify_scenario_result ----------------------------------------------------


def test_verify_pass(tmp_path):
    path, h = _manifest(tmp_path, threshold=0.7)
    r = _result(_check(True), _check(True), _check(True), _check(False))  # 0.75
    v = verify_scenario_result(r, str(path))
    assert v["status"] == "PASS"
    assert v["ok"] and v["hash_match"] and v["threshold_satisfied"]
    assert v["observed_value"] == 0.75
    assert v["expected_hash"] == h


def test_verify_fail(tmp_path):
    path, _ = _manifest(tmp_path, threshold=0.9)
    r = _result(_check(True), _check(True), _check(True), _check(False))  # 0.75
    v = verify_scenario_result(r, str(path))
    assert v["status"] == "FAIL"
    assert v["hash_match"] and not v["threshold_satisfied"]


def test_verify_named_metric_pass(tmp_path):
    path, _ = _manifest(tmp_path, metric="groundedness", threshold=0.8)
    r = _result(_check(True, metrics=[("groundedness", 0.91)]))
    v = verify_scenario_result(r, str(path))
    assert v["status"] == "PASS"
    assert v["observed_value"] == 0.91


def test_verify_tampered_noncanonical_file(tmp_path):
    # A manifest file edited after commit so its bytes no longer match the
    # canonical form: sha256(file) != hash(reparsed) -> TAMPERED.
    path, _ = _manifest(tmp_path, threshold=0.7)
    path.write_text(path.read_text() + "\n# sneaky edit\n", encoding="utf-8")
    r = _result(_check(True), _check(True))  # would PASS if untampered
    v = verify_scenario_result(r, str(path))
    assert v["status"] == "TAMPERED"
    assert not v["hash_match"]


def test_canonical_hash_is_deterministic():
    m1 = GiskardManifest(
        metric="pass_rate", value=None, threshold=0.9, threshold_direction=">=",
        dataset="d", dataset_hash="sha256:a", seed=1, pre_registered="2026-06-01T00:00:00Z",
    )
    m2 = GiskardManifest(
        metric="pass_rate", value=0.99, threshold=0.9, threshold_direction=">=",
        dataset="d", dataset_hash="sha256:a", seed=1, pre_registered="2026-06-01T00:00:00Z",
    )
    # `value` is excluded from the hash, so m1 and m2 hash identically.
    assert m1.hash() == m2.hash()
