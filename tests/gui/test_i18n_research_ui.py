from __future__ import annotations

import pytest
import re

from i18n import display_name, load_translations, tr
from research.setups import SetupErrorCode


def test_research_translation_resources_default_to_chinese_and_keep_english():
    assert tr("research.tab.data_audit", "zh_CN") == "数据审计"
    assert tr("research.run", "zh_CN") == "运行研究分析"
    assert tr("research.tab.data_audit", "en_US") == "Data Audit"
    assert tr("research.run", "en_US") == "Run Research Analysis"
    assert tr("time_series.workspace", "zh_CN") == "时间序列分析"
    assert tr("time_series.workspace", "en_US") == "Time-Series Analysis"
    assert tr("time_series.run", "zh_CN") == "运行时间序列分析"
    assert tr("time_series.run", "en_US") == "Run Time-Series Analysis"
    assert tr("time_series.failed", "zh_CN") == "时间序列分析失败"
    assert tr("time_series.failed", "en_US") == "Time-series analysis failed"
    assert tr("workspace.equity", "zh_CN") == "权益曲线"
    assert tr("time_series.pca_unavailable", "zh_CN").startswith("PCA 因子模型需要多币种收益矩阵")


def test_every_setup_error_code_has_chinese_and_english_user_copy():
    for code in SetupErrorCode:
        key = f"decision_research.setup.error.{code.value}"
        assert tr(key, "zh_CN") != key
        assert tr(key, "en_US") != key


def test_chinese_research_copy_uses_central_display_names_without_internal_tokens():
    assert display_name("Setup", "zh_CN") == "策略模板"
    assert display_name("Setup version", "zh_CN") == "策略模板版本"
    assert display_name("episode", "zh_CN") == "独立行情片段"
    assert display_name("ENTRY", "zh_CN") == "开仓"
    assert display_name("REJECT", "zh_CN") == "拒绝开仓"
    assert display_name("EXIT_NOW", "zh_CN") == "立即平仓"
    assert display_name("HOLD", "zh_CN") == "继续持有"
    assert display_name("entry ATR20", "zh_CN") == "开仓时 ATR20"

    visible_copy = "\n".join(load_translations("zh_CN").values())
    visible_copy = re.sub(r"\{[^{}]+\}", "", visible_copy)
    for token in (
        "Setup",
        "episode",
        "ENTRY",
        "REJECT",
        "EXIT_NOW",
        "HOLD",
        "entry ATR20",
        "Entry Logic",
        "Entry annotation",
        "review queue",
        "start_export_task",
    ):
        assert re.search(rf"(?<![A-Za-z_]){re.escape(token)}(?![A-Za-z_])", visible_copy) is None


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
    assert dialog.btnRunResearch.text() == "打开决策研究"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.researchTab)) == "历史研究结果"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.timeSeriesTab)) == "时间序列分析"
    assert not hasattr(dialog, "performanceTabs")
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
    assert dialog.btnRunResearch.text() == "Open Decision Research"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.researchTab)) == "Legacy Research Results"
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.timeSeriesTab)) == "Time-Series Analysis"
    assert not hasattr(dialog, "performanceTabs")
    assert "No strategy consistency panel." in dialog.consistencyTab.toPlainText()
    dialog.close()
    app.processEvents()
