# -*- coding: utf-8 -*-
"""
Two small QComboBox subclasses used by the main window.

``HistoryComboBox``
    The Search box. Every entry in the drop-down list carries an "X" on
    its right-hand side; clicking it deletes just that one entry, without
    closing the list, changing what is typed in the box, or touching the
    rest of the history.

``MultiSelectComboBox``
    The "Look in" box. Entries are check boxes, so several folders can
    be searched at once - the closed box then shows them joined
    together, e.g. ``C:\\, D:\\``. Clicking an entry toggles it and
    leaves the list open, so a few folders can be ticked in one go;
    click anywhere outside the list (or press Esc) to close it.
    Folders that came from the history (browsed to / remembered) also
    carry an "X" on the right, exactly like the Search box, which
    removes just that folder from the history. The built-in entries
    (drives, home folder) have no X.

Written for Python 3.8 / PyQt5, like the rest of the app - nothing here
needs a newer interpreter or a newer Qt than the Windows 7 build uses.
"""
import os

from PyQt5.QtCore import Qt, QEvent, QRect, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPalette, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)


# Item role marking a row as deletable. Rows without it (None/False) get
# no X - used by the "Look in" list for the drives and the home folder,
# which are rebuilt on every start and so are not history entries.
REMOVABLE_ROLE = Qt.UserRole + 10


def _row_removable(index):
    """True unless the row explicitly opted out. HistoryComboBox rows
    carry no role at all and are always removable; the "Look in" rows
    set it to True/False."""
    value = index.data(REMOVABLE_ROLE)
    return True if value is None else bool(value)


class _DeleteItemDelegate(QStyledItemDelegate):
    """Draws each drop-down entry as: entry text [X].

    The "X" sits at the right-hand end of the row and is painted by
    hand (rather than using an icon asset) so it scales with the row
    height and matches the rest of the app's hand-drawn icons.
    ``button_rect()`` is also what HistoryComboBox uses to decide
    whether a click landed on the X, so the hit area and the drawn
    glyph can never drift apart.
    """

    BUTTON_WIDTH = 24
    GLYPH_SIZE = 9

    def button_rect(self, item_rect):
        """The clickable strip, always on the far right of the row - in
        right-to-left languages too, where the entry text moves over to
        the left but the X stays where the user was told it is."""
        return QRect(item_rect.right() - self.BUTTON_WIDTH + 1, item_rect.top(),
                     self.BUTTON_WIDTH, item_rect.height())

    def sizeHint(self, option, index):
        size = super(_DeleteItemDelegate, self).sizeHint(option, index)
        if _row_removable(index):
            size.setWidth(size.width() + self.BUTTON_WIDTH)
        # Give the X a little breathing room even with a small UI font.
        size.setHeight(max(size.height(), 22))
        return size

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        # Let the style paint the row itself (background, selection,
        # hover) across its full width, but without the text - we draw
        # that ourselves below, shifted over to leave room for the X.
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        removable = _row_removable(index)
        selected = bool(option.state & QStyle.State_Selected)
        if opt.features & QStyleOptionViewItem.HasCheckIndicator:
            # Check-box rows ("Look in"): let the style say where the
            # text goes so it doesn't overlap the check box.
            text_rect = QRect(style.subElementRect(
                QStyle.SE_ItemViewItemText, opt, widget))
        else:
            text_rect = QRect(option.rect)
            text_rect.setLeft(text_rect.left() + 4)
        if removable:
            text_rect.setRight(max(option.rect.right() - self.BUTTON_WIDTH - 2,
                                   text_rect.left()))
        painter.setPen(opt.palette.color(
            QPalette.Normal,
            QPalette.HighlightedText if selected else QPalette.Text))
        align = Qt.AlignVCenter | (
            Qt.AlignRight if opt.direction == Qt.RightToLeft else Qt.AlignLeft)
        painter.drawText(
            text_rect, align,
            painter.fontMetrics().elidedText(text, Qt.ElideRight, text_rect.width()))

        if not removable:
            painter.restore()
            return

        # The X itself - red while the row is under the cursor, so it
        # reads as "this deletes something" rather than as decoration.
        hovered = bool(option.state & QStyle.State_MouseOver)
        rect = self.button_rect(option.rect)
        cx = rect.center().x() + 0.5
        cy = rect.center().y() + 0.5
        half = self.GLYPH_SIZE / 2.0
        pen = QPen(QColor(200, 60, 60) if hovered else QColor(135, 135, 135))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy + half))
        painter.drawLine(QPointF(cx - half, cy + half), QPointF(cx + half, cy - half))

        painter.restore()


class HistoryComboBox(QComboBox):
    """Editable combo whose drop-down entries can be deleted one by one.

    Emits ``itemRemoved(text)`` so the owner can drop the same entry
    from wherever it is persisted (QSettings, a completer model, ...).
    """

    itemRemoved = pyqtSignal(str)

    def __init__(self, parent=None):
        super(HistoryComboBox, self).__init__(parent)
        self._delete_delegate = _DeleteItemDelegate(self)
        self.setItemDelegate(self._delete_delegate)
        view = self.view()
        # Mouse tracking is what makes State_MouseOver arrive in the
        # delegate, i.e. what lets the X light up under the cursor.
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        view = self.view()
        if obj is view.viewport() and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                QEvent.MouseButtonDblClick):
            if event.button() == Qt.LeftButton:
                index = view.indexAt(event.pos())
                if index.isValid():
                    rect = view.visualRect(index)
                    if self._delete_delegate.button_rect(rect).contains(event.pos()):
                        if event.type() == QEvent.MouseButtonRelease:
                            self.remove_entry(index.row())
                        # Swallow press *and* release: a click on the X
                        # must not also pick that entry (which would
                        # close the list and fill the box with an entry
                        # that is about to disappear).
                        return True
        return super(HistoryComboBox, self).eventFilter(obj, event)

    # ------------------------------------------------------------------
    def remove_entry(self, row):
        if row < 0 or row >= self.count():
            return
        text = self.itemText(row)
        typed = self.currentText() if self.isEditable() else None
        self.removeItem(row)
        if typed is not None:
            # removeItem() re-syncs the line edit to whatever entry
            # becomes current - put back exactly what the user typed.
            self.setEditText(typed)
        self.itemRemoved.emit(text)
        if self.count() == 0:
            self.hidePopup()
        else:
            self._resize_popup()

    def _resize_popup(self):
        """Shrink the open drop-down by one row after a deletion, so it
        doesn't leave a blank strip where the entry used to be."""
        view = self.view()
        container = view.parentWidget()
        if container is None or not container.isVisible():
            return
        try:
            row_height = view.sizeHintForRow(0)
            if row_height <= 0:
                return
            rows = min(self.count(), max(self.maxVisibleItems(), 1))
            frame = max(container.height() - view.height(), 0)
            container.resize(container.width(), row_height * rows + frame + 2)
        except Exception:
            # Purely cosmetic - never let it break the deletion itself.
            pass


class MultiSelectComboBox(QComboBox):
    """Combo box whose entries are check boxes, for picking several
    folders at once ("C:\\, D:\\").

    The closed box shows every ticked path joined by ``SEPARATOR``; the
    line edit is display-only, so paths are always real ones that were
    picked from the list or added by Browse..., never free text with a
    typo in it. Emits ``selectionChanged(list_of_paths)``.
    """

    SEPARATOR = ", "

    selectionChanged = pyqtSignal(list)
    # Emitted with the path whose "X" was clicked, after the row is gone.
    itemRemoved = pyqtSignal(str)

    def __init__(self, parent=None):
        super(MultiSelectComboBox, self).__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._delete_delegate = _DeleteItemDelegate(self)
        self.setItemDelegate(self._delete_delegate)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().installEventFilter(self)
        self.setInsertPolicy(QComboBox.NoInsert)
        view = self.view()
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)
        self._model.dataChanged.connect(self._on_data_changed)
        # The combo would otherwise keep overwriting the joined text
        # with the "current" entry's own text.
        self.currentIndexChanged.connect(self._on_current_index_changed)
        self.setCurrentIndex(-1)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            # A read-only line edit swallows clicks, so clicking the
            # box itself would do nothing without this - only the
            # little arrow would open the list.
            self.showPopup()
            return True

        view = self.view()
        if obj is view.viewport() and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                QEvent.MouseButtonDblClick):
            if event.button() == Qt.LeftButton:
                index = view.indexAt(event.pos())
                on_x = (index.isValid() and _row_removable(index)
                        and self._delete_delegate.button_rect(
                            view.visualRect(index)).contains(event.pos()))
                if event.type() == QEvent.MouseButtonRelease:
                    if on_x:
                        self.remove_row(index.row())
                    elif index.isValid():
                        self.toggle_row(index.row())
                # Keep the list open so several folders can be ticked in
                # one go - clicking outside it (or Esc) closes it.
                return True
        return super(MultiSelectComboBox, self).eventFilter(obj, event)

    def _on_data_changed(self, *args):
        self._update_display()

    def _on_current_index_changed(self, _index):
        self._update_display()

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------
    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.normpath(path)) if path else ""

    def find_path(self, path):
        """Row holding *path* (compared the way the filesystem compares
        it - case-insensitively on Windows), or -1."""
        key = self._key(path)
        for row in range(self._model.rowCount()):
            if self._key(self._model.item(row).text()) == key:
                return row
        return -1

    def paths(self):
        return [self._model.item(row).text() for row in range(self._model.rowCount())]

    def add_path(self, path, checked=False, at_top=False, removable=False):
        """Add *path* if it isn't listed yet; returns its row either
        way, so re-adding an existing folder just re-uses its entry.
        ``removable=True`` gives the row an "X" (history entries)."""
        if not path:
            return -1
        path = os.path.normpath(path)
        row = self.find_path(path)
        if row != -1:
            if checked:
                self.set_row_checked(row, True)
            return row

        item = QStandardItem(path)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        item.setData(Qt.Checked if checked else Qt.Unchecked, Qt.CheckStateRole)
        item.setData(bool(removable), REMOVABLE_ROLE)
        if at_top:
            self._model.insertRow(0, item)
            row = 0
        else:
            self._model.appendRow(item)
            row = self._model.rowCount() - 1
        self._update_display()
        return row

    def remove_row(self, row):
        """Delete one entry (its "X" was clicked). The list stays open
        and the other folders keep their ticks."""
        if row < 0 or row >= self._model.rowCount():
            return
        path = self._model.item(row).text()
        self._model.removeRow(row)
        self._update_display()
        self.itemRemoved.emit(path)
        self._resize_popup()

    def _resize_popup(self):
        """Shrink the open drop-down after a deletion so no blank strip
        is left where the entry used to be."""
        view = self.view()
        container = view.parentWidget()
        if container is None or not container.isVisible():
            return
        try:
            row_height = view.sizeHintForRow(0)
            if row_height <= 0:
                return
            rows = min(self.count(), max(self.maxVisibleItems(), 1))
            frame = max(container.height() - view.height(), 0)
            container.resize(container.width(), row_height * rows + frame + 2)
        except Exception:
            pass

    def clear_paths(self):
        self._model.clear()
        self.setCurrentIndex(-1)
        self._update_display()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def selected_paths(self):
        paths = []
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item.checkState() == Qt.Checked:
                paths.append(item.text())
        return paths

    def set_row_checked(self, row, checked):
        if 0 <= row < self._model.rowCount():
            self._model.item(row).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def toggle_row(self, row):
        if 0 <= row < self._model.rowCount():
            item = self._model.item(row)
            self.set_row_checked(row, item.checkState() != Qt.Checked)

    def set_selected_paths(self, paths, add_missing=True):
        """Tick exactly *paths* and untick everything else."""
        wanted = set(self._key(p) for p in paths if p)
        if add_missing:
            for path in paths:
                if path and self.find_path(path) == -1:
                    self.add_path(path)
        self._model.blockSignals(True)
        try:
            for row in range(self._model.rowCount()):
                item = self._model.item(row)
                item.setCheckState(
                    Qt.Checked if self._key(item.text()) in wanted else Qt.Unchecked)
        finally:
            self._model.blockSignals(False)
        self._update_display()

    # ------------------------------------------------------------------
    def _update_display(self):
        paths = self.selected_paths()
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setText(self.SEPARATOR.join(paths))
            # Show the *start* of a long list rather than its tail.
            line_edit.setCursorPosition(0)
        self.setToolTip("\n".join(paths))
        self.selectionChanged.emit(paths)
