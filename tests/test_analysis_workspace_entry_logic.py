from __future__ import annotations

import json
from pathlib import Path

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from analysis_workspace import AnalysisWorkspace


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "session_entry"

    def __init__(self) -> None:
        super().__init__()
        self.export_calls: list[tuple[Path, object, str, str]] = []
        self.storage = FakeStorage()
        self.jump_calls: list[int] = []

    def start_export_task(self, target, on_success=None, language=None, selected_label="fwd_ret_10_side_adj"):
        self.export_calls.append((Path(target), on_success, language, selected_label))
        return True

    def jump_to_bar(self, bar_index: int):
        self.jump_calls.append(int(bar_index))


class FakeStorage:
    def __init__(self) -> None:
        self.saved_annotations: list[dict] = []

    def save_entry_annotation(self, row: dict) -> None:
        self.saved_annotations.append(dict(row))


def test_entry_logic_report_button_uses_background_export_task(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    dialog = AnalysisWorkspace(host)

    dialog.run_entry_logic_report()

    assert len(host.export_calls) == 1
    target, callback, language, selected_label = host.export_calls[0]
    assert target.name == "exports"
    assert callable(callback)
    assert language == "zh_CN"
    assert selected_label == dialog.selectedLabelBox.currentText()
    assert "Entry Logic" in dialog.entryLogicHint.text()

    dialog.close()
    host.close()
    app.processEvents()


def test_entry_logic_export_output_is_loaded_into_summary_and_queue(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    export_dir = tmp_path / "session_entry"
    export_dir.mkdir()
    (export_dir / "entry_logic_report.json").write_text(
        json.dumps(
            {
                "annotation_overview": {
                    "ENTRY": 2,
                    "REJECT": 1,
                    "UNCERTAIN": 0,
                    "UNLABELED": 4,
                },
                "warnings": ["empty_input"],
                "review_queue_top_k": [
                    {
                        "observation_id": "obs_1",
                        "human_entry_similarity": 0.87,
                        "setup_confidence": 0.81,
                        "review_reason": "high_similarity",
                        "review_mode": "high_similarity",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "entry_logic_report.md").write_text("# Entry Logic Research Report\n", encoding="utf-8")
    (export_dir / "entry_review_queue.csv").write_text(
        "observation_id,human_entry_similarity,setup_confidence,review_reason,review_mode\n"
        "obs_1,0.87,0.81,high_similarity,high_similarity\n",
        encoding="utf-8",
    )

    dialog = AnalysisWorkspace(Host())
    dialog._entry_logic_export_finished(export_dir)

    assert "ENTRY: 2" in dialog.entryLogicSummary.text()
    assert "REJECT: 1" in dialog.entryLogicSummary.text()
    assert "UNLABELED: 4" in dialog.entryLogicSummary.text()
    assert "empty_input" in dialog.entryLogicHint.text()
    assert dialog.entryReviewQueueTable.rowCount() == 1
    assert dialog.entryReviewQueueTable.item(0, 0).text() == "obs_1"
    assert dialog.entryLogicReportText.toPlainText().startswith("# Entry Logic Research Report")

    dialog.close()
    app.processEvents()

def test_entry_review_queue_selection_jumps_to_decision_bar(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    export_dir = tmp_path / "session_entry"
    export_dir.mkdir()
    (export_dir / "entry_logic_report.json").write_text(
        json.dumps({"annotation_overview": {"ENTRY": 0, "REJECT": 0, "UNCERTAIN": 0, "UNLABELED": 1}}),
        encoding="utf-8",
    )
    (export_dir / "entry_review_queue.csv").write_text(
        "observation_id,human_entry_similarity,setup_confidence,review_reason,review_mode,"
        "session_id,symbol,interval,setup_bar_index,decision_bar_index,decision_timing,lower_shadow_ratio\n"
        "obs_1,0.87,0.81,high_similarity,high_similarity,session_entry,BTCUSDT,1m,9,10,NEXT_BAR_CONFIRMATION,0.82\n",
        encoding="utf-8",
    )
    host = Host()
    dialog = AnalysisWorkspace(host)
    dialog._entry_logic_export_finished(export_dir)

    dialog.entryReviewQueueTable.selectRow(0)
    app.processEvents()

    assert host.jump_calls[-1] == 10
    assert "setup_bar_index" in dialog.entryCandidateDetail.toPlainText()
    assert "lower_shadow_ratio" in dialog.entryFeatureText.toPlainText()

    dialog.close()
    host.close()
    app.processEvents()


def test_entry_review_annotation_save_updates_queue_without_full_refresh(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    export_dir = tmp_path / "session_entry"
    export_dir.mkdir()
    (export_dir / "entry_logic_report.json").write_text(
        json.dumps({"annotation_overview": {"ENTRY": 0, "REJECT": 0, "UNCERTAIN": 0, "UNLABELED": 1}}),
        encoding="utf-8",
    )
    (export_dir / "entry_review_queue.csv").write_text(
        "observation_id,human_entry_similarity,setup_confidence,review_reason,review_mode,"
        "session_id,symbol,interval,setup_bar_index,decision_bar_index,decision_timing,lower_shadow_ratio\n"
        "obs_1,0.87,0.81,high_similarity,high_similarity,session_entry,BTCUSDT,1m,9,10,NEXT_BAR_CONFIRMATION,0.82\n",
        encoding="utf-8",
    )
    host = Host()
    dialog = AnalysisWorkspace(host)
    dialog._entry_logic_export_finished(export_dir)
    dialog.entryConfidenceSpin.setValue(5)
    dialog.entryReasonTagsEdit.setText("long_lower_shadow")
    dialog.entryNoteEdit.setPlainText("accepted in review")

    dialog._save_entry_logic_annotation("ENTRY")

    assert len(host.storage.saved_annotations) == 1
    assert host.storage.saved_annotations[0]["human_decision"] == "ENTRY"
    assert host.storage.saved_annotations[0]["decision_bar_index"] == 10
    assert dialog.entryReviewQueueTable.rowCount() == 0
    assert "没有待复标候选" in dialog.entryLogicHint.text()

    dialog.close()
    host.close()
    app.processEvents()
