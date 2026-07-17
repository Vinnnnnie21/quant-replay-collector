from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

try:
    from app_config import APP_VERSION
except ImportError:  # pragma: no cover - package import path
    from ..app_config import APP_VERSION
from .cancellation import raise_if_research_cancelled


DEFAULT_RANDOM_SEED = 42
BOOTSTRAP_METHOD_VERSION = "bootstrap_v2"
DEFAULT_RESAMPLE_BATCH_SIZE = 256
MAX_BATCH_WORK_ITEMS = 1_000_000
MAX_RESAMPLE_WORK_ITEMS = 50_000_000
MAX_SIMULATION_COUNT = 1_000_000


def _values(values: Any) -> np.ndarray:
    raw = pd.Series(values, dtype="object")
    if raw.empty:
        return np.asarray([], dtype=float)
    numeric = pd.to_numeric(raw, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError(
            "bootstrap data quality gate rejected input: NaN or infinite values; "
            "reload source data or inspect the data quality report"
        )
    return numeric


def _empty_result(warning: str, settings: dict | None = None) -> dict:
    return {
        "estimate": math.nan,
        "ci_low": math.nan,
        "ci_high": math.nan,
        "sample_count": 0,
        "warning": warning,
        **(settings or {}),
    }


def bootstrap_mean_ci(
    values,
    n_boot: int = 1000,
    ci: float = 0.95,
    random_state: int | None = DEFAULT_RANDOM_SEED,
    batch_size: int = DEFAULT_RESAMPLE_BATCH_SIZE,
    max_work_items: int = MAX_RESAMPLE_WORK_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    observations = _values(values)
    seed = DEFAULT_RANDOM_SEED if random_state is None else int(random_state)
    configured_batch_size = _positive_integer(batch_size, "batch_size")
    simulation_count, budget, work_items = validate_resampling_request(
        "bootstrap",
        n_boot,
        len(observations),
        max_work_items=max_work_items,
    )
    confidence = _confidence(ci)
    settings = {
        "random_seed": seed,
        "simulation_count": simulation_count,
        "confidence": confidence,
        "application_version": APP_VERSION,
        "method_version": BOOTSTRAP_METHOD_VERSION,
        "work_items": work_items,
        "resource_budget": budget,
        "max_batch_work_items": MAX_BATCH_WORK_ITEMS,
    }
    if not len(observations):
        return _empty_result(
            "empty sample",
            {**settings, "batch_size": 0, "batch_count": 0},
        )
    warning = "small sample; interval is unstable" if len(observations) < 30 else ""
    rng = np.random.default_rng(seed)
    effective_batch_size = min(
        simulation_count,
        configured_batch_size,
        max(1, MAX_BATCH_WORK_ITEMS // len(observations)),
    )
    draws = np.empty(simulation_count, dtype=float)
    raise_if_research_cancelled(cancelled)
    for start in range(0, simulation_count, effective_batch_size):
        stop = min(simulation_count, start + effective_batch_size)
        draws[start:stop] = rng.choice(
            observations,
            size=(stop - start, len(observations)),
            replace=True,
        ).mean(axis=1)
        raise_if_research_cancelled(cancelled)
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(draws, [alpha, 1.0 - alpha])
    return {
        "estimate": float(np.mean(observations)),
        "ci_low": float(low),
        "ci_high": float(high),
        "sample_count": int(len(observations)),
        "warning": warning,
        **settings,
        "batch_size": effective_batch_size,
        "batch_count": math.ceil(simulation_count / effective_batch_size),
    }


def bootstrap_win_rate_ci(
    values,
    n_boot: int = 1000,
    ci: float = 0.95,
    random_state: int | None = DEFAULT_RANDOM_SEED,
    batch_size: int = DEFAULT_RESAMPLE_BATCH_SIZE,
    max_work_items: int = MAX_RESAMPLE_WORK_ITEMS,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    observations = _values(values)
    binary = (observations > 0).astype(float)
    result = bootstrap_mean_ci(
        binary,
        n_boot=n_boot,
        ci=ci,
        random_state=random_state,
        batch_size=batch_size,
        max_work_items=max_work_items,
        cancelled=cancelled,
    )
    if result["sample_count"]:
        result["estimate"] *= 100.0
        result["ci_low"] *= 100.0
        result["ci_high"] *= 100.0
    return result


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if result <= 0 or float(value) != result:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _confidence(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be between zero and one") from exc
    if not math.isfinite(result) or not 0.0 < result < 1.0:
        raise ValueError("confidence must be between zero and one")
    return result


def validate_resampling_request(
    method: str,
    simulation_count: Any,
    sample_count: int,
    *,
    max_work_items: int = MAX_RESAMPLE_WORK_ITEMS,
) -> tuple[int, int, int]:
    count = _positive_integer(simulation_count, "simulation_count")
    if count > MAX_SIMULATION_COUNT:
        raise ValueError(
            f"{method} resource limit exceeded: requested {count} simulations, "
            f"maximum is {MAX_SIMULATION_COUNT}"
        )
    budget = min(_positive_integer(max_work_items, "max_work_items"), MAX_RESAMPLE_WORK_ITEMS)
    work_items = count * max(0, int(sample_count))
    if work_items > budget:
        raise ValueError(
            f"{method} resource limit exceeded: requested {work_items} work items, budget {budget}; "
            "reduce the sample size or simulation count"
        )
    return count, budget, work_items
