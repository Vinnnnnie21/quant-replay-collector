from __future__ import annotations

from types import SimpleNamespace

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from research.entry_behavior_model import (
    BehaviorModelTarget,
    EntryBehaviorTrainingRequest,
)
from views.decision_research_workspace import DecisionResearchWorkspace
from views.entry_behavior_model_workspace import EntryBehaviorModelWorkspace


class _BehaviorController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.start_calls = []
        self.is_running = False
        self.invalidations = 0

    def start(self, request) -> int:
        self.start_calls.append(request)
        self.is_running = True
        return len(self.start_calls)

    def cancel(self) -> None:
        self.is_running = False

    def invalidate(self) -> None:
        self.invalidations += 1
        self.is_running = False


class _BehaviorService:
    def list_models(self, **_context):
        return ()

    def model_freshness(self, model_version_id, **_context):
        return SimpleNamespace(
            model_version_id=model_version_id,
            needs_retraining=False,
            new_label_count=0,
            message_zh="模型已包含当前全部合格盲态标签。",
        )


def test_behavior_training_is_blocked_until_research_operation_gate_is_ready():
    app = QtWidgets.QApplication.instance()
    assert app is not None
    controller = _BehaviorController()
    page = EntryBehaviorModelWorkspace(
        service=_BehaviorService(),
        controller=controller,
        language="zh_CN",
    )
    page.set_research_context(
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
    )

    assert page.trainButton.isEnabled() is False
    page.trainButton.click()
    assert controller.start_calls == []

    page.set_training_operation_gate(
        allowed=False,
        message="附加原始字段仍有差额：15m 成交笔数 3 行。",
    )
    assert "成交笔数 3 行" in page.trainingGateLabel.text()

    page.set_training_operation_gate(allowed=True, message="")
    assert page.trainButton.isEnabled() is True
    assert page.trainingGateLabel.isHidden()


def test_behavior_workspace_trains_explicitly_and_renders_neutral_model_audit():
    app = QtWidgets.QApplication.instance()
    assert app is not None
    controller = _BehaviorController()
    page = EntryBehaviorModelWorkspace(
        service=_BehaviorService(),
        controller=controller,
        language="zh_CN",
    )
    page.set_research_context(
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
    )
    page.set_training_operation_gate(allowed=True, message="")

    page.trainButton.click()

    assert controller.start_calls == [
        EntryBehaviorTrainingRequest(
            "setup_version_1",
            "grouping_version_1",
            "LONG",
        )
    ]
    model = SimpleNamespace(
        model_version_id="model_v1",
        maturity=SimpleNamespace(value="FORMAL"),
        stable_features=(
            SimpleNamespace(
                name_zh="决策周期20根方向效率",
                coefficient=0.75,
                nonzero_fold_count=3,
                fold_count=3,
                fold_coefficient_min=0.61,
                fold_coefficient_max=0.84,
            ),
        ),
        research_threshold=0.62,
        applicability_threshold=68.5,
        manifest=SimpleNamespace(
            data_end_utc_ms=1_735_689_600_000,
            label_counts=(("ENTRY", 50), ("REJECT", 50)),
            episode_ids=tuple(f"episode_{index}" for index in range(100)),
            selected_c=0.1,
            validation_metrics=SimpleNamespace(
                sample_count=45,
                balanced_log_loss=0.38,
                brier_score=0.12,
                recall=0.85,
                precision=0.70,
            ),
            test_metrics=SimpleNamespace(
                sample_count=20,
                balanced_log_loss=0.41,
                brier_score=0.14,
                recall=0.82,
                precision=0.67,
            ),
        ),
    )
    controller.resultReady.emit(
        SimpleNamespace(model=model, failure=None)
    )
    app.processEvents()

    assert "开仓选择倾向" in page.titleLabel.text()
    assert "正式" in page.statusLabel.text()
    assert "0.410" in page.metricsLabel.text()
    assert page.featureTable.rowCount() == 1
    assert "0.6100" in page.featureTable.item(0, 3).text()
    assert "0.8400" in page.featureTable.item(0, 3).text()
    visible_text = " ".join(
        label.text() for label in page.findChildren(QtWidgets.QLabel)
    )
    assert all(
        forbidden not in visible_text
        for forbidden in ("胜率", "盈利概率", "交易信号")
    )
    assert not page.styleSheet()

    page.retranslate_ui("en_US")
    assert "current eligible blind labels" in page.statusLabel.text()
    assert "模型已包含" not in page.statusLabel.text()


def test_decision_workspace_reuses_behavior_page_for_exit_training_semantics():
    app = QtWidgets.QApplication.instance()
    assert app is not None
    controller = _BehaviorController()
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        behavior_training_service=_BehaviorService(),
        behavior_training_controller=controller,
    )

    assert isinstance(
        workspace.stepPages["behavior_model"],
        EntryBehaviorModelWorkspace,
    )
    workspace.modeTabs.setCurrentIndex(1)
    app.processEvents()
    workspace.select_step("behavior_model")
    page = workspace.stepPages["behavior_model"]
    page.set_research_context(
        setup_version_id="setup_version_1",
        grouping_version_id="grouping_version_1",
        direction="LONG",
    )
    page.set_training_operation_gate(allowed=True, message="")
    page.trainButton.click()

    assert len(controller.start_calls) == 1
    assert (
        controller.start_calls[0].target
        is BehaviorModelTarget.EXIT_SELECTION
    )
    assert "立即平仓选择倾向" in page.titleLabel.text()
    assert "不表示后面会下跌" in page.explanationLabel.text()
    assert "卖出信号" not in page.explanationLabel.text()
