"""falsify-giskard — PRML pre-registration for Giskard scenario results.

Pre-register an eval claim before running a Giskard scenario, then verify the
realised result against it:

    from falsify_giskard import preregister, verify_scenario_result

    # Before the run — commit the claim (real PRML v0.1 manifest)
    h, manifest = preregister(
        metric="pass_rate",
        threshold=0.9,
        threshold_direction=">=",          # PRML `comparator`
        dataset="support-qa-v1",           # PRML `dataset.id`
        dataset_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # PRML `dataset.hash` (64 hex)
        seed=42,
        producer_id="acme/eval-bot",       # PRML `producer.id`
        giskard_scenario="grounded-answers",
        output_path="grounded.prml.yaml",
    )

    # Run the Giskard scenario as usual
    result = await scenario.run()

    # After the run — verify
    verdict = verify_scenario_result(result, "grounded.prml.yaml")
    assert verdict["status"] == "PASS"
"""

from falsify_giskard.core import (
    preregister,
    verify_scenario_result,
    extract_observed,
    load_committed_manifest,
    GiskardManifest,
    PRMLVerificationError,
    MalformedResultError,
)

__version__ = "0.3.0"

__all__ = [
    "preregister",
    "verify_scenario_result",
    "extract_observed",
    "load_committed_manifest",
    "GiskardManifest",
    "PRMLVerificationError",
    "MalformedResultError",
    "__version__",
]
