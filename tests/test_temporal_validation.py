
from __future__ import annotations

import inspect
import json

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import quant_collector_app.research.temporal_validation as temporal_validation
from quant_collector_app.research.temporal_validation import (
    SplitResult,
    WalkForwardSplitResult,
    _resolve_bar_col,
    apply_embargo,
    apply_embargo_against_eval,
    assign_episode_id,
    build_purged_chronological_split,
    build_purged_walk_forward_splits,
    chronological_train_val_test_split,
    ensure_label_window,
    purge_overlapping_label_windows,
    purge_train_against_eval,
    summarize_split,
    validate_split_integrity,
    walk_forward_splits,
    windows_overlap,
)


def _samples(count: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"obs_{index:03d}" for index in range(count)],
            "symbol": ["BTCUSDT"] * count,
            "interval": ["1m"] * count,
            "bar_index": list(range(count)),
            "bar_time": pd.date_range("2026-01-01", periods=count, freq="h"),
        }
    )


def _with_labels(frame: pd.DataFrame, horizon: int = 2) -> pd.DataFrame:
    return ensure_label_window(frame, horizon_bars=horizon)


def test_resolve_bar_col_prefers_decision_bar_index_and_rejects_missing_or_nan():
    frame = _samples(3).assign(decision_bar_index=[10, 11, 12])
    assert _resolve_bar_col(frame) == "decision_bar_index"
    assert _resolve_bar_col(_samples(3)) == "bar_index"

    with pytest.raises(ValueError, match="decision_bar_index or bar_index"):
        _resolve_bar_col(pd.DataFrame({"observation_id": ["obs"]}))

    with pytest.raises(ValueError, match="must not contain NaN"):
        _resolve_bar_col(_samples(3).assign(decision_bar_index=[1, None, 3]))


def test_ensure_label_window_generates_windows_without_modifying_input():
    samples = _samples(3)
    original = samples.copy(deep=True)

    labeled = ensure_label_window(samples, horizon_bars=5)

    assert labeled["label_start_bar"].tolist() == [1, 2, 3]
    assert labeled["label_end_bar"].tolist() == [5, 6, 7]
    assert "label_start_bar" not in samples.columns
    assert_frame_equal(samples, original)


def test_ensure_label_window_preserves_existing_unless_overwrite_enabled():
    samples = _samples(2).assign(label_start_bar=[100, 200], label_end_bar=[110, 210])

    preserved = ensure_label_window(samples, horizon_bars=5)
    overwritten = ensure_label_window(samples, horizon_bars=5, allow_overwrite=True)

    assert preserved["label_start_bar"].tolist() == [100, 200]
    assert overwritten["label_start_bar"].tolist() == [1, 2]
    assert overwritten["label_end_bar"].tolist() == [5, 6]


def test_windows_overlap_uses_closed_intervals_and_missing_values_are_false():
    assert windows_overlap(1, 3, 3, 5) is True
    assert windows_overlap(1, 2, 3, 5) is False
    assert windows_overlap(1, 5, 2, 3) is True
    assert windows_overlap(None, 5, 2, 3) is False


def test_purge_train_against_eval_removes_train_windows_overlapping_eval():
    train = pd.DataFrame(
        {
            "observation_id": ["train_10", "train_15", "train_30"],
            "bar_index": [10, 15, 30],
            "label_start_bar": [11, 16, 31],
            "label_end_bar": [20, 25, 40],
        }
    )
    evaluation = pd.DataFrame(
        {
            "observation_id": ["val_18"],
            "bar_index": [18],
            "label_start_bar": [18],
            "label_end_bar": [24],
        }
    )
    original_train = train.copy(deep=True)

    purged, summary = purge_train_against_eval(train, evaluation)

    assert purged["observation_id"].tolist() == ["train_30"]
    assert summary == {
        "original_train_count": 3,
        "eval_count": 1,
        "purged_count": 2,
        "remaining_train_count": 1,
    }
    assert_frame_equal(train, original_train)


def test_apply_embargo_against_eval_removes_train_samples_near_eval_range():
    train = _samples(10)
    evaluation = _samples(3).assign(bar_index=[10, 11, 12], observation_id=["val_10", "val_11", "val_12"])

    embargoed_train, summary = apply_embargo_against_eval(train, evaluation, embargo_bars=2)

    assert embargoed_train["bar_index"].tolist() == list(range(8))
    assert summary["embargoed_count"] == 2
    assert summary["remaining_train_count"] == 8


def test_apply_embargo_against_eval_zero_embargo_returns_copy():
    train = _samples(5)
    evaluation = _samples(2).assign(bar_index=[5, 6])

    output, summary = apply_embargo_against_eval(train, evaluation, embargo_bars=0)

    assert_frame_equal(output, train.reset_index(drop=True))
    assert output is not train
    assert summary["embargoed_count"] == 0


def test_assign_episode_id_groups_nearby_candidates_by_symbol_and_interval():
    samples = pd.DataFrame(
        {
            "observation_id": ["btc_8", "eth_2", "btc_3", "btc_1"],
            "symbol": ["BTCUSDT", "ETHUSDT", "BTCUSDT", "BTCUSDT"],
            "interval": ["1m", "1m", "1m", "1m"],
            "bar_index": [8, 2, 3, 1],
        }
    )

    episodes = assign_episode_id(samples, max_gap_bars=2)
    by_id = dict(zip(episodes["observation_id"], episodes["episode_id"]))

    assert by_id["btc_1"] == by_id["btc_3"]
    assert by_id["btc_8"] != by_id["btc_1"]
    assert by_id["btc_1"].startswith("BTCUSDT|1m|ep_")
    assert by_id["eth_2"].startswith("ETHUSDT|1m|ep_")


def test_build_purged_chronological_split_keeps_time_order_and_reports_counts():
    samples = _samples(20)

    split = build_purged_chronological_split(
        samples,
        train_ratio=0.5,
        validation_ratio=0.25,
        test_ratio=0.25,
        horizon_bars=2,
        embargo_bars=2,
    )

    assert isinstance(split, SplitResult)
    assert split.summary["split_method"] == "purged_chronological"
    assert split.train["bar_index"].tolist() == list(range(8))
    assert split.validation["bar_index"].tolist() == [10, 11, 12, 13, 14]
    assert split.test["bar_index"].tolist() == [15, 16, 17, 18, 19]
    assert split.summary["purged_count"] == 1
    assert split.summary["embargoed_count"] == 1
    assert split.summary["horizon_bars"] == 2
    assert split.summary["embargo_bars"] == 2
    assert split.summary["label_window_overlap_count"] == 0
    assert split.summary["bar_index_ranges"]["train"]["max"] < split.summary["bar_index_ranges"]["validation"]["min"]
    json.dumps(summarize_split(split))


def test_build_purged_chronological_split_can_use_legacy_val_ratio_name():
    split = build_purged_chronological_split(
        _samples(12),
        train_ratio=0.5,
        val_ratio=0.25,
        test_ratio=0.25,
        label_horizon_bars=1,
    )

    assert split["val"]["bar_index"].tolist() == [6, 7, 8]
    assert split["split_method"] == "purged_chronological"


def test_validate_split_integrity_detects_episode_leakage_and_label_overlap():
    train = pd.DataFrame(
        {
            "observation_id": ["train_a"],
            "bar_index": [1],
            "label_start_bar": [2],
            "label_end_bar": [4],
            "episode_id": ["episode_a"],
        }
    )
    validation = pd.DataFrame(
        {
            "observation_id": ["val_a"],
            "bar_index": [3],
            "label_start_bar": [3],
            "label_end_bar": [5],
            "episode_id": ["episode_a"],
        }
    )
    test = pd.DataFrame(
        {
            "observation_id": ["test_a"],
            "bar_index": [6],
            "label_start_bar": [7],
            "label_end_bar": [8],
            "episode_id": ["episode_b"],
        }
    )
    split = SplitResult(train=train, validation=validation, test=test, summary={}, warnings=[])

    report = validate_split_integrity(split)

    assert report["is_valid"] is False
    assert report["status"] == "FAIL"
    assert report["episode_leakage_count"] == 1
    assert report["label_window_overlap_count"] == 1
    assert "episode_leakage" in report["warnings"]
    assert "label_window_overlap" in report["warnings"]


def test_chronological_split_keeps_legacy_dict_interface_and_allows_optional_bar_time():
    samples = _samples(10).drop(columns=["bar_time"])
    split = chronological_train_val_test_split(samples, 0.5, 0.3, 0.2)

    assert split["train"]["bar_index"].tolist() == [0, 1, 2, 3, 4]
    assert split["val"]["bar_index"].tolist() == [5, 6, 7]
    assert split["test"]["bar_index"].tolist() == [8, 9]


def test_walk_forward_splits_keep_legacy_dict_interface():
    splits = walk_forward_splits(_samples(12), train_window=4, val_window=2, test_window=2, step=2)

    assert len(splits) == 3
    assert splits[0]["train"]["bar_index"].tolist() == [0, 1, 2, 3]
    assert splits[0]["val"]["bar_index"].tolist() == [4, 5]
    assert splits[0]["test"]["bar_index"].tolist() == [6, 7]
    assert splits[1]["train"]["bar_index"].tolist() == [2, 3, 4, 5]


def test_build_purged_walk_forward_splits_generates_multiple_folds_with_summary():
    result = build_purged_walk_forward_splits(
        _samples(18),
        train_window=5,
        validation_window=2,
        test_window=2,
        step=3,
        horizon_bars=1,
        embargo_bars=1,
        episode_gap_bars=1,
    )

    assert isinstance(result, WalkForwardSplitResult)
    assert len(result) == 4
    assert result.summary["split_method"] == "purged_walk_forward"
    assert result.summary["fold_count"] == 4
    assert result[0].summary["fold_index"] == 0
    assert result[0]["train"]["bar_index"].tolist() == [0, 1, 2, 3]
    assert result[0]["val"]["bar_index"].tolist() == [5, 6]
    assert result[0]["test"]["bar_index"].tolist() == [7, 8]
    json.dumps(result.summary)
    json.dumps(result[0].summary)


def test_build_purged_walk_forward_splits_small_sample_returns_empty_result_with_warning():
    result = build_purged_walk_forward_splits(
        _samples(5),
        train_window=4,
        validation_window=2,
        test_window=2,
        step=1,
        horizon_bars=1,
    )

    assert isinstance(result, WalkForwardSplitResult)
    assert result.folds == []
    assert result.summary["fold_count"] == 0
    assert "insufficient_samples_for_walk_forward" in result.warnings


def test_chronological_split_small_sample_raises_clear_error():
    with pytest.raises(ValueError, match="at least 3 samples"):
        chronological_train_val_test_split(_samples(2), 0.5, 0.25, 0.25)


def test_unsorted_input_is_sorted_without_modifying_input():
    samples = _samples(10).iloc[::-1].reset_index(drop=True)
    original = samples.copy(deep=True)

    split = chronological_train_val_test_split(samples, 0.5, 0.3, 0.2)

    assert split["train"]["bar_index"].tolist() == [0, 1, 2, 3, 4]
    assert_frame_equal(samples, original)


def test_build_purged_chronological_split_does_not_modify_input():
    samples = _samples(12)
    original = samples.copy(deep=True)

    build_purged_chronological_split(
        samples,
        train_ratio=0.5,
        validation_ratio=0.25,
        test_ratio=0.25,
        horizon_bars=2,
        embargo_bars=1,
        episode_gap_bars=1,
    )

    assert_frame_equal(samples, original)


def test_purge_overlapping_label_windows_keeps_non_overlapping_closed_windows():
    samples = pd.DataFrame(
        {
            "observation_id": ["obs_10", "obs_15", "obs_21"],
            "bar_index": [10, 15, 21],
            "label_start_bar": [11, 16, 22],
            "label_end_bar": [20, 25, 30],
        }
    )

    purged = purge_overlapping_label_windows(samples, horizon_bars=10)

    assert purged["observation_id"].tolist() == ["obs_10", "obs_21"]


def test_apply_embargo_legacy_api_removes_validation_and_test_boundary_rows():
    split = chronological_train_val_test_split(_samples(10), 0.5, 0.3, 0.2)

    embargoed = apply_embargo(split, embargo_bars=1)

    assert embargoed["train"]["bar_index"].tolist() == [0, 1, 2, 3, 4]
    assert embargoed["val"]["bar_index"].tolist() == [6, 7]
    assert embargoed["test"]["bar_index"].tolist() == [9]
    assert embargoed["embargoed"]["bar_index"].tolist() == [5, 8]


def test_build_purged_chronological_split_requires_non_empty_ratio_buckets():
    with pytest.raises(ValueError, match="empty train, validation, or test"):
        build_purged_chronological_split(
            _samples(4),
            train_ratio=0.8,
            validation_ratio=0.1,
            test_ratio=0.1,
            horizon_bars=1,
        )


def test_public_interfaces_do_not_expose_random_split_options_or_shuffle_paths():
    functions = [
        chronological_train_val_test_split,
        walk_forward_splits,
        apply_embargo,
        apply_embargo_against_eval,
        purge_overlapping_label_windows,
        purge_train_against_eval,
        build_purged_chronological_split,
        build_purged_walk_forward_splits,
        assign_episode_id,
        validate_split_integrity,
        summarize_split,
    ]

    for function in functions:
        parameters = inspect.signature(function).parameters
        assert "shuffle" not in parameters
        assert "random_state" not in parameters

    source = inspect.getsource(temporal_validation)
    assert "shuffle=True" not in source
    assert "random_state" not in source

    with pytest.raises(TypeError):
        chronological_train_val_test_split(_samples(10), 0.5, 0.3, 0.2, shuffle=True)
