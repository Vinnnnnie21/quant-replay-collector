from __future__ import annotations

from pathlib import Path

from export_controller import ExportController
from premium_controller import PremiumController
from replay_controller import ReplayController
from trade_controller import TradeController


def test_replay_controller_moves_and_stops_at_end():
    replay = ReplayController(playing=True)
    changed = replay.tick(3.0, length=3, speed=1.0)
    assert changed is True
    assert replay.cursor == 2
    assert replay.playing is False
    assert replay.step(3) == 2


def test_premium_controller_prevents_duplicate_inflight_and_saves_result():
    class Storage:
        saved = None

        def insert_premium_sample(self, row):
            self.saved = row

    storage = Storage()
    controller = PremiumController()
    assert controller.begin_sample() is True
    assert controller.begin_sample() is False
    controller.complete_sample({"sample_status": "ERROR", "error_message": "offline"}, storage)
    assert controller.inflight is False
    assert controller.last_error == "offline"
    assert storage.saved["sample_status"] == "ERROR"


def test_export_and_trade_controllers_are_pure_boundaries(tmp_path):
    class Exporter:
        def export_session(self, session_id, target):
            assert session_id == "s1"
            return Path(target) / "session_s1"

    result = ExportController(Exporter()).export_session("s1", tmp_path)
    settings = TradeController.execution_settings("close", 4, 1, 1000)
    assert result.ok is True
    assert result.output_dir.name == "session_s1"
    assert settings.fill_mode == "CLOSE"
