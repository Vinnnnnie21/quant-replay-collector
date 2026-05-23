from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app_i18n import tr
from ui_style import SPACING, style_secondary_button


class AnalysisWorkspace(QtWidgets.QDialog):
    def __init__(self, app_window, parent=None):
        super().__init__(parent or app_window)
        self.app_window = app_window
        self.resize(1180, 760)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self._build_ui()
        self.retranslate_ui()

    def _language(self) -> str:
        return str(getattr(self.app_window, "current_language", "zh_CN") or "zh_CN")

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self._language(), default)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        root.setSpacing(SPACING["md"])

        header = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel()
        self.titleLabel.setProperty("role", "appTitle")
        self.sessionLabel = QtWidgets.QLabel()
        self.sessionLabel.setProperty("role", "muted")
        self.btnRefresh = QtWidgets.QPushButton()
        self.btnRefresh.setStyleSheet(style_secondary_button())
        self.btnRefresh.clicked.connect(self.refresh)
        header.addWidget(self.titleLabel)
        header.addWidget(self.sessionLabel)
        header.addStretch(1)
        header.addWidget(self.btnRefresh)
        root.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
        self.performanceTab = self._performance_tab()
        self.eventStudyTab = self._event_study_tab()
        self.consistencyTab = self._existing_analysis_widget("strategyConsistencyPanel", "No strategy consistency panel.")
        self.backtestTab = self._existing_analysis_widget("backtestPanel", "No backtest panel.")
        self.premiumTab = self._existing_analysis_widget("premiumBox", "No USDT premium panel.")
        self.aiTab = self._ai_tab()
        self.tabs.addTab(self.performanceTab, "")
        self.tabs.addTab(self.eventStudyTab, "")
        self.tabs.addTab(self.consistencyTab, "")
        self.tabs.addTab(self.backtestTab, "")
        self.tabs.addTab(self.premiumTab, "")
        self.tabs.addTab(self.aiTab, "")
        root.addWidget(self.tabs, stretch=1)

    def _performance_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.performanceTabs = QtWidgets.QTabWidget()
        self.closedTradesTab = self._existing_analysis_widget("closedTradesTable", "No closed trades table.")
        self.performanceTextTab = self._existing_analysis_widget("performanceText", "No performance summary.")
        self.equityTab = self._existing_analysis_widget("equityTable", "No equity curve table.")
        self.performanceTabs.addTab(self.closedTradesTab, "")
        self.performanceTabs.addTab(self.performanceTextTab, "")
        self.performanceTabs.addTab(self.equityTab, "")
        layout.addWidget(self.performanceTabs)
        return tab

    def _event_study_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.eventTabs = QtWidgets.QTabWidget()
        self.eventStudyTableTab = self._existing_analysis_widget("eventStudyTable", "No event study table.")
        self.datasetTab = self._existing_analysis_widget("datasetText", "No dataset summary.")
        self.eventTabs.addTab(self.eventStudyTableTab, "")
        self.eventTabs.addTab(self.datasetTab, "")
        layout.addWidget(self.eventTabs)
        return tab

    def _is_main_trading_tab_widget(self, widget: QtWidgets.QWidget) -> bool:
        right_tabs = getattr(self.app_window, "rightTabs", None)
        if not isinstance(right_tabs, QtWidgets.QTabWidget):
            return False
        current = widget
        while current is not None:
            if right_tabs.indexOf(current) >= 0:
                return True
            current = current.parentWidget()
        return False

    def _placeholder(self, text: str) -> QtWidgets.QWidget:
        placeholder = QtWidgets.QPlainTextEdit()
        placeholder.setReadOnly(True)
        placeholder.setPlainText(text)
        return placeholder

    def _existing_analysis_widget(self, name: str, empty_text: str) -> QtWidgets.QWidget:
        widget = getattr(self.app_window, name, None)
        if not isinstance(widget, QtWidgets.QWidget):
            return self._placeholder(empty_text)
        # Lightweight migration only. These widgets should eventually become independent panels.
        # Do not reparent widgets that still belong to the main trading tabs.
        if self._is_main_trading_tab_widget(widget):
            return self._placeholder(f"{empty_text}\nWidget is still owned by the main trading tabs.")
        return widget

    def _ai_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        self.aiText = QtWidgets.QPlainTextEdit()
        self.aiText.setReadOnly(True)
        layout.addWidget(self.aiText)
        return tab

    def retranslate_ui(self):
        self.setWindowTitle(self._tr("data_analysis"))
        self.titleLabel.setText(self._tr("data_analysis"))
        self.btnRefresh.setText(self._tr("refresh"))
        self.tabs.setTabText(self.tabs.indexOf(self.performanceTab), self._tr("trading_performance"))
        self.tabs.setTabText(self.tabs.indexOf(self.eventStudyTab), self._tr("event_study"))
        self.tabs.setTabText(self.tabs.indexOf(self.consistencyTab), self._tr("strategy_consistency"))
        self.tabs.setTabText(self.tabs.indexOf(self.backtestTab), self._tr("backtest_research"))
        self.tabs.setTabText(self.tabs.indexOf(self.premiumTab), self._tr("usdt_premium"))
        self.tabs.setTabText(self.tabs.indexOf(self.aiTab), self._tr("ai_summary"))
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.closedTradesTab), self._tr("closed_trades"))
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.performanceTextTab), self._tr("trading_performance"))
        self.performanceTabs.setTabText(self.performanceTabs.indexOf(self.equityTab), "Equity")
        self.eventTabs.setTabText(self.eventTabs.indexOf(self.eventStudyTableTab), self._tr("event_study"))
        self.eventTabs.setTabText(self.eventTabs.indexOf(self.datasetTab), self._tr("dataset"))
        self.aiText.setPlainText(
            "AI summary is reserved for exported LLM context.\n"
            "The local API is read-only. AI output is not investment advice."
            if self._language() == "en_US"
            else "AI 摘要入口已预留。\n导出会话后，可通过本地只读 API 获取 LLM context。\nAI 只解释研究结果，不提供投资建议。"
        )
        self.refresh()

    def refresh(self):
        session_id = getattr(self.app_window, "session_id", None)
        self.sessionLabel.setText(f"session: {session_id}" if session_id else self._tr("no_session_data"))
        for method_name in ("_refresh_tables", "_refresh_performance_summary", "_refresh_premium_plot"):
            method = getattr(self.app_window, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    def closeEvent(self, event):
        event.ignore()
        self.hide()
