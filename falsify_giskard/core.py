"""Core integration: PRML manifest generation + Giskard scenario verification.

Giskard (giskard-checks v3) runs a `Scenario` of checks and returns a
`ScenarioResult`. Each `CheckResult` carries a status (PASS/FAIL/ERROR/SKIP)
and a list of `Metric(name, value)`. This module lets you pre-register an
eval claim (a metric + threshold) to a SHA-256 *before* the run, then verify
the realised `ScenarioResult` against it.

The canonicalisation mirrors the PRML v0.1 rules used by the falsify
reference tooling, so a Giskard claim hashes deterministically.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

# -- Errors --------------------------------------------------------------------


class PRMLVerificationError(Exception):
    """Raised when a result fails PRML hash verification."""


class MalformedResultError(Exception):
    """Raised when the Giskard result / manifest is structurally invalid
    (e.g. the pre-registered metric is not present in the result)."""


# -- Comparators ---------------------------------------------------------------

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


# -- Manifest ------------------------------------------------------------------


@dataclass
class GiskardManifest:
    """A PRML manifest scoped to Giskard scenario results.

    Holds the PRML v0.1 claim fields plus an optional Giskard scenario name.
    The `value` is excluded from the canonical hash (it is filled at verify
    time); the manifest commits the *threshold*, not the observed value.
    """

    metric: str
    value: float | None  # None at pre-registration; filled at verify time
    threshold: float
    threshold_direction: str  # ">=" | "<=" | "==" | ">" | "<"
    dataset: str
    dataset_hash: str
    seed: int
    pre_registered: str  # RFC 3339
    prml_version: str = "0.1"
    giskard_scenario: str | None = None

    def to_canonical_yaml(self) -> bytes:
        d = asdict(self)
        d.pop("value", None)
        d = {k: v for k, v in d.items() if v is not None}
        canonical = yaml.safe_dump(
            d,
            default_flow_style=False,
            sort_keys=True,
            width=float("inf"),
            allow_unicode=False,
        )
        canonical = canonical.replace("\r\n", "\n").rstrip() + "\n"
        return canonical.encode("utf-8")

    def hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.to_canonical_yaml()).hexdigest()


_MANIFEST_FIELDS = {
    "metric", "threshold", "threshold_direction", "dataset", "dataset_hash",
    "seed", "pre_registered", "prml_version", "giskard_scenario",
}


# -- Pre-registration ----------------------------------------------------------


def preregister(
    *,
    metric: str,
    threshold: float,
    threshold_direction: str,
    dataset: str,
    dataset_hash: str,
    seed: int,
    giskard_scenario: str | None = None,
    pre_registered: str | None = None,
    output_path: str | Path | None = None,
) -> tuple[str, GiskardManifest]:
    """Create a PRML manifest before running a Giskard scenario.

    `metric` is either ``"pass_rate"`` (fraction of checks that passed) or the
    `name` of a Giskard `Metric` emitted by a check. Returns
    ``(hash, manifest)``; write the manifest to disk via ``output_path``.
    """
    if threshold_direction not in _OPS:
        raise ValueError(
            f"threshold_direction must be one of >= <= > < ==, got {threshold_direction!r}"
        )
    if pre_registered is None:
        pre_registered = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        if pre_registered.endswith("+00:00"):
            pre_registered = pre_registered[:-6] + "Z"

    manifest = GiskardManifest(
        metric=metric,
        value=None,
        threshold=threshold,
        threshold_direction=threshold_direction,
        dataset=dataset,
        dataset_hash=dataset_hash,
        seed=seed,
        pre_registered=pre_registered,
        giskard_scenario=giskard_scenario,
    )
    h = manifest.hash()
    if output_path is not None:
        Path(output_path).write_bytes(manifest.to_canonical_yaml())
    return h, manifest


def load_committed_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load a committed ``.prml.yaml`` and return ``(fields, committed_hash)``.

    Because the file is the canonical byte form, ``sha256(file)`` equals the
    hash ``preregister()`` returned at lock time.
    """
    raw = Path(path).read_bytes()
    committed_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    fields = yaml.safe_load(raw.decode("utf-8")) or {}
    if not isinstance(fields, dict):
        raise MalformedResultError(
            f"manifest at {path} did not parse to a mapping (got {type(fields).__name__})"
        )
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
    - otherwise: the value of the first `Metric` whose ``name`` matches
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


def _verdict(committed_hash: str, fields: dict[str, Any], observed: float | None) -> dict[str, Any]:
    rebuilt = {k: v for k, v in fields.items() if k in _MANIFEST_FIELDS}
    manifest = GiskardManifest(value=None, **rebuilt)
    actual_hash = manifest.hash()
    hash_match = actual_hash == committed_hash
    direction = fields.get("threshold_direction")
    threshold = fields.get("threshold")
    threshold_ok = (
        observed is not None
        and direction in _OPS
        and threshold is not None
        and _OPS[direction](observed, threshold)
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
        "threshold_direction": direction,
        "metric": fields.get("metric"),
        "expected_hash": committed_hash,
        "actual_hash": actual_hash,
    }


def verify_scenario_result(
    result: Any,
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Verify a Giskard ``ScenarioResult`` against a committed manifest.

    Extracts the observed value for the committed metric, evaluates the
    committed predicate, and returns a verdict dict with ``status`` of
    PASS / FAIL / TAMPERED.
    """
    fields, committed_hash = load_committed_manifest(manifest_path)
    metric = fields.get("metric")
    if not metric:
        raise MalformedResultError(f"manifest {manifest_path} has no metric")
    observed = extract_observed(result, metric)
    return _verdict(committed_hash, fields, observed)
