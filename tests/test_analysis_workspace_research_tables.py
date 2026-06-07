from __future__ import annotations

import json

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from analysis_workspace import AnalysisWorkspace


class Host(QtWidgets.QWidget):
    current_language = "en_US"
    session_id = "session_test"


def test_research_output_is_presented_as_tables(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "data_audit.json").write_text(
        json.dumps({"sample_count": 12, "leakage_audit_status": "PASS", "small_sample_warning": "severe: n < 30"}),
        encoding="utf-8",
    )
    (research_dir / "event_study_summary.csv").write_text(
        "group_by,sample_count,mean,small_sample_warning\nside,12,0.1,severe\n",
        encoding="utf-8",
    )
    for name in ("factor_binning_summary.csv", "factor_ic_summary.csv", "candidate_rules.csv", "walk_forward_results.csv"):
        (research_dir / name).write_text("warning\nsmall sample\n", encoding="utf-8")
    (research_dir / "research_report.md").write_text("# Quant Research Report\n", encoding="utf-8")

    dialog = AnalysisWorkspace(Host())
    dialog.last_research_dir = research_dir
    dialog._load_research_views()

    assert dialog.auditTable.rowCount() > 0
    assert dialog.researchEventTable.rowCount() == 1
    assert dialog.factorBinningTable.rowCount() == 1
    assert "Leakage audit: PASS" in dialog.researchWarning.text()
    assert dialog.reportText.toPlainText().startswith("# Quant Research Report")
    dialog.close()
    app.processEvents()


def test_analysis_workspace_exposes_selected_candidate_for_backtest_params(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "candidate_rules.csv").write_text(
        'readable_rule,conditions_json,test_score\n'
        '"deep V","[{""column"": ""pre_ret_5"", ""op"": ""<="", ""value"": -0.04}]",0.2\n',
        encoding="utf-8",
    )

    dialog = AnalysisWorkspace(Host())
    dialog.last_research_dir = research_dir
    dialog._load_research_views()
    selected = dialog.selected_candidate_rule_params()

    assert selected == {
        "conditions_json": '[{"column": "pre_ret_5", "op": "<=", "value": -0.04}]'
    }
    dialog.close()
    app.processEvents()
