from __future__ import annotations

import pytest


def test_strategy_consistency_panel_importable():
    pytest.importorskip("PySide6")

    from strategy_consistency_panel import StrategyConsistencyPanel

    assert hasattr(StrategyConsistencyPanel, "retranslate_ui")
    assert hasattr(StrategyConsistencyPanel, "_format_result")
