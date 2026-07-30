"""Tests for falsify-giskard core: preregister, extract_observed, verify.

Giskard's ScenarioResult is mocked with SimpleNamespace so these run without
giskard-checks installed. A real giskard-checks scenario is exercised
separately in test_giskard_e2e.py (skipped when giskard is absent).

These tests assert the adapter emits real PRML v0.1 manifests (nine required
fields, nested dataset/producer) and that every committed manifest passes
``falsify_prml.validate_manifest``.
"""

from __future__ import annotations

from types import SimpleNamespace

import falsify_prml as prml
import pytest

from falsify_giskard import (
    GiskardManifest,
    load_committed_manifest,
    preregister,
    verify_scenario_result,
)
from falsify_giskard.core import extract_observed

# A valid PRML dataset.hash: 64 lowercase hex chars (SHA-256 of the empty string).
HASH64 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


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
        dataset_hash=HASH64,
        seed=42,
        producer_id="acme/eval-bot",
        giskard_scenario="grounded-answers",
    )
    kw.update(over)
    out_name = kw.pop("output_name", "x.prml.yaml")
    path = tmp_path / out_name
    h, _ = preregister(output_path=str(path), **kw)
    return path, h


# -- pre-registration / manifest ----------------------------------------------


def test_preregister_roundtrip(tmp_path):
    path, h = _manifest(tmp_path)
    fields, committed_hash = load_committed_manifest(str(path))
    assert committed_hash == h
    assert fields["metric"] == "pass_rate"
    assert fields["threshold"] == 0.9
    assert fields["metric_args"]["giskard_scenario"] == "grounded-answers"


def test_committed_manifest_is_valid_prml(tmp_path):
    """Every committed manifest must be a real PRML v0.1 manifest."""
    path, _ = _manifest(tmp_path)
    fields, _ = load_committed_manifest(str(path))
    assert prml.validate_manifest(fields) == []
    # Real PRML schema: nested dataset/producer, comparator (not threshold_direction).
    assert fields["version"] == "prml/0.1"
    assert fields["comparator"] == ">="
    assert "threshold_direction" not in fields
    assert fields["dataset"] == {"id": "support-qa-v1", "hash": HASH64}
    assert fields["producer"] == {"id": "acme/eval-bot"}
    assert "claim_id" in fields and "created_at" in fields


def test_claim_id_defaults_to_generated_uuid7(tmp_path):
    import re as _re
    path, _ = _manifest(tmp_path)
    fields, _h = load_committed_manifest(str(path))
    assert _re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        fields["claim_id"],
    ), fields["claim_id"]


def test_claim_id_unique_per_lock(tmp_path):
    p1, _ = _manifest(tmp_path, output_name="a.yaml")
    p2, _ = _manifest(tmp_path, output_name="b.yaml")
    f1, _ = load_committed_manifest(str(p1))
    f2, _ = load_committed_manifest(str(p2))
    assert f1["claim_id"] != f2["claim_id"]


def test_claim_id_override(tmp_path):
    path, _ = _manifest(tmp_path, claim_id="01920000-0000-7000-8000-000000000042")
    fields, _ = load_committed_manifest(str(path))
    assert fields["claim_id"] == "01920000-0000-7000-8000-000000000042"


def test_preregister_rejects_bad_comparator(tmp_path):
    with pytest.raises(ValueError):
        preregister(
            metric="pass_rate", threshold=0.9, threshold_direction="=>",
            dataset="d", dataset_hash=HASH64, seed=1,
        )


def test_preregister_rejects_non_hex_dataset_hash(tmp_path):
    # Old schema allowed "sha256:abc"; real PRML requires 64 lowercase hex.
    with pytest.raises(ValueError):
        preregister(
            metric="pass_rate", threshold=0.9, threshold_direction=">=",
            dataset="d", dataset_hash="sha256:abc", seed=1,
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
    # Verdict uses PRML field names.
    assert v["comparator"] == ">="
    assert "threshold_direction" not in v


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


def test_verify_tampered_mutated_field(tmp_path):
    # Commit, then mutate a committed identity field after lock. Verifying
    # against the lock-time `expected_hash` detects the swap -> TAMPERED.
    path, h = _manifest(tmp_path, threshold=0.7)
    fields, _ = load_committed_manifest(str(path))
    fields["dataset"]["hash"] = "0" * 64  # different valid hex -> different hash
    path.write_bytes(prml.canonicalize(fields).encode("utf-8"))
    r = _result(_check(True), _check(True))  # would PASS if untampered
    v = verify_scenario_result(r, str(path), expected_hash=h)
    assert v["status"] == "TAMPERED"
    assert not v["hash_match"]
    assert v["expected_hash"] == h
    assert v["actual_hash"] != h


def test_verify_pass_with_expected_hash(tmp_path):
    # Untampered file + correct expected_hash -> PASS.
    path, h = _manifest(tmp_path, threshold=0.7)
    r = _result(_check(True), _check(True), _check(True), _check(False))  # 0.75
    v = verify_scenario_result(r, str(path), expected_hash=h)
    assert v["status"] == "PASS" and v["hash_match"]


def test_canonical_hash_matches_falsify_prml(tmp_path):
    # The adapter's hash MUST equal falsify_prml.manifest_hash of the same dict.
    m = GiskardManifest(
        metric="pass_rate", comparator=">=", threshold=0.9,
        dataset_id="d", dataset_hash=HASH64, producer_id="p", seed=1,
        created_at="2026-06-01T00:00:00Z", claim_id="01920000-0000-7000-8000-000000000042",
    )
    assert m.hash() == prml.manifest_hash(m.to_dict())
    assert prml.validate_manifest(m.to_dict()) == []
