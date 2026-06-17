"""Core integration: PRML v0.1 manifest generation + Giskard scenario verification.

This adapter is a thin Giskard-shaped layer over the published ``falsify``
package's reference implementation (``falsify_prml``). It does NOT carry its own
canonicalization, hashing, validation or predicate logic — all of that is
delegated to ``falsify_prml`` so the hash a Giskard user commits is byte-for-byte
the same one the ``falsify`` CLI, the JS/Go/Rust reference impls, and every other
PRML surface produce. See https://spec.falsify.dev/v0.1.

Giskard (giskard-checks) runs a ``Scenario`` of checks and returns a
``ScenarioResult``. Each ``CheckResult`` carries a status (PASS/FAIL/ERROR/SKIP)
and a list of ``Metric(name, value)``. This module lets you pre-register an eval
claim (a metric + threshold) to a SHA-256 *before* the run, then verify the
realised ``ScenarioResult`` against it.

Manifests follow the real PRML v0.1 schema (nine required fields)::

    version: prml/0.1
    claim_id: <stable id>
    created_at: <RFC 3339>
    metric: <name>
    comparator: ">=" | "<=" | ">" | "<" | "=="
    threshold: <float>
    dataset: {id: <name>, hash: <64 lowercase hex>}
    seed: <int>
    producer: {id: <model/org id>}

Giskard-specific context (scenario name) is carried as an extra top-level key
(``giskard_scenario``). ``falsify_prml.validate_manifest`` allows unknown keys,
and they participate in the canonical hash like any other field.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import falsify_prml as _prml
import yaml

# -- Errors --------------------------------------------------------------------


class PRMLVerificationError(Exception):
    """Raised when a result fails PRML hash verification."""


class MalformedResultError(Exception):
    """Raised when the Giskard result / manifest is structurally invalid
    (e.g. the pre-registered metric is not present in the result)."""


# Comparators accepted by PRML v0.1 (mirrors falsify_prml.VALID_COMPARATORS).
_COMPARATORS = {">=", "<=", ">", "<", "=="}

# Giskard-specific extra keys carried in the manifest alongside the nine
# required PRML fields. NOT part of the PRML schema, but PRML allows extra keys;
# they are hashed like everything else.
_EXTRA_KEYS = ("giskard_scenario",)


# -- Manifest ------------------------------------------------------------------


@dataclass
class GiskardManifest:
    """A PRML v0.1 manifest scoped to Giskard scenario results.

    Holds the real PRML v0.1 fields. Identity that a Giskard run exposes maps
    as follows:

        metric                   -> metric
        threshold                -> threshold
        threshold_direction      -> comparator
        dataset (name)           -> dataset.id
        dataset_hash             -> dataset.hash   (64 lowercase hex)
        model_version            -> producer.id
        seed                     -> seed
        pre_registered (RFC3339) -> created_at
        giskard_scenario         -> extra key ``giskard_scenario``

    The observed value is never part of the manifest; the manifest commits the
    *threshold*, not the realised value (which is filled at verify time from the
    Giskard ``ScenarioResult``).
    """

    metric: str
    comparator: str  # ">=" | "<=" | "==" | ">" | "<"
    threshold: float
    dataset_id: str
    dataset_hash: str
    producer_id: str
    seed: int
    created_at: str  # RFC 3339
    claim_id: str
    version: str = "prml/0.1"

    # Giskard-specific (optional) — carried as an extra top-level key
    giskard_scenario: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render the real PRML v0.1 manifest dict (the thing that gets hashed).

        None-valued optional Giskard fields are omitted so they do not change
        the canonical bytes when unset.
        """
        m: dict[str, Any] = {
            "version": self.version,
            "claim_id": self.claim_id,
            "created_at": self.created_at,
            "metric": self.metric,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "dataset": {"id": self.dataset_id, "hash": self.dataset_hash},
            "seed": self.seed,
            "producer": {"id": self.producer_id},
        }
        for key in _EXTRA_KEYS:
            value = getattr(self, key)
            if value is not None:
                m[key] = value
        return m

    def hash(self) -> str:
        """Return the canonical PRML SHA-256 (64 lowercase hex) of this manifest.

        Delegates to ``falsify_prml.manifest_hash`` — identical bytes to the
        ``falsify`` CLI and all reference implementations.
        """
        return _prml.manifest_hash(self.to_dict())

    def to_canonical_yaml(self) -> bytes:
        """Canonical byte serialisation per PRML v0.1 §4 (via falsify_prml)."""
        return _prml.canonicalize(self.to_dict()).encode("utf-8")


def _manifest_from_fields(fields: dict[str, Any]) -> GiskardManifest:
    """Build a :class:`GiskardManifest` from a real PRML v0.1 manifest dict.

    Accepts the nested ``dataset``/``producer`` shape plus the Giskard extra
    key. Used when loading a committed manifest off disk.
    """
    ds = fields.get("dataset") or {}
    prod = fields.get("producer") or {}
    if not isinstance(ds, dict) or not isinstance(prod, dict):
        raise MalformedResultError(
            "manifest dataset/producer must be mappings (real PRML v0.1 schema)"
        )
    return GiskardManifest(
        metric=fields.get("metric"),
        comparator=fields.get("comparator"),
        threshold=fields.get("threshold"),
        dataset_id=ds.get("id"),
        dataset_hash=ds.get("hash"),
        producer_id=prod.get("id"),
        seed=fields.get("seed"),
        created_at=fields.get("created_at"),
        claim_id=fields.get("claim_id"),
        version=fields.get("version", "prml/0.1"),
        giskard_scenario=fields.get("giskard_scenario"),
    )


# -- Pre-registration ----------------------------------------------------------


def preregister(
    *,
    metric: str,
    threshold: float,
    threshold_direction: str,
    dataset: str,
    dataset_hash: str,
    seed: int,
    producer_id: str = "unknown",
    claim_id: str | None = None,
    giskard_scenario: str | None = None,
    pre_registered: str | None = None,
    output_path: str | Path | None = None,
) -> tuple[str, GiskardManifest]:
    """Create a PRML v0.1 manifest before running a Giskard scenario.

    ``metric`` is either ``"pass_rate"`` (fraction of checks that passed) or the
    ``name`` of a Giskard ``Metric`` emitted by a check.

    ``threshold_direction`` is the adapter-facing name for the PRML
    ``comparator`` field (kept for backwards-compatible call sites).

    ``dataset_hash`` must be 64 lowercase hex chars (a SHA-256 of the dataset),
    per PRML v0.1. ``producer_id`` maps to PRML ``producer.id`` (the model/org
    that produced the run). ``claim_id`` defaults to ``"{scenario-or-dataset}:{metric}"``
    if not supplied.

    Returns ``(hash, manifest)``; the hash is the bare 64-hex canonical PRML
    SHA-256 (no ``sha256:`` prefix). Write the manifest to disk via
    ``output_path``.

    Raises:
        ValueError if the resulting manifest is invalid per
        ``falsify_prml.validate_manifest`` (bad comparator, non-hex dataset
        hash, control chars, etc.).
    """
    if threshold_direction not in _COMPARATORS:
        raise ValueError(
            f"threshold_direction must be one of >= <= > < ==, got {threshold_direction!r}"
        )
    if pre_registered is None:
        pre_registered = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        if pre_registered.endswith("+00:00"):
            pre_registered = pre_registered[:-6] + "Z"

    if claim_id is None:
        claim_id = f"{giskard_scenario or dataset}:{metric}"

    manifest = GiskardManifest(
        metric=metric,
        comparator=threshold_direction,
        threshold=threshold,
        dataset_id=dataset,
        dataset_hash=dataset_hash,
        producer_id=producer_id,
        seed=seed,
        created_at=pre_registered,
        claim_id=claim_id,
        giskard_scenario=giskard_scenario,
    )

    errors = _prml.validate_manifest(manifest.to_dict())
    if errors:
        raise ValueError("invalid PRML manifest: " + "; ".join(errors))

    h = manifest.hash()
    if output_path is not None:
        Path(output_path).write_bytes(manifest.to_canonical_yaml())
    return h, manifest


def load_committed_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load a committed ``.prml.yaml`` and return ``(fields, committed_hash)``.

    The committed hash is the *canonical* PRML hash of the parsed manifest
    (``falsify_prml.manifest_hash``), NOT a hash of the raw file bytes. This is
    the value :func:`preregister` returned at lock time and the value every PRML
    surface re-derives, so it is robust to incidental file reformatting.
    """
    fields = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(fields, dict):
        raise MalformedResultError(
            f"manifest at {path} did not parse to a mapping (got {type(fields).__name__})"
        )
    committed_hash = _prml.manifest_hash(fields)
    return fields, committed_hash


# -- Observed-metric extraction from a Giskard ScenarioResult ------------------


def _iter_check_results(result: Any):
    """Yield every CheckResult in a ScenarioResult (across steps), defensively."""
    steps = getattr(result, "steps", None) or []
    for step in steps:
        for cr in (getattr(step, "results", None) or []):
            yield cr


def extract_observed(result: Any, metric: str) -> float | None:
    """Pull the observed value for ``metric`` from a Giskard ScenarioResult.

    - ``"pass_rate"``: fraction of (non-skipped) checks whose status is PASS.
    - otherwise: the value of the first ``Metric`` whose ``name`` matches
      ``metric`` (exact or last path segment), searched across all checks.
    """
    if metric == "pass_rate":
        passed = total = 0
        for cr in _iter_check_results(result):
            if getattr(cr, "skipped", False):
                continue
            total += 1
            if getattr(cr, "passed", False):
                passed += 1
        if total == 0:
            return None
        return passed / total

    target = metric.split("/")[-1]
    for cr in _iter_check_results(result):
        for m in (getattr(cr, "metrics", None) or []):
            name = getattr(m, "name", None)
            if name is None and isinstance(m, dict):
                name = m.get("name")
            value = getattr(m, "value", None)
            if value is None and isinstance(m, dict):
                value = m.get("value")
            if name in {metric, target} and value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    return None


# -- Verification --------------------------------------------------------------


def _verdict(expected_hash: str, fields: dict[str, Any], observed: float | None) -> dict[str, Any]:
    manifest = _manifest_from_fields(fields)
    actual_hash = manifest.hash()
    hash_match = actual_hash == expected_hash
    comparator = manifest.comparator
    threshold = manifest.threshold
    threshold_ok = (
        observed is not None
        and comparator in _COMPARATORS
        and threshold is not None
        and _prml.evaluate_predicate(observed, comparator, threshold)
    )
    if not hash_match:
        status = "TAMPERED"
    elif threshold_ok:
        status = "PASS"
    else:
        status = "FAIL"
    return {
        "ok": hash_match and threshold_ok,
        "status": status,
        "hash_match": hash_match,
        "threshold_satisfied": threshold_ok,
        "observed_value": observed,
        "threshold": threshold,
        "comparator": comparator,
        "metric": manifest.metric,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
    }


def verify_scenario_result(
    result: Any,
    manifest_path: str | Path,
    *,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    """Verify a Giskard ``ScenarioResult`` against a committed manifest.

    Extracts the observed value for the committed metric, evaluates the
    committed predicate, and returns a verdict dict with ``status`` of
    PASS / FAIL / TAMPERED. The verdict uses PRML field names (``comparator``),
    not the legacy ``threshold_direction``.

    If ``expected_hash`` (the 64-hex canonical PRML hash returned by
    :func:`preregister` at lock time) is supplied, a mismatch between it and the
    hash recomputed from the manifest on disk is reported as **TAMPERED** — the
    manifest file was altered after the claim was committed. When omitted, the
    expected hash is taken from the manifest file itself, so only the
    predicate (PASS/FAIL) is meaningfully evaluated; pass ``expected_hash`` for
    real tamper-evidence.
    """
    fields, committed_hash = load_committed_manifest(manifest_path)
    metric = fields.get("metric")
    if not metric:
        raise MalformedResultError(f"manifest {manifest_path} has no metric")
    observed = extract_observed(result, metric)
    return _verdict(expected_hash or committed_hash, fields, observed)
