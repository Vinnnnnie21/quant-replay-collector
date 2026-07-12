from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class _ClickLineEdit(QtWidgets.QLineEdit):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class DatePickerPopup(QtWidgets.QFrame):
    dateSelected = QtCore.Signal(QtCore.QDate)

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("datePickerPopup")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setFixedWidth(312)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        self.previousButton = QtWidgets.QToolButton()
        self.previousButton.setText("‹")
        self.previousButton.setProperty("role", "calendarNav")
        self.monthLabel = QtWidgets.QLabel()
        self.monthLabel.setProperty("role", "calendarTitle")
        self.monthLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.nextButton = QtWidgets.QToolButton()
        self.nextButton.setText("›")
        self.nextButton.setProperty("role", "calendarNav")
        header.addWidget(self.previousButton)
        header.addWidget(self.monthLabel, 1)
        header.addWidget(self.nextButton)
        root.addLayout(header)

        self.calendar = QtWidgets.QCalendarWidget()
        self.calendar.setObjectName("datePickerCalendar")
        self.calendar.setNavigationBarVisible(False)
        self.calendarView = self.calendar.findChild(QtWidgets.QTableView)
        if self.calendarView is not None:
            self.calendarView.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.calendar.setVerticalHeaderFormat(QtWidgets.QCalendarWidget.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(QtWidgets.QCalendarWidget.ShortDayNames)
        self.calendar.setFirstDayOfWeek(QtCore.Qt.Monday)
        self.calendar.setGridVisible(False)
        root.addWidget(self.calendar)

        self.todayButton = QtWidgets.QPushButton("今天")
        self.todayButton.setProperty("role", "calendarToday")
        root.addWidget(self.todayButton, alignment=QtCore.Qt.AlignRight)

        self.previousButton.clicked.connect(self.calendar.showPreviousMonth)
        self.nextButton.clicked.connect(self.calendar.showNextMonth)
        self.calendar.currentPageChanged.connect(self._update_title)
        self.calendar.clicked.connect(self._choose_date)
        self.todayButton.clicked.connect(lambda: self._choose_date(QtCore.QDate.currentDate()))
        self._update_title(self.calendar.yearShown(), self.calendar.monthShown())

    def _update_title(self, year: int, month: int) -> None:
        self.monthLabel.setText(f"{year}年 {month}月")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect(), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    def _choose_date(self, date: QtCore.QDate) -> None:
        self.dateSelected.emit(date)
        self.hide()

    def sync(self, date: QtCore.QDate, minimum: QtCore.QDate, maximum: QtCore.QDate) -> None:
        self.calendar.setDateRange(minimum, maximum)
        self.calendar.setSelectedDate(date)
        self.calendar.setCurrentPage(date.year(), date.month())


class DatePicker(QtWidgets.QWidget):
    """A click-only date field with a custom calendar and QDateEdit-compatible API."""

    dateChanged = QtCore.Signal(QtCore.QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "datePicker")
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self._minimum = QtCore.QDate(1900, 1, 1)
        self._maximum = QtCore.QDate.currentDate()
        self._date = self._maximum

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.textField = _ClickLineEdit()
        self.textField.setObjectName("datePickerText")
        self.textField.setReadOnly(True)
        self.textField.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.openButton = QtWidgets.QToolButton()
        self.openButton.setObjectName("datePickerButton")
        self.openButton.setText("▾")
        self.openButton.setToolTip("选择日期")
        self.openButton.setFocusPolicy(QtCore.Qt.NoFocus)
        layout.addWidget(self.textField, 1)
        layout.addWidget(self.openButton)

        self.popup = DatePickerPopup(self)
        self.textField.clicked.connect(self.showCalendar)
        self.openButton.clicked.connect(self.showCalendar)
        self.popup.dateSelected.connect(self.setDate)
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.textField.setText(self._date.toString("yyyy/MM/dd"))

    def date(self) -> QtCore.QDate:
        return QtCore.QDate(self._date)

    @QtCore.Slot(QtCore.QDate)
    def setDate(self, date: QtCore.QDate) -> None:  # noqa: N802 - Qt compatibility
        if not date.isValid():
            return
        bounded = max(self._minimum, min(self._maximum, date))
        if bounded == self._date:
            return
        self._date = QtCore.QDate(bounded)
        self._refresh_text()
        self.dateChanged.emit(self.date())

    def setMinimumDate(self, date: QtCore.QDate) -> None:  # noqa: N802
        if date.isValid():
            self._minimum = QtCore.QDate(date)
            if self._date < self._minimum:
                self.setDate(self._minimum)

    def setMaximumDate(self, date: QtCore.QDate) -> None:  # noqa: N802
        if date.isValid():
            self._maximum = QtCore.QDate(date)
            if self._date > self._maximum:
                self.setDate(self._maximum)

    def setCalendarPopup(self, _enabled: bool) -> None:  # noqa: N802
        pass

    def calendarWidget(self) -> QtWidgets.QCalendarWidget:  # noqa: N802
        return self.popup.calendar

    @QtCore.Slot()
    def showCalendar(self) -> None:  # noqa: N802
        self.popup.sync(self._date, self._minimum, self._maximum)
        position = self.mapToGlobal(QtCore.QPoint(0, self.height() + 4))
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            popup_size = self.popup.sizeHint()
            x = min(max(position.x(), available.left()), available.right() - popup_size.width() + 1)
            y = position.y()
            if y + popup_size.height() > available.bottom():
                y = self.mapToGlobal(QtCore.QPoint(0, -popup_size.height() - 4)).y()
            position = QtCore.QPoint(x, max(available.top(), y))
        self.popup.move(position)
        self.popup.show()
        self.popup.raise_()


def bind_date_range(start: DatePicker, end: DatePicker) -> None:
    """Keep two date fields ordered without duplicate change emissions."""

    def keep_end_valid(date: QtCore.QDate) -> None:
        if date > end.date():
            end.setDate(date)

    def keep_start_valid(date: QtCore.QDate) -> None:
        if date < start.date():
            start.setDate(date)

    start.dateChanged.connect(keep_end_valid)
    end.dateChanged.connect(keep_start_valid)


__all__ = ["DatePicker", "DatePickerPopup", "bind_date_range"]
