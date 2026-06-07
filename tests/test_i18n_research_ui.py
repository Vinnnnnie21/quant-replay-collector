from __future__ import annotations

import pytest

from i18n import tr


def test_research_translation_resources_default_to_chinese_and_keep_english():
    assert tr("research.tab.data_audit", "zh_CN") == "数据审计"
    assert tr("research.run", "zh_CN") == "运行研究分析"
    assert tr("research.tab.data_audit", "en_US") == "Data Audit"
    assert tr("research.run", "en_US") == "Run Research Analysis"
    assert tr("time_series.workspace", "zh_CN") == "时间序列诊断"
    assert tr("time_series.workspace", "en_US") == "Time-Series Diagnostics"
    assert tr("workspace.equity", "zh_CN") == "权益曲线"
    assert tr("time_series.pca_unavailable", "zh_CN").startswith("PCA 因子模型需要多币种收益矩阵")


def test_research_workspace_uses_language_for_visible_tabs():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from analysis_workspace import AnalysisWorkspace

    class Host(QtWidgets.QWidget):
        current_language = "zh_CN"
        session_id = "sess_test"

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    dialog = AnalysisWorkspace(host)
    assert dialog.researchTabs.tabText(0) == "数据审计"
    assert dialog.btnRunResearch.text() == "运行研究分析"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.timeSeriesTab)) == "时间序列诊断"
    assert dialog.performanceTabs.tabText(dialog.performanceTabs.indexOf(dialog.equityTab)) == "权益曲线"
    assert dialog.selectedLabelBox.currentText() == "fwd_ret_10_side_adj"
    assert dialog.researchEventTable.isSortingEnabled() is True
    visible_zh = "\n".join(
        [
            dialog.consistencyTab.toPlainText(),
            dialog.backtestTab.toPlainText(),
            dialog.premiumTab.toPlainText(),
            dialog.aiText.toPlainText(),
            dialog.sessionLabel.text(),
        ]
    )
    for residual in ("No strategy", "No backtest", "No USDT", "AI summary is reserved", "session:"):
        assert residual not in visible_zh
    dialog.app_window.current_language = "en_US"
    dialog.retranslate_ui()
    assert dialog.researchTabs.tabText(0) == "Data Audit"
    assert dialog.btnRunResearch.text() == "Run Research Analysis"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.timeSeriesTab)) == "Time-Series Diagnostics"
    assert dialog.performanceTabs.tabText(dialog.performanceTabs.indexOf(dialog.equityTab)) == "Equity"
    assert "No strategy consistency panel." in dialog.consistencyTab.toPlainText()
    dialog.close()
    app.processEvents()
