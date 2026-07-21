from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import services.exit_outcome_comparison as service_module
from services.exit_outcome_comparison import ExitOutcomeComparisonService
from storage import StorageManager
from research.exit_outcome_comparison import (
    ExitDecisionForComparison,
    ExitOutcomeMetric,
    ExitOutcomePath,
    ExitOutcomeValue,
    ExitPairSimilarity,
    MatchedExitPair,
    OutcomeBar,
    build_exit_outcome_matrix,
    calculate_exit_outcome_path,
    global_match_exit_hold,
)


class _Storage:
    def __init__(self) -> None:
        self.saved = None
        self.outcome_reads: list[int] = []
        self.timeframes = ("1m", "5m", "15m")
        self.rows = [
            self._row("exit_1", "EXIT_NOW", "episode_1", 1_000),
            self._row("exit_2", "EXIT_NOW", "episode_2", 2_000),
            self._row("hold_1", "HOLD", "episode_3", 3_000),
            self._row("hold_2", "HOLD", "episode_4", 4_000),
        ]

    def _row(self, event_id: str, label: str, episode_id: str, cutoff: int):
        return {
            "decision_event_id": event_id,
            "blind_judgment_id": f"judgment_{event_id}",
            "blind_label": label,
            "setup_version_id": "setup_v1",
            "grouping_version_id": "grouping_v1",
            "episode_id": episode_id,
            "trade_id": f"trade_{event_id}",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "decision_timeframe": "1m",
            "context_timeframe_one": "5m",
            "context_timeframe_two": "15m",
            "decision_cutoff_utc_ms": cutoff,
        }

    def get_setup_version(self, setup_version_id):
        assert setup_version_id == "setup_v1"
        return SimpleNamespace(
            setup_version_id="setup_v1",
            direction=SimpleNamespace(value="LONG"),
            timeframes=SimpleNamespace(as_tuple=lambda: self.timeframes),
        )

    def get_episode_grouping(self, grouping_version_id):
        assert grouping_version_id == "grouping_v1"
        return object()

    def list_exit_outcome_events(self, **context):
        assert context == {
            "setup_version_id": "setup_v1",
            "grouping_version_id": "grouping_v1",
            "direction": "LONG",
        }
        return list(self.rows)

    def fetch_klines_for_range(self, **query):
        self.outcome_reads.append(int(query["start_time_utc_ms"]))
        start = int(query["start_time_utc_ms"])
        return [
            {
                "open_time_utc_ms": start + 60_000 * index,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + index / 100.0,
            }
            for index in range(20)
        ]

    def save_exit_outcome_result(self, result):
        self.saved = result

    def get_exit_outcome_result(self, comparison_id):
        if self.saved is not None and self.saved.comparison_id == comparison_id:
            return self.saved
        return None


@pytest.mark.parametrize(
    ("direction", "expected_return", "expected_mfe", "expected_mae"),
    (
        ("LONG", 0.03, 0.05, -0.01),
        ("SHORT", -0.03, 0.01, -0.05),
    ),
)
def test_exit_continuation_uses_next_bar_open_and_direction_adjustment(
    direction,
    expected_return,
    expected_mfe,
    expected_mae,
):
    path = calculate_exit_outcome_path(
        direction=direction,
        decision_cutoff_utc_ms=999,
        bars=(
            OutcomeBar(1_000, 100.0, 103.0, 99.0, 101.0),
            OutcomeBar(2_000, 101.0, 105.0, 101.0, 104.0),
            OutcomeBar(3_000, 104.0, 104.0, 100.0, 103.0),
        ),
    )

    assert path.execution_price == pytest.approx(100.0)
    assert path.value(3, ExitOutcomeMetric.CLOSE_RETURN) == pytest.approx(
        expected_return
    )
    assert path.value(3, ExitOutcomeMetric.MFE) == pytest.approx(expected_mfe)
    assert path.value(3, ExitOutcomeMetric.MAE) == pytest.approx(expected_mae)


def test_exit_continuation_does_not_replace_a_missing_next_bar_with_fill_or_later_bar():
    path = calculate_exit_outcome_path(
        direction="LONG",
        decision_cutoff_utc_ms=999,
        decision_interval_ms=1_000,
        bars=(OutcomeBar(2_000, 100.0, 101.0, 99.0, 100.0),),
        actual_fill_price=123.45,
    )

    assert path.available is False
    assert path.execution_price is None
    assert path.unavailable_reason == "next_decision_bar_missing"


def test_exit_matching_is_global_one_to_one_and_not_greedy():
    decisions = tuple(
        ExitDecisionForComparison(
            decision_event_id=event_id,
            label=label,
            setup_version_id="setup_v1",
            grouping_version_id="grouping_v1",
            episode_id=episode_id,
            trade_id=f"trade_{event_id}",
            symbol="BTCUSDT",
            direction="LONG",
            decision_timeframe="5m",
            decision_cutoff_utc_ms=cutoff,
        )
        for event_id, label, episode_id, cutoff in (
            ("exit_1", "EXIT_NOW", "episode_1", 1_000),
            ("exit_2", "EXIT_NOW", "episode_2", 2_000),
            ("hold_1", "HOLD", "episode_3", 3_000),
            ("hold_2", "HOLD", "episode_4", 4_000),
        )
    )
    similarities = tuple(
        ExitPairSimilarity(exit_id, hold_id, similarity)
        for exit_id, hold_id, similarity in (
            ("exit_1", "hold_1", 99.0),
            ("exit_1", "hold_2", 98.0),
            ("exit_2", "hold_1", 97.0),
            ("exit_2", "hold_2", 10.0),
        )
    )

    matches = global_match_exit_hold(decisions, similarities)

    assert {
        (pair.exit_now_decision_event_id, pair.hold_decision_event_id)
        for pair in matches
    } == {("exit_1", "hold_2"), ("exit_2", "hold_1")}

    with pytest.raises(ValueError, match="matched similarity"):
        MatchedExitPair(
            exit_now_decision_event_id="exit_1",
            hold_decision_event_id="hold_1",
            exit_now_episode_id="episode_1",
            hold_episode_id="episode_3",
            symbol="BTCUSDT",
            decision_timeframe="5m",
            similarity=float("nan"),
            context_distance=0.1,
            similarity_threshold=75.0,
        )


def test_exit_matrix_difference_is_registered_hold_minus_exit_now():
    pair = MatchedExitPair(
        exit_now_decision_event_id="exit_1",
        hold_decision_event_id="hold_1",
        exit_now_episode_id="episode_exit",
        hold_episode_id="episode_hold",
        symbol="BTCUSDT",
        decision_timeframe="5m",
        similarity=90.0,
        context_distance=0.1,
        similarity_threshold=75.0,
    )

    def path(value: float) -> ExitOutcomePath:
        return ExitOutcomePath(
            direction="LONG",
            execution_price=100.0,
            outcomes=tuple(
                ExitOutcomeValue(horizon, metric, value)
                for horizon in (1, 3, 5, 10, 20)
                for metric in ExitOutcomeMetric
            ),
        )

    matrix = build_exit_outcome_matrix(
        (pair,),
        {"exit_1": path(-0.02), "hold_1": path(0.03)},
        random_seed=17,
    )

    assert len(matrix) == 15
    assert all(
        cell.differences[0].value == pytest.approx(0.05)
        for cell in matrix
    )


def test_public_exit_outcome_service_matches_before_reading_outcomes(monkeypatch):
    storage = _Storage()

    def load_context(_storage, row, timeframes):
        assert timeframes == storage.timeframes
        return (row["decision_event_id"],), SimpleNamespace(
            identity=row["decision_event_id"]
        )

    def compare_contexts(left, right, **_cutoffs):
        assert storage.outcome_reads == []
        similarity = 90.0 if left[0][-1] == right[0][-1] else 85.0
        return SimpleNamespace(aggregate=SimpleNamespace(similarity=similarity))

    monkeypatch.setattr(service_module, "load_exit_structural_context", load_context)
    monkeypatch.setattr(
        service_module,
        "compare_exit_structural_snapshot_sets",
        compare_contexts,
    )
    service = ExitOutcomeComparisonService(
        storage,
        clock=lambda: datetime(2026, 7, 20, tzinfo=UTC),
        id_factory=lambda: "exit_outcome_1",
    )

    result = service.run(
        setup_version_id="setup_v1",
        grouping_version_id="grouping_v1",
        direction="LONG",
        random_seed=17,
    )

    assert storage.outcome_reads
    assert result.research_target == "EXIT"
    assert tuple(item.similarity_threshold for item in result.sensitivities) == (
        70.0,
        75.0,
        80.0,
    )
    assert len(result.primary.pairs) == 2
    assert len(result.primary.matrix) == 15
    assert {
        item.label for item in result.eligible_decisions
    } == {"EXIT_NOW", "HOLD"}
    assert all(
        difference.value == pytest.approx(0.0)
        for cell in result.primary.matrix
        for difference in cell.differences
    )
    assert service.get_result(result.comparison_id) == result


def test_schema_18_upgrade_adds_immutable_exit_outcomes_and_keeps_old_data(
    tmp_path,
):
    db_path = tmp_path / "schema_18_exit_outcomes.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    with legacy.connect() as conn:
        conn.execute(
            """
            INSERT INTO data_quality_reports (
                report_id, symbol, interval, created_at, report_json
            ) VALUES ('legacy_report', 'BTCUSDT', '1m', '2026-07-01', '{}')
            """
        )
        conn.execute("PRAGMA user_version=18")

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == 19
    assert upgraded.fetch_table(
        "data_quality_reports",
        "report_id=?",
        ("legacy_report",),
    )[0]["symbol"] == "BTCUSDT"
    with upgraded.connect() as conn:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        triggers = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
    assert {"exit_outcome_comparisons", "exit_outcome_matches"} <= tables
    assert {
        "trg_exit_outcome_comparisons_no_update",
        "trg_exit_outcome_comparisons_no_delete",
        "trg_exit_outcome_matches_no_update",
        "trg_exit_outcome_matches_no_delete",
    } <= triggers
    assert list(backup_dir.glob("*v18_to_v19*.db"))
