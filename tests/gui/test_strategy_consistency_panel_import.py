from __future__ import annotations

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from strategy_consistency.profile import StrategyProfile
from strategy_consistency_panel import (
    PROFILE_MODE_CUSTOM,
    PROFILE_MODE_DEFAULT_REVERSAL_LONG,
    PROFILE_MODE_UNDECLARED,
    StrategyConsistencyPanel,
)


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = None
    storage = None


def _panel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = StrategyConsistencyPanel(Host())
    return app, panel


def test_strategy_consistency_panel_importable():
    assert hasattr(StrategyConsistencyPanel, "retranslate_ui")
    assert hasattr(StrategyConsistencyPanel, "_format_result")


def test_panel_defaults_to_undeclared_profile_and_labels_modes():
    app, panel = _panel()
    assert panel.profileModeBox.currentData() == PROFILE_MODE_UNDECLARED
    assert panel._selected_profile() is None
    assert panel.profileModeBox.findData(PROFILE_MODE_DEFAULT_REVERSAL_LONG) >= 0
    assert panel.profileModeBox.findData(PROFILE_MODE_CUSTOM) >= 0
    panel.run_audit()
    text = panel.summaryText.toPlainText()
    assert "未声明 StrategyProfile" in text
    assert "当前只输出行为统计和样本结构" in text
    panel.close()
    app.processEvents()


def test_panel_only_uses_default_template_after_explicit_selection():
    app, panel = _panel()
    panel.profileModeBox.setCurrentIndex(panel.profileModeBox.findData(PROFILE_MODE_DEFAULT_REVERSAL_LONG))
    assert panel._selected_profile().strategy_id == "reversal_long_after_drop"
    custom = StrategyProfile(strategy_id="user_defined", name="用户自定义策略")
    panel.set_custom_profile(custom)
    assert panel.profileModeBox.currentData() == PROFILE_MODE_CUSTOM
    assert panel._selected_profile().strategy_id == "user_defined"
    panel.close()
    app.processEvents()
