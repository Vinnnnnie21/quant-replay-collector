from PySide6 import QtCore, QtTest, QtWidgets

from views.date_picker import DatePicker, bind_date_range
from ui_style import DARK_THEME, build_app_qss


def test_clicking_date_field_opens_calendar_without_changing_date():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    picker = DatePicker()
    picker.setDate(QtCore.QDate(2026, 7, 12))
    picker.show()
    qapp.processEvents()

    original = picker.date()
    for _ in range(10):
        QtTest.QTest.mouseClick(picker.textField, QtCore.Qt.LeftButton)
        qapp.processEvents()
        assert picker.date() == original

    assert picker.popup.isVisible()
    assert not picker.popup.mask().isEmpty()
    picker.setDate(QtCore.QDate.currentDate().addYears(7))
    assert picker.date() == QtCore.QDate.currentDate()
    picker.close()


def test_bound_date_range_updates_once_and_never_becomes_invalid():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    start = DatePicker()
    end = DatePicker()
    start.setDate(QtCore.QDate(2026, 7, 1))
    end.setDate(QtCore.QDate(2026, 7, 5))
    bind_date_range(start, end)
    changes = []
    end.dateChanged.connect(changes.append)

    start.setDate(QtCore.QDate(2026, 7, 10))

    assert end.date() == start.date()
    assert len(changes) == 1
    start.close()
    end.close()


def test_date_picker_uses_custom_controls_and_complete_theme_contract():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    picker = DatePicker()
    assert not isinstance(picker, QtWidgets.QAbstractSpinBox)
    assert not isinstance(picker.textField, QtWidgets.QAbstractSpinBox)
    assert picker.popup.previousButton.property("role") == "calendarNav"
    assert picker.popup.nextButton.property("role") == "calendarNav"
    assert picker.popup.todayButton.property("role") == "calendarToday"
    assert picker.popup.calendarView is not None
    assert picker.popup.calendarView.frameShape() == QtWidgets.QFrame.NoFrame
    picker.show()
    qapp.processEvents()
    assert abs(picker.textField.geometry().top() - picker.openButton.geometry().top()) <= 1
    assert abs(picker.textField.height() - picker.openButton.height()) <= 3

    qss = build_app_qss(DARK_THEME)
    for selector in (
        "QWidget[role=\"datePicker\"]",
        "QFrame#datePickerPopup",
        "QCalendarWidget#datePickerCalendar",
        "QToolButton[role=\"calendarNav\"]",
        "QPushButton[role=\"calendarToday\"]",
        "QCalendarWidget#datePickerCalendar QHeaderView::section",
    ):
        assert selector in qss
    popup_style = qss[qss.index("QFrame#datePickerPopup"): qss.index("}", qss.index("QFrame#datePickerPopup"))]
    assert "border-radius: 12px" in popup_style
    picker.close()


def test_date_picker_theme_never_clips_its_text_or_expand_button():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    previous_qss = qapp.styleSheet()
    qapp.setStyleSheet(build_app_qss(DARK_THEME))
    picker = DatePicker()
    try:
        picker.show()
        qapp.processEvents()

        assert picker.textField.geometry().bottom() < picker.height()
        assert picker.openButton.geometry().bottom() < picker.height()
        assert picker.textField.geometry().top() == picker.openButton.geometry().top()
        assert picker.textField.height() == picker.openButton.height()
    finally:
        picker.close()
        qapp.setStyleSheet(previous_qss)
