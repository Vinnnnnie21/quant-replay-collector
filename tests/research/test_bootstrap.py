from __future__ import annotations

import math

import numpy as np
import pytest

from app_config import APP_VERSION
from research.bootstrap import bootstrap_mean_ci, bootstrap_win_rate_ci


def test_bootstrap_handles_empty_sample():
    result = bootstrap_mean_ci([], n_boot=99, ci=0.9, random_state=3)

    assert math.isnan(result["ci_low"])
    assert result["random_seed"] == 3
    assert result["simulation_count"] == 99
    assert result["confidence"] == 0.9


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_bootstrap_rejects_non_finite_samples(bad_value):
    with pytest.raises(ValueError, match="bootstrap.*NaN or infinite.*quality report"):
        bootstrap_mean_ci([1.0, bad_value, 2.0])


def test_win_rate_bootstrap_does_not_silently_drop_nan():
    with pytest.raises(ValueError, match="bootstrap.*NaN or infinite.*quality report"):
        bootstrap_win_rate_ci([True, np.nan, False])


def test_bootstrap_mean_and_win_rate_return_intervals():
    mean_ci = bootstrap_mean_ci([1.0, 2.0, 3.0], n_boot=100)
    win_ci = bootstrap_win_rate_ci([True, False, True], n_boot=100)
    assert mean_ci["ci_low"] <= mean_ci["estimate"] <= mean_ci["ci_high"]
    assert 0 <= win_ci["ci_low"] <= win_ci["ci_high"] <= 100


def test_bootstrap_is_reproducible_and_records_changed_seed():
    first = bootstrap_mean_ci([1.0, 2.0, 3.0, 8.0], n_boot=101, ci=0.9)
    repeated = bootstrap_mean_ci([1.0, 2.0, 3.0, 8.0], n_boot=101, ci=0.9)
    changed = bootstrap_mean_ci([1.0, 2.0, 3.0, 8.0], n_boot=101, ci=0.9, random_state=43)

    assert first == repeated
    assert first["random_seed"] == 42
    assert first["simulation_count"] == 101
    assert first["confidence"] == 0.9
    assert first["application_version"] == APP_VERSION
    assert first["method_version"]
    assert changed["random_seed"] == 43
    assert (changed["ci_low"], changed["ci_high"]) != (first["ci_low"], first["ci_high"])


def test_bootstrap_processes_large_samples_in_bounded_batches():
    result = bootstrap_mean_ci(np.arange(2_000, dtype=float), n_boot=25, batch_size=7)

    assert result["batch_size"] == 7
    assert result["batch_count"] == 4
    assert result["work_items"] == 50_000


def test_bootstrap_cancellation_is_observed_after_a_completed_batch():
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        bootstrap_mean_ci(
            np.arange(2_000, dtype=float),
            n_boot=25,
            batch_size=7,
            cancelled=cancelled,
        )

    assert type(exc_info.value).__name__ == "ResearchCancelled"
    assert cancellation_checks == 2


def test_win_rate_bootstrap_propagates_batch_cancellation():
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        bootstrap_win_rate_ci(
            np.resize([True, False], 2_000),
            n_boot=25,
            batch_size=7,
            cancelled=cancelled,
        )

    assert type(exc_info.value).__name__ == "ResearchCancelled"
    assert cancellation_checks == 2


def test_bootstrap_rejects_requests_above_resource_budget():
    with pytest.raises(ValueError, match="bootstrap resource limit.*requested 1020.*budget 1000"):
        bootstrap_mean_ci(
            np.arange(20, dtype=float),
            n_boot=51,
            max_work_items=1_000,
        )
