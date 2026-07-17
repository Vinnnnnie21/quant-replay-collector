from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


DEFAULT_TRADE_PAGE_SIZE = 200


@dataclass(frozen=True)
class PerformanceTradeRow:
    values: tuple[str, ...]
    trade_id: str
    sort_values: tuple[Any, ...]
    colors: tuple[str | None, ...]


class PerformanceTradeTableModel(QtCore.QAbstractTableModel):
    pageChanged = QtCore.Signal(int, int)

    def __init__(self, headers: list[str], *, page_size: int = DEFAULT_TRADE_PAGE_SIZE, parent=None) -> None:
        super().__init__(parent)
        self._headers = tuple(headers)
        self._rows: tuple[PerformanceTradeRow, ...] = ()
        self.page_size = max(1, int(page_size))
        self.current_page = 0

    @property
    def total_rows(self) -> int:
        return len(self._rows)

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(self.total_rows / self.page_size))

    def _page_rows(self) -> tuple[PerformanceTradeRow, ...]:
        start = self.current_page * self.page_size
        return self._rows[start : start + self.page_size]

    def rowCount(self, _parent=QtCore.QModelIndex()) -> int:
        return len(self._page_rows())

    def columnCount(self, _parent=QtCore.QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QtCore.QModelIndex, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        rows = self._page_rows()
        if index.row() >= len(rows) or index.column() >= len(self._headers):
            return None
        row = rows[index.row()]
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            return row.values[column]
        if role == QtCore.Qt.UserRole and column == 0:
            return row.trade_id
        if role == QtCore.Qt.ForegroundRole and row.colors[column]:
            return QtGui.QBrush(QtGui.QColor(row.colors[column]))
        return None

    def headerData(self, section: int, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return super().headerData(section, orientation, role)

    def set_rows(self, rows: list[PerformanceTradeRow]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.current_page = 0
        self.endResetModel()
        self.pageChanged.emit(self.current_page, self.page_count)

    def next_page(self) -> bool:
        if self.current_page + 1 >= self.page_count:
            return False
        self.beginResetModel()
        self.current_page += 1
        self.endResetModel()
        self.pageChanged.emit(self.current_page, self.page_count)
        return True

    def previous_page(self) -> bool:
        if self.current_page <= 0:
            return False
        self.beginResetModel()
        self.current_page -= 1
        self.endResetModel()
        self.pageChanged.emit(self.current_page, self.page_count)
        return True

    def sort(self, column: int, order=QtCore.Qt.AscendingOrder) -> None:
        if not 0 <= column < len(self._headers):
            return
        reverse = order == QtCore.Qt.DescendingOrder
        self.beginResetModel()
        self._rows = tuple(
            sorted(self._rows, key=lambda row: row.sort_values[column], reverse=reverse)
        )
        self.current_page = 0
        self.endResetModel()
        self.pageChanged.emit(self.current_page, self.page_count)

    def show_trade(self, trade_id: str) -> int | None:
        absolute = next(
            (index for index, row in enumerate(self._rows) if row.trade_id == trade_id),
            None,
        )
        if absolute is None:
            return None
        page = absolute // self.page_size
        if page != self.current_page:
            self.beginResetModel()
            self.current_page = page
            self.endResetModel()
            self.pageChanged.emit(self.current_page, self.page_count)
        return absolute % self.page_size

    def sort_value(self, row: int, column: int):
        rows = self._page_rows()
        return rows[row].sort_values[column]


class _CellAdapter:
    def __init__(self, model: PerformanceTradeTableModel, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column
        self.sort_value = model.sort_value(row, column)

    def text(self) -> str:
        return str(self._model.index(self._row, self._column).data(QtCore.Qt.DisplayRole) or "")

    def data(self, role):
        return self._model.index(self._row, self._column).data(role)

    def foreground(self) -> QtGui.QBrush:
        value = self._model.index(self._row, self._column).data(QtCore.Qt.ForegroundRole)
        return value if isinstance(value, QtGui.QBrush) else QtGui.QBrush()

    def row(self) -> int:
        return self._row


class PerformanceTradeTableView(QtWidgets.QTableView):
    def rowCount(self) -> int:
        return self.model().rowCount()

    def columnCount(self) -> int:
        return self.model().columnCount()

    def item(self, row: int, column: int) -> _CellAdapter | None:
        if row < 0 or column < 0 or row >= self.rowCount() or column >= self.columnCount():
            return None
        return _CellAdapter(self.model(), row, column)

    def horizontalHeaderItem(self, column: int) -> _CellAdapter | None:
        if column < 0 or column >= self.columnCount():
            return None
        model = self.model()

        class HeaderAdapter:
            def text(self_nonlocal) -> str:
                return str(model.headerData(column, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole) or "")

        return HeaderAdapter()

    def selectedItems(self) -> list[_CellAdapter]:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [
            _CellAdapter(self.model(), row, column)
            for row in rows
            for column in range(self.columnCount())
        ]

    def scrollToItem(self, item: _CellAdapter) -> None:
        self.scrollTo(self.model().index(item.row(), 0))


__all__ = [
    "DEFAULT_TRADE_PAGE_SIZE",
    "PerformanceTradeRow",
    "PerformanceTradeTableModel",
    "PerformanceTradeTableView",
]
