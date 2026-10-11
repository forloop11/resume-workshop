"""Widgets the block editor (blocks.py) is built from: auto-growing text
fields, collapsible cards, a wrapping layout, and drag-and-drop lists."""
from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget


def restyle(widget, name, value):
    """Sets a property the stylesheet (style.qss) selects on, and reapplies it."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class AutoTextEdit(QTextEdit):
    """A plain-text field that grows with its content instead of scrolling."""

    def __init__(self, text="", min_lines=1):
        super().__init__()
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(6)
        self.min_lines = min_lines
        self.setPlainText(text)
        self.document().documentLayout().documentSizeChanged.connect(self.fit)
        self.fit()

    def fit(self, *_):
        margin = 2 * self.document().documentMargin()
        minimum = self.min_lines * self.fontMetrics().lineSpacing() + margin
        # +2 for the stylesheet's 1px border.
        self.setFixedHeight(int(max(self.document().size().height(), minimum)) + 2)

    def wheelEvent(self, event):
        event.ignore()  # scroll the page, not this (unscrollable) field


class LineEdit(AutoTextEdit):
    """A one-line field. It's a text box, not a QLineEdit, so the proofing
    underlines (proofing.py) can be drawn in it."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
        else:
            super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        self.insertPlainText(" ".join(source.text().splitlines()))


class Header(QFrame):
    """A card's title bar; clicking it opens or closes the card."""

    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


HEADER_MARGINS = {"section": (14, 10, 14, 10), "employer": (10, 8, 10, 8)}


class Collapsible(QFrame):
    """A card with a header (an arrow, then whatever the caller adds to
    `head`) and a body (`content`) shown only while the card is open.
    `kind` picks its look in style.qss."""

    toggled = Signal(bool)

    def __init__(self, kind, is_open=False):
        super().__init__()
        self.setProperty("kind", kind)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = Header()
        self.header.setProperty("kind", f"{kind}-header")
        self.head = QHBoxLayout(self.header)
        self.head.setContentsMargins(*HEADER_MARGINS.get(kind, (0, 0, 0, 0)))
        self.arrow = QLabel()
        self.arrow.setProperty("kind", "arrow")
        self.head.addWidget(self.arrow)
        self.body = QFrame()
        self.body.setProperty("kind", f"{kind}-body")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.header)
        outer.addWidget(self.body)
        self.header.clicked.connect(lambda: self.set_open(not self.is_open))
        self.is_open = not is_open
        self.set_open(is_open)

    def set_open(self, is_open):
        if is_open == self.is_open:
            return
        self.is_open = is_open
        self.arrow.setText("▾" if is_open else "▸")
        self.body.setVisible(is_open)
        self.toggled.emit(is_open)


class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto new rows."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, row_height = area.x(), y + row_height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()


# --- drag-and-drop lists -----------------------------------------------------

MIME = "application/x-resume-workshop-item"
DRAG_IMAGE_HEIGHT = 220  # a whole employer card is cropped to this
SCROLL_EDGE = 48  # dragging this close to the page's top/bottom scrolls it


class _Drag:
    def __init__(self, source, index):
        self.source, self.index = source, index
        self.pos = None  # the cursor's last known global position
        self.drop = None  # (list, index) once dropped on one


_drag = None  # the drag in progress, if any


def _dragging(event):
    return _drag is not None and event.mimeData().hasFormat(MIME)


def _drag_image(item):
    grabbed = item.grab()
    ratio = grabbed.devicePixelRatio()
    size = QSize(grabbed.width(), min(grabbed.height(), int(DRAG_IMAGE_HEIGHT * ratio)))
    image = QPixmap(size)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setOpacity(0.85)
    painter.drawPixmap(0, 0, grabbed)
    painter.end()
    return image


def _autoscroll(area):
    if _drag is None or _drag.pos is None:
        return
    viewport = area.viewport()
    pos = viewport.mapFromGlobal(_drag.pos)
    if not 0 <= pos.x() <= viewport.width():
        return
    bar = area.verticalScrollBar()
    if pos.y() < SCROLL_EDGE:
        bar.setValue(bar.value() - (SCROLL_EDGE - pos.y()) // 3 - 2)
    elif pos.y() > viewport.height() - SCROLL_EDGE:
        bar.setValue(bar.value() + (pos.y() - viewport.height() + SCROLL_EDGE) // 3 + 2)


def _start_drag(grip, item, hotspot):
    """Drags `item` (a widget in a SortableList) by `grip`, and moves it once
    it's dropped on a list of the same group."""
    global _drag
    source = item.sortable
    _drag = _Drag(source, source.item_widgets.index(item))
    drag = QDrag(grip)
    mime = QMimeData()
    mime.setData(MIME, source.group.encode())
    drag.setMimeData(mime)
    drag.setPixmap(_drag_image(item))
    drag.setHotSpot(QPoint(hotspot.x(), min(hotspot.y(), DRAG_IMAGE_HEIGHT - 1)))

    area = item.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    scroller = QTimer()
    if area is not None:
        scroller.timeout.connect(lambda: _autoscroll(area))
        scroller.start(30)
    drag.exec(Qt.DropAction.MoveAction)
    scroller.stop()

    finished, _drag = _drag, None
    if finished.drop is None:
        return
    target, index = finished.drop
    src, old, dst, on_move = source.items, finished.index, target.items, target.on_move
    if src is dst:
        if index > old:
            index -= 1
        if index == old:
            return
    # The move rebuilds the editor, this grip included, so it waits until the
    # mouse event that started the drag has been fully handled.
    QTimer.singleShot(0, lambda: on_move(src, old, dst, index))


def _grip_press(self, event):
    self._press = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None


def _grip_move(self, event):
    press = getattr(self, "_press", None)
    if press is None or (event.position().toPoint() - press).manhattanLength() < QApplication.startDragDistance():
        return
    self._press = None
    item = self.drag_item
    _start_drag(self, item, self.mapTo(item, press))


def _grip_release(self, _event):
    self._press = None


class Handle(QLabel):
    """The ⠿ grip that drags `item` within and between SortableLists."""

    def __init__(self, item):
        super().__init__("⠿")
        self.drag_item = item
        self.setProperty("kind", "handle")
        self.setToolTip("Drag to reorder")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    mousePressEvent = _grip_press
    mouseMoveEvent = _grip_move
    mouseReleaseEvent = _grip_release


class Chip(QFrame):
    """A small labelled item that is its own drag grip."""

    def __init__(self):
        super().__init__()
        self.drag_item = self
        self.setProperty("kind", "chip")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    mousePressEvent = _grip_press
    mouseMoveEvent = _grip_move
    mouseReleaseEvent = _grip_release


class SortableList(QFrame):
    """Widgets for the entries of `items` (a list in the resume document), in
    a column -- or wrapping rows, with flow=True. An item's Handle drags it to
    a new place in this list or any other with the same `group`; the drop
    calls on_move(from_items, old_index, to_items, new_index), which does the
    actual move (new_index is the item's index once it has moved)."""

    def __init__(self, items, group, on_move, flow=False, spacing=8):
        super().__init__()
        self.items, self.group, self.on_move, self.flow = items, group, on_move, flow
        self.item_widgets = []
        self.setAcceptDrops(True)
        if flow:
            self._layout = FlowLayout(self, spacing)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        else:
            self._layout = QVBoxLayout(self)
            self._layout.setSpacing(spacing)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # Shows where a dragged item would land.
        self._marker = QFrame(self)
        self._marker.setProperty("kind", "drop-marker")
        self._marker.hide()

    def add(self, widget):
        widget.sortable = self
        self.item_widgets.append(widget)
        self._layout.addWidget(widget)

    def _accepts(self, event):
        return _dragging(event) and bytes(event.mimeData().data(MIME)).decode() == self.group

    def _index_at(self, pos):
        """Where in the list a drop at `pos` lands (0..len)."""
        for i, widget in enumerate(self.item_widgets):
            box = widget.geometry()
            if self.flow:
                if pos.y() < box.top() or (pos.y() <= box.bottom() and pos.x() < box.center().x()):
                    return i
            elif pos.y() < box.center().y():
                return i
        return len(self.item_widgets)

    def _show_marker(self, index):
        gap = self._layout.spacing()
        margins = self._layout.contentsMargins()
        widgets = self.item_widgets
        if self.flow:
            if not widgets:
                box = QRect(margins.left(), margins.top(), 3, max(self.height() - margins.top() - margins.bottom(), 8))
            elif index < len(widgets):
                at = widgets[index].geometry()
                box = QRect(at.left() - gap // 2 - 1, at.top(), 3, at.height())
            else:
                at = widgets[-1].geometry()
                box = QRect(at.right() + gap // 2, at.top(), 3, at.height())
        else:
            if not widgets:
                y = margins.top()
            elif index < len(widgets):
                y = widgets[index].geometry().top() - gap // 2 - 1
            else:
                y = widgets[-1].geometry().bottom() + gap // 2
            box = QRect(0, y, self.width(), 3)
        box.moveLeft(max(0, min(box.left(), self.width() - box.width())))
        box.moveTop(max(0, min(box.top(), self.height() - box.height())))
        self._marker.setGeometry(box)
        self._marker.raise_()
        self._marker.show()

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._accepts(event):
            event.ignore()
            return
        pos = event.position().toPoint()
        _drag.pos = self.mapToGlobal(pos)
        self._show_marker(self._index_at(pos))
        event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._marker.hide()

    def dropEvent(self, event):
        self._marker.hide()
        if not self._accepts(event):
            event.ignore()
            return
        _drag.drop = (self, self._index_at(event.position().toPoint()))
        event.acceptProposedAction()


class DragSurface(QWidget):
    """The page behind the SortableLists. It takes no drops; it only follows
    a drag between the lists, so the page can scroll while one is underway."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if _dragging(event):
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if _dragging(event):
            _drag.pos = self.mapToGlobal(event.position().toPoint())
        event.ignore()
