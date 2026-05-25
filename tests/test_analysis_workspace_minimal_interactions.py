from __future__ import annotations

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from analysis_workspace import AnalysisWorkspace


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"


def test_research_controls_sorting_and_single_symbol_pca_hint():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = AnalysisWorkspace(Host())

    assert dialog.selectedLabelBox.currentText() == "fwd_ret_10_side_adj"
    assert dialog.selectedLabelBox.findText("hit_tp_1pct_before_sl_1pct") >= 0
    assert dialog.researchEventTable.isSortingEnabled()
    assert dialog.factorIcTable.isSortingEnabled()
    assert dialog.ruleTable.isSortingEnabled()

    dialog.last_time_series_summary = {"factor_model": {"available": False}}
    dialog._populate_time_series_views()
    assert "PCA 因子模型需要多币种收益矩阵" in dialog.tsFactorTable.item(0, 1).text()
    assert dialog.btnRunTimeSeries.text() == "运行时间序列诊断"
    dialog.close()
    app.processEvents()
