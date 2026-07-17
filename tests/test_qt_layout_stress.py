from __future__ import annotations

import gc
import os
import sys

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

from test_main_window_layout import _LayoutHost
from analysis_workspace import AnalysisWorkspace, _ManagedAnalysisPlotWidget
from ui_style import EXCHANGE_DARK_THEME
from views.main_window_layout import (
    _ManagedGraphicsLayoutWidget,
    _ManagedPlotWidget,
    build_main_window_ui,
)
from views.main_window_presentation import apply_main_window_theme


def _trace_native_stress(iteration: int, stage: str) -> None:
    if os.environ.get("QRC_QT_STRESS_TRACE") == "1":
        print(f"qt_stress iteration={iteration} stage={stage}", file=sys.stderr, flush=True)


class _StressLayoutHost(_LayoutHost):
    def __init__(self) -> None:
        super().__init__()
        self._start_multi_timeframe_worker = True
        self.reject_close = True
        self.close_order: list[str] = []
        self.panel_stopped_before_graphics = False

    def closeEvent(self, event) -> None:
        if self.reject_close:
            self.close_order.append("close_ignored")
            event.ignore()
            return

        self.close_order.append("panel_stop_requested")
        self.panel_stopped_before_graphics = self.multiTimeframePanel.shutdown()
        if not self.panel_stopped_before_graphics:
            self.close_order.append("panel_stop_pending")
            event.ignore()
            return
        self.close_order.append("panel_stopped")
        self.premiumPlot.shutdown()
        self.close_order.append("premium_plot_released")
        self.glw.shutdown()
        self.close_order.append("main_plots_released")
        event.accept()


class _MenuLifecycleProbe:
    def __init__(self) -> None:
        self.parent_changes: list[object] = []
        self.hidden = False
        self.delete_scheduled = False

    def setParent(self, parent) -> None:
        self.parent_changes.append(parent)

    def hide(self) -> None:
        self.hidden = True

    def deleteLater(self) -> None:
        self.delete_scheduled = True

    def close(self) -> None:
        raise AssertionError("shutdown must not touch a PlotItem menu after graphics close")


def test_managed_plot_widget_close_is_idempotent_after_explicit_shutdown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedPlotWidget()

    plot.shutdown()
    app.processEvents()

    assert plot.close() in (True, False)


def test_managed_plot_widget_shutdown_detaches_scene_without_clearing(monkeypatch):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedPlotWidget()
    scene = plot.scene()
    clear_calls: list[bool] = []
    monkeypatch.setattr(scene, "clear", lambda: clear_calls.append(True))

    plot.shutdown()

    assert clear_calls == []
    assert plot.plotItem is None
    assert plot.scene() is None


def test_managed_plot_widget_does_not_queue_menu_delete_during_parent_teardown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedPlotWidget()
    probe = _MenuLifecycleProbe()
    plot.plotItem.ctrlMenu = probe

    plot.shutdown()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    assert probe.hidden is True
    assert probe.delete_scheduled is False
    assert probe.parent_changes == [None]


def test_managed_plot_widget_disconnects_viewbox_callback_before_cleanup(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedPlotWidget()
    view_box = plot.plotItem.vb
    unhandled: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: unhandled.append(args))

    plot.shutdown()
    view_box.sigStateChanged.emit(view_box)
    app.processEvents()

    assert unhandled == []


def test_managed_graphics_layout_does_not_queue_menu_delete_during_parent_teardown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    owner = QtWidgets.QWidget()
    graphics = _ManagedGraphicsLayoutWidget(owner)
    plot = graphics.addPlot()
    graphics.manage_plots(plot)
    probe = _MenuLifecycleProbe()
    plot.ctrlMenu = probe

    graphics.shutdown()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    assert probe.hidden is True
    assert probe.delete_scheduled is False
    assert probe.parent_changes == [None]


def test_managed_graphics_layout_runs_plotitem_cleanup_before_scene_teardown():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    owner = QtWidgets.QWidget()
    graphics = _ManagedGraphicsLayoutWidget(owner)
    plot = graphics.addPlot()
    graphics.manage_plots(plot)

    graphics.shutdown()

    assert plot.ctrlMenu is None
    assert plot.axes is None
    assert plot.vb is None


def test_managed_graphics_layout_disconnects_viewbox_callbacks_before_cleanup(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    owner = QtWidgets.QWidget()
    graphics = _ManagedGraphicsLayoutWidget(owner)
    plot = graphics.addPlot()
    graphics.manage_plots(plot)
    view_box = plot.vb
    unhandled: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: unhandled.append(args))

    graphics.shutdown()
    view_box.sigStateChanged.emit(view_box)
    app.processEvents()

    assert unhandled == []


def test_managed_graphics_layout_unlinks_axes_and_linked_plots_before_cleanup(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    owner = QtWidgets.QWidget()
    graphics = _ManagedGraphicsLayoutWidget(owner)
    price_plot = graphics.addPlot(row=0, col=0)
    volume_plot = graphics.addPlot(row=1, col=0)
    volume_plot.setXLink(price_plot)
    graphics.manage_plots(price_plot, volume_plot)
    axes = [
        axis["item"]
        for plot in (price_plot, volume_plot)
        for axis in plot.axes.values()
    ]
    linked_views = [axis.linkedView() for axis in axes]
    unhandled: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: unhandled.append(args))

    graphics.shutdown()
    app.processEvents()

    assert unhandled == []
    assert all(view is not None for view in linked_views)
    assert all(axis.linkedView() is None for axis in axes)


def test_managed_analysis_plot_does_not_queue_menu_delete_during_parent_teardown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedAnalysisPlotWidget()
    probe = _MenuLifecycleProbe()
    plot.plotItem.ctrlMenu = probe

    plot.shutdown()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    assert probe.hidden is True
    assert probe.delete_scheduled is False
    assert probe.parent_changes == [None]


def test_managed_analysis_plot_disconnects_viewbox_callback_before_cleanup(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = _ManagedAnalysisPlotWidget()
    view_box = plot.plotItem.vb
    unhandled: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: unhandled.append(args))

    plot.shutdown()
    view_box.sigStateChanged.emit(view_box)
    app.processEvents()

    assert unhandled == []


def test_analysis_workspace_plot_menus_have_explicit_widget_owners():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class WorkspaceHost(QtWidgets.QWidget):
        current_language = "zh_CN"

    host = WorkspaceHost()
    workspace = AnalysisWorkspace(host, parent=host, embedded=True)

    assert workspace.equityCurvePlot.plotItem.ctrlMenu.parentWidget() is workspace.equityCurvePlot
    assert (
        workspace.performanceHistogramPlot.plotItem.ctrlMenu.parentWidget()
        is workspace.performanceHistogramPlot
    )

    assert workspace.shutdown() is True
    host.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_analysis_workspace_plot_shutdown_is_idempotent_before_parent_teardown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    existing_top_level_menus = {
        menu
        for menu in app.topLevelWidgets()
        if isinstance(menu, QtWidgets.QMenu)
    }

    class WorkspaceHost(QtWidgets.QWidget):
        current_language = "zh_CN"

    host = WorkspaceHost()
    workspace = AnalysisWorkspace(host, parent=host, embedded=True)

    for plot in (workspace.equityCurvePlot, workspace.performanceHistogramPlot):
        plot.shutdown()
        plot.shutdown()
        assert plot.plotItem is None

    assert workspace.shutdown() is True
    assert workspace.shutdown() is True
    host.close()
    host.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()
    remaining_top_level_menus = {
        menu
        for menu in app.topLevelWidgets()
        if isinstance(menu, QtWidgets.QMenu)
    }
    assert remaining_top_level_menus <= existing_top_level_menus


@pytest.mark.qt_native_inner
def test_analysis_workspace_plotwidgets_repeat_create_and_delete():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class WorkspaceHost(QtWidgets.QWidget):
        current_language = "zh_CN"

    for _index in range(50):
        host = WorkspaceHost()
        workspace = AnalysisWorkspace(host, parent=host, embedded=True)
        host.resize(900, 700)
        host.show()
        app.processEvents()

        assert workspace.equityCurvePlot.plotItem is not None
        assert workspace.performanceHistogramPlot.plotItem is not None

        if _index % 2:
            host.close()
        assert workspace.shutdown() is True
        assert workspace.shutdown() is True
        host.close()
        workspace.deleteLater()
        destroyed: list[bool] = []
        host.destroyed.connect(lambda: destroyed.append(True))
        host.deleteLater()
        delete_loop = QtCore.QEventLoop()
        host.destroyed.connect(delete_loop.quit)
        QtCore.QTimer.singleShot(2_000, delete_loop.quit)
        delete_loop.exec()
        assert destroyed == [True]
        workspace = None
        host = None
        gc.collect()

    assert not any(isinstance(widget, QtWidgets.QMenu) for widget in app.topLevelWidgets())


@pytest.mark.qt_native_inner
def test_repeated_theme_layout_and_safe_close_in_one_qapplication(monkeypatch):
    import views.main_window_presentation as presentation

    monkeypatch.setattr(presentation, "save_theme_settings", lambda _theme: None)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    for _index in range(150):
        iteration = _index + 1
        _trace_native_stress(iteration, "build_start")
        host = _StressLayoutHost()
        build_main_window_ui(host)
        _trace_native_stress(iteration, "build_done")
        apply_main_window_theme(host, EXCHANGE_DARK_THEME)
        host.resize(1280, 720)
        host.show()
        app.processEvents()
        _trace_native_stress(iteration, "shown")

        assert host.pricePlot.getAxis("right").isVisible()
        assert host.pricePlot.ctrlMenu.parent() is host.glw
        assert host.volPlot.ctrlMenu.parent() is host.glw
        assert host.premiumPlot.plotItem.ctrlMenu.parent() is host.premiumPlot
        assert not isinstance(host.pricePlot.ctrlMenu, QtWidgets.QMenu)
        assert not isinstance(host.volPlot.ctrlMenu, QtWidgets.QMenu)
        assert not isinstance(host.premiumPlot.plotItem.ctrlMenu, QtWidgets.QMenu)
        assert host.pricePlot.ctrlMenu.isEnabled() is False
        assert host.volPlot.ctrlMenu.isEnabled() is False
        assert host.premiumPlot.plotItem.ctrlMenu.isEnabled() is False
        assert host.pricePlot.ctrlMenu.actions() == []
        assert host.volPlot.ctrlMenu.actions() == []
        assert host.premiumPlot.plotItem.ctrlMenu.actions() == []

        assert host.close() is False
        app.processEvents()
        _trace_native_stress(iteration, "ignored_close_done")
        assert host.isVisible() is True
        assert host.glw.closed is False
        assert host.premiumPlot.plotItem is not None
        assert host.multiTimeframePanel._worker_thread.isRunning() is True

        destroyed: list[bool] = []
        host.destroyed.connect(lambda: destroyed.append(True))

        host.reject_close = False
        assert host.close() is False
        assert host.glw.closed is False
        _trace_native_stress(iteration, "stop_requested")
        stop_loop = QtCore.QEventLoop()
        stop_poll = QtCore.QTimer()
        stop_poll.setInterval(10)

        def observe_safe_stop() -> None:
            if host.multiTimeframePanel.shutdown():
                stop_poll.stop()
                stop_loop.quit()

        stop_poll.timeout.connect(observe_safe_stop)
        stop_poll.start()
        QtCore.QTimer.singleShot(2_000, stop_loop.quit)
        stop_loop.exec()
        stop_poll.stop()
        assert host.multiTimeframePanel.shutdown() is True
        _trace_native_stress(iteration, "worker_stopped")
        assert host.close() is True
        _trace_native_stress(iteration, "final_close_done")
        assert host.panel_stopped_before_graphics is True
        assert host.close_order == [
            "close_ignored",
            "panel_stop_requested",
            "panel_stop_pending",
            "panel_stop_requested",
            "panel_stopped",
            "premium_plot_released",
            "main_plots_released",
        ]
        assert host.multiTimeframePanel._worker_thread is None
        assert host.premiumPlot.plotItem is None
        assert host.glw.closed is True
        host.premiumPlot.shutdown()
        host.glw.shutdown()

        delete_loop = QtCore.QEventLoop()
        host.destroyed.connect(delete_loop.quit)
        QtCore.QTimer.singleShot(2_000, delete_loop.quit)
        delete_loop.exec()
        _trace_native_stress(iteration, "deferred_delete_done")
        assert destroyed == [True]

        host = None
        gc.collect()
        app.processEvents()
        assert not any(isinstance(widget, QtWidgets.QMenu) for widget in app.topLevelWidgets())
        _trace_native_stress(iteration, "iteration_done")
