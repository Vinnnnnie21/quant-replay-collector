from __future__ import annotations

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from research.setups import SetupLibrary
from analysis_workspace import AnalysisWorkspace
from storage import StorageManager
from ui_style import DARK_THEME, normalize_theme_settings
from views.decision_research_workspace import DecisionResearchWorkspace
from views.setup_editor import SetupEditorForm


def test_setup_form_saves_version_and_workspace_keeps_it_across_steps(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_ui.db"))
    form = SetupEditorForm(setup_library=library, language="zh_CN")

    try:
        form.displayNameEdit.setText("深 V 反转")
        form.rulesEdit.setPlainText("区间低位长下影后收回前低。")
        form.decisionTimeframeBox.setCurrentText("5m")
        form.save()

        assert form.savedSetup is not None
        workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        try:
            assert workspace.setupBox.currentData() == (
                form.savedSetup.setup.setup_id
            )
            assert workspace.versionBox.currentData() == (
                form.savedSetup.version.setup_version_id
            )
            assert workspace.state.setup_version == (
                form.savedSetup.version.setup_version_id
            )
            assert workspace.state.direction == "LONG"
            assert workspace.state.timeframes == ("5m", "15m", "1h")

            for step in workspace.stepButtons.values():
                step.click()

            assert workspace.state.setup_version == (
                form.savedSetup.version.setup_version_id
            )
            assert workspace.state.timeframes == ("5m", "15m", "1h")
        finally:
            workspace.close()
    finally:
        form.close()
        app.processEvents()


def test_setup_version_form_creates_new_version_and_selector_reads_old_one(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_version_ui.db"))
    create_form = SetupEditorForm(
        setup_library=library,
        language="zh_CN",
    )

    try:
        create_form.displayNameEdit.setText("突破回踩")
        create_form.rulesEdit.setPlainText("收盘站上突破位。")
        create_form.decisionTimeframeBox.setCurrentText("5m")
        create_form.save()
        created = create_form.savedSetup
        assert created is not None

        version_form = SetupEditorForm(
            setup_library=library,
            language="zh_CN",
            setup=created.setup,
            based_on_version=created.version,
        )
        try:
            version_form.rulesEdit.setPlainText("下一根完整 K 线确认站稳。")
            version_form.protocolBox.setCurrentIndex(
                version_form.protocolBox.findData(
                    created.version.decision_protocol.NEXT_BAR_CONFIRMATION
                )
            )
            version_form.save()
            changed = version_form.savedVersion
            assert changed is not None
        finally:
            version_form.close()

        workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        try:
            assert workspace.versionBox.currentData() == (
                changed.setup_version_id
            )

            old_index = workspace.versionBox.findData(
                created.version.setup_version_id
            )
            workspace.versionBox.setCurrentIndex(old_index)

            assert workspace.state.setup_version == (
                created.version.setup_version_id
            )
            assert workspace.state.direction == "LONG"
            assert workspace.state.timeframes == ("5m", "15m", "1h")
        finally:
            workspace.close()
    finally:
        create_form.close()
        app.processEvents()


def test_setup_empty_archived_and_illegal_timeframes_have_chinese_states(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_states_ui.db"))
    empty_workspace = DecisionResearchWorkspace(
        language="zh_CN",
        setup_library=library,
    )
    form = SetupEditorForm(setup_library=library, language="zh_CN")

    try:
        assert empty_workspace.setupBox.currentText() == "尚未选择"
        assert empty_workspace.versionBox.currentText() == "尚无版本"

        form.displayNameEdit.setText("非法周期检查")
        form.rulesEdit.setPlainText("有效规则")
        form.decisionTimeframeBox.setCurrentText("5m")
        form.contextTimeframeOneBox.setCurrentText("5m")
        form.save()

        assert form.savedSetup is None
        assert form.errorLabel.isHidden() is False
        assert "严格高于" in form.errorLabel.text()

        form.contextTimeframeOneBox.setCurrentText("15m")
        form.save()
        created = form.savedSetup
        assert created is not None
        library.archive_setup(created.setup.setup_id)

        archived_workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        try:
            assert "已归档" in archived_workspace.setupBox.currentText()
            assert archived_workspace.setupStatusLabel.text() == (
                "已归档，只可读取历史版本"
            )
        finally:
            archived_workspace.close()
    finally:
        form.close()
        empty_workspace.close()
        app.processEvents()


def test_data_analysis_create_setup_action_updates_top_context(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Host(QtWidgets.QWidget):
        current_language = "zh_CN"
        session_id = "setup_session"

        def __init__(self):
            super().__init__()
            self.storage = StorageManager(tmp_path / "setup_analysis.db")

    host = Host()
    analysis = AnalysisWorkspace(host)

    try:
        decision = analysis.decisionResearchWorkspace
        decision.btnCreateSetup.click()
        editor = decision.setupEditorForm

        assert editor is not None
        assert editor.isHidden() is False
        editor.displayNameEdit.setText("数据分析内创建")
        editor.rulesEdit.setPlainText("收盘后确认规则。")
        editor.decisionTimeframeBox.setCurrentText("5m")
        editor.save()

        assert decision.setupBox.currentText() == "数据分析内创建"
        assert decision.versionBox.currentText() == "版本 1"
        assert decision.state.setup_version is not None
        assert decision.state.timeframes == ("5m", "15m", "1h")
    finally:
        analysis.close()
        host.close()
        app.processEvents()


def test_selected_version_freezes_top_semantics_and_edit_action_makes_v2(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_frozen_ui.db"))
    create_form = SetupEditorForm(
        setup_library=library,
        language="zh_CN",
    )

    try:
        create_form.displayNameEdit.setText("冻结版本")
        create_form.rulesEdit.setPlainText("初始规则")
        create_form.decisionTimeframeBox.setCurrentText("5m")
        create_form.save()
        workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        try:
            assert workspace.directionBox.isEnabled() is False
            assert workspace.decisionTimeframeBox.isEnabled() is False
            assert workspace.contextTimeframeOneBox.isEnabled() is False
            assert workspace.contextTimeframeTwoBox.isEnabled() is False

            workspace.btnCreateSetupVersion.click()
            editor = workspace.setupEditorForm
            assert editor is not None
            editor.rulesEdit.setPlainText("新版本规则")
            editor.save()

            assert workspace.versionBox.currentText() == "版本 2"
            assert len(library.list_versions(
                workspace.state.setup_id
            )) == 2
        finally:
            workspace.close()
    finally:
        create_form.close()
        app.processEvents()


def test_setup_editor_created_later_uses_workspace_theme_tokens(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_theme_ui.db"))
    workspace = DecisionResearchWorkspace(
        language="zh_CN",
        setup_library=library,
    )

    try:
        workspace.apply_theme(DARK_THEME)
        workspace.btnCreateSetup.click()
        editor = workspace.setupEditorForm

        assert editor is not None
        theme = normalize_theme_settings(DARK_THEME)
        assert (
            f"background-color: {theme['btn_bg']}"
            in editor.saveButton.styleSheet()
        )
        assert editor.displayNameEdit.styleSheet() != ""
    finally:
        workspace.close()
        app.processEvents()


def test_setup_and_version_selector_texts_follow_language_switch(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_language_ui.db"))
    form = SetupEditorForm(setup_library=library, language="zh_CN")

    try:
        form.displayNameEdit.setText("语言切换")
        form.rulesEdit.setPlainText("有效规则")
        form.decisionTimeframeBox.setCurrentText("5m")
        form.save()
        created = form.savedSetup
        assert created is not None
        library.archive_setup(created.setup.setup_id)
        workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        try:
            assert workspace.setupBox.currentText() == "语言切换（已归档）"
            assert workspace.versionBox.currentText() == "版本 1"

            workspace.retranslate_ui("en_US")

            assert workspace.setupBox.currentText() == (
                "语言切换 (archived)"
            )
            assert workspace.versionBox.currentText() == "Version 1"
        finally:
            workspace.close()
    finally:
        form.close()
        app.processEvents()


def test_invalid_rename_is_rendered_inline_instead_of_escaping_qt_slot(
    tmp_path,
    monkeypatch,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = SetupLibrary(StorageManager(tmp_path / "setup_rename_ui.db"))
    form = SetupEditorForm(setup_library=library, language="zh_CN")

    try:
        form.displayNameEdit.setText("原名称")
        form.rulesEdit.setPlainText("有效规则")
        form.decisionTimeframeBox.setCurrentText("5m")
        form.save()
        assert form.savedSetup is not None
        workspace = DecisionResearchWorkspace(
            language="zh_CN",
            setup_library=library,
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getText",
            lambda *args, **kwargs: (" ", True),
        )
        try:
            workspace._rename_selected_setup()

            assert workspace.setupStatusLabel.isHidden() is False
            assert workspace.setupStatusLabel.text() == (
                "请输入策略模板显示名称。"
            )
        finally:
            workspace.close()
    finally:
        form.close()
        app.processEvents()
