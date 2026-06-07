from __future__ import annotations

import pandas as pd

from research.matched_baseline import (
    MatchedBaselineSpec,
    build_match_pool,
    select_matched_controls,
)
from research.observation_universe import (
    create_matched_control_observation,
    generate_deep_v_observation_universe,
)
from storage import StorageManager


def _deep_v_klines() -> pd.DataFrame:
    rows = []
    for idx in range(35):
        close = 100.0 - idx * 0.35
        rows.append(
            {
                "bar_index": idx,
                "open_time_bjt": f"2026-05-27T10:{idx:02d}:00+08:00",
                "open": close + 0.1,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": 100.0,
            }
        )
    rows[25].update(
        {
            "open": 91.0,
            "high": 93.0,
            "low": 86.0,
            "close": 92.0,
            "volume": 420.0,
        }
    )
    return pd.DataFrame(rows)


def test_generates_stable_deep_v_candidates_and_scheduled_no_action_samples():
    klines = _deep_v_klines()

    rows = generate_deep_v_observation_universe(
        klines,
        session_id="session_1",
        symbol="BTCUSDT",
        interval="1m",
        strategy_id="LONG_DEEP_V_REVERSAL",
        created_at="2026-05-27T02:00:00+00:00",
    )
    rerun = generate_deep_v_observation_universe(
        klines,
        session_id="session_1",
        symbol="BTCUSDT",
        interval="1m",
        strategy_id="LONG_DEEP_V_REVERSAL",
        created_at="2026-05-27T02:00:00+00:00",
    )

    assert [row["sample_id"] for row in rows] == [row["sample_id"] for row in rerun]
    assert [row["bar_index"] for row in rows] == sorted(row["bar_index"] for row in rows)
    assert any(row["source_type"] == "AUTO_CANDIDATE" for row in rows)
    assert any(row["source_type"] == "SCHEDULED_BAR" for row in rows)

    candidate = next(row for row in rows if row["bar_index"] == 25)
    assert candidate["source_type"] == "AUTO_CANDIDATE"
    assert candidate["user_action"] == "NO_ACTION"
    assert candidate["is_candidate"] == 1
    assert candidate["is_user_trade"] == 0
    assert candidate["profile_id"] == "LONG_DEEP_V_REVERSAL"
    assert candidate["event_time_bjt"] == "2026-05-27T10:25:00+08:00"


def test_no_action_candidates_can_be_saved_without_mixing_user_trades(tmp_path):
    storage = StorageManager(tmp_path / "deep_v_universe.db")
    rows = generate_deep_v_observation_universe(
        _deep_v_klines(),
        session_id="session_2",
        symbol="BTCUSDT",
        interval="1m",
        strategy_id="LONG_DEEP_V_REVERSAL",
        user_actions_by_bar={25: "OPEN_LONG"},
        created_at="2026-05-27T02:00:00+00:00",
    )
    control = create_matched_control_observation(
        session_id="session_2",
        symbol="BTCUSDT",
        interval="1m",
        bar_index=28,
        profile_id="LONG_DEEP_V_REVERSAL",
        event_time_bjt="2026-05-27T10:28:00+08:00",
        created_at="2026-05-27T02:00:00+00:00",
    )

    for row in [*rows, control]:
        storage.save_observation_sample(row)

    stored = storage.list_observation_samples(session_id="session_2")
    user_trade = next(row for row in stored if row["user_action"] == "OPEN_LONG")
    matched_control = next(row for row in stored if row["source_type"] == "MATCHED_CONTROL")
    no_action_rows = [row for row in stored if row["user_action"] == "NO_ACTION"]

    assert user_trade["source_type"] == "USER_TRADE"
    assert user_trade["is_user_trade"] == 1
    assert user_trade["side"] == "LONG"
    assert matched_control["is_matched_control"] == 1
    assert all(row["is_user_trade"] == 0 for row in no_action_rows)


def test_future_columns_do_not_change_deep_v_candidate_selection():
    klines = _deep_v_klines()
    optimistic = klines.assign(fwd_ret_20=999.0, future_close=99999.0)
    pessimistic = klines.assign(fwd_ret_20=-999.0, future_close=0.01)

    optimistic_rows = generate_deep_v_observation_universe(
        optimistic,
        session_id="session_3",
        symbol="BTCUSDT",
        interval="1m",
        strategy_id="LONG_DEEP_V_REVERSAL",
    )
    pessimistic_rows = generate_deep_v_observation_universe(
        pessimistic,
        session_id="session_3",
        symbol="BTCUSDT",
        interval="1m",
        strategy_id="LONG_DEEP_V_REVERSAL",
    )

    assert [
        (row["sample_id"], row["source_type"], row["user_action"])
        for row in optimistic_rows
    ] == [
        (row["sample_id"], row["source_type"], row["user_action"])
        for row in pessimistic_rows
    ]
    assert not any(
        any(token in key.lower() for token in ("fwd", "future", "post", "mfe", "mae", "label"))
        for row in optimistic_rows
        for key in row
    )


def test_matched_baseline_can_use_generated_no_action_controls():
    observations = pd.DataFrame(
        generate_deep_v_observation_universe(
            _deep_v_klines(),
            session_id="session_4",
            symbol="BTCUSDT",
            interval="1m",
            strategy_id="LONG_DEEP_V_REVERSAL",
            user_actions_by_bar={25: "OPEN_LONG"},
        )
    )
    context_features = pd.DataFrame(
        [
            {
                "sample_id": row.sample_id,
                "feature_name": feature_name,
                "lookback_bars": 20,
                "feature_value": value,
            }
            for row in observations.itertuples()
            for feature_name, value in (
                ("pre_simple_ret", -0.02 if row.bar_index in {24, 25, 26} else -0.01),
                ("realized_vol", 0.01),
                ("volume_zscore", 2.0 if row.bar_index in {24, 25, 26} else 0.5),
                ("trend_regime", "UP"),
                ("volatility_regime", "NORMAL"),
                ("time_session", "ASIA"),
            )
        ]
    )

    pool = build_match_pool(observations, context_features)
    user_sample_id = observations.loc[observations["user_action"] == "OPEN_LONG", "sample_id"].iloc[0]
    controls = select_matched_controls(
        user_sample_id,
        pool,
        MatchedBaselineSpec(
            controls_per_sample=2,
            min_controls_per_sample=1,
            numeric_features=("pre_ret_20", "realized_vol_20", "volume_zscore_20"),
        ),
    )

    assert not controls.empty
    assert user_sample_id not in set(controls["control_sample_id"])
    assert set(controls["source_type"]).issubset({"SCHEDULED_BAR", "AUTO_CANDIDATE", "MATCHED_CONTROL"})
    assert set(controls["user_action"]).issubset({"NO_ACTION", "HOLD"})
