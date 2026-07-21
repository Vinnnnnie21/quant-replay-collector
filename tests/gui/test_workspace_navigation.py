from __future__ import annotations

from types import SimpleNamespace

import analysis_workspace
from main_app import MainWindow


class _Signal:
    def connect(self, _callback):
        return None


class _Tabs:
    def __init__(self):
        self.currentChanged = _Signal()
        self.index = 0

    def count(self):
        return 8

    def setCurrentIndex(self, index):
        self.index = index

    def currentIndex(self):
        return self.index


class _EmbeddedAnalysis:
    def __init__(self, app_window, parent=None, *, embedded=False):
        self.app_window = app_window
        self.parent = parent
        self.embedded = embedded
        self.tabs = _Tabs()
        self.refresh_count = 0
        self.decision_research_open_count = 0
        self.object_name = ""

    def setObjectName(self, name):
        self.object_name = name

    def refresh(self):
        self.refresh_count += 1

    def open_decision_research(self):
        self.decision_research_open_count += 1

    def show(self):  # pragma: no cover - must never be called by embedded navigation
        raise AssertionError("embedded analysis must not open as a window")


class _Stack:
    def __init__(self):
        self.widgets = []
        self.current = None

    def addWidget(self, widget):
        self.widgets.append(widget)

    def setCurrentWidget(self, widget):
        self.current = widget


class _Button:
    def __init__(self):
        self.checked = False

    def setChecked(self, checked):
        self.checked = bool(checked)


def test_workspace_navigation_embeds_analysis_and_restores_replay(monkeypatch):
    monkeypatch.setattr(analysis_workspace, "AnalysisWorkspace", _EmbeddedAnalysis)
    controller_ensures = []
    host = SimpleNamespace(
        backtestPanel=object(),
        strategyConsistencyPanel=object(),
        _analysis_workspace=None,
        workspaceStack=_Stack(),
        app_settings={"analysis_subtab": 3},
        theme_settings={},
        btnAnalysisWorkspace=_Button(),
        btnReplayWorkspace=_Button(),
        replayWorkspace=object(),
        _save_layout_preferences=lambda: None,
        _log=lambda _message: None,
        _ensure_research_backfill_controller=lambda: controller_ensures.append(
            True
        ),
    )
    MainWindow.open_analysis_workspace(host)

    workspace = host._analysis_workspace
    assert workspace.embedded is True
    assert workspace.parent is host.workspaceStack
    assert workspace.object_name == "analysisWorkspace"
    assert workspace.tabs.currentIndex() == 3
    assert workspace.refresh_count == 1
    assert controller_ensures == [True]
    assert host.workspaceStack.current is workspace
    assert host.btnAnalysisWorkspace.checked is True

    MainWindow.open_replay_workspace(host)
    assert host.workspaceStack.current is host.replayWorkspace
    assert host.btnReplayWorkspace.checked is True


def test_legacy_decision_research_navigation_redirects_into_data_analysis(
    monkeypatch,
):
    monkeypatch.setattr(analysis_workspace, "AnalysisWorkspace", _EmbeddedAnalysis)
    controller_ensures = []
    host = SimpleNamespace(
        backtestPanel=object(),
        strategyConsistencyPanel=object(),
        _analysis_workspace=None,
        workspaceStack=_Stack(),
        app_settings={},
        theme_settings={},
        btnAnalysisWorkspace=_Button(),
        replayWorkspace=object(),
        _save_layout_preferences=lambda: None,
        _log=lambda _message: None,
        _ensure_research_backfill_controller=lambda: controller_ensures.append(
            True
        ),
    )
    host.open_analysis_workspace = lambda: MainWindow.open_analysis_workspace(
        host
    )

    MainWindow.open_decision_research_workspace(host)

    workspace = host._analysis_workspace
    assert host.workspaceStack.current is workspace
    assert workspace.decision_research_open_count == 1
    assert controller_ensures == [True]
