"""The Find / Replace bar (Edit > Find..., Ctrl+F).

It searches the text boxes of the tab that is showing: every field of the
block editor, in order -- opening whatever card a match is folded away in --
or the raw resume.json. A replacement is typed into the text box like any
other edit, so the box's own undo reverses it and, in the block editor, the
resume document is updated just as if it had been typed.
"""
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton
from shiboken6 import isValid

from proofing import utf16
from widgets import Collapsible, restyle


def from_utf16(text, position):
    """A QTextDocument position within `text` -> the Python string index."""
    if text.isascii():
        return position
    return len(text.encode("utf-16-le")[:2 * position].decode("utf-16-le", "ignore"))


class FindBar(QFrame):
    def __init__(self, targets):
        """`targets()` returns the text boxes to search, in reading order."""
        super().__init__()
        self.targets = targets
        self.current = None  # (text box, start, end) of the match that is selected
        self.setProperty("kind", "actions")

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find")
        self.find_input.setClearButtonEnabled(True)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with")
        self.case = QCheckBox("Match case")
        self.words = QCheckBox("Whole words")
        self.count = QLabel()
        self.count.setProperty("kind", "label")
        self.count.setMinimumWidth(90)

        layout = QHBoxLayout(self)
        layout.setSpacing(6)
        layout.addWidget(self.find_input, 3)
        layout.addWidget(self._button("Previous", lambda: self.find(backward=True), "Find the previous match (Shift+F3)"))
        layout.addWidget(self._button("Next", self.find, "Find the next match (F3)"))
        layout.addWidget(self.replace_input, 3)
        layout.addWidget(self._button("Replace", self.replace, "Replace this match and find the next"))
        layout.addWidget(self._button("Replace all", self.replace_all, "Replace every match in this tab"))
        layout.addWidget(self.case)
        layout.addWidget(self.words)
        layout.addWidget(self.count)
        layout.addWidget(self._button("✕", self.close_bar, "Close (Esc)"))

        self.find_input.textChanged.connect(lambda: self.find(restart=True))
        self.find_input.returnPressed.connect(self._enter)
        self.replace_input.returnPressed.connect(self.replace)
        for box in (self.case, self.words):
            box.toggled.connect(lambda: self.find(restart=True))
        self.hide()

    def _button(self, text, slot, tip):
        button = QPushButton(text)
        button.setProperty("kind", "tool")
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda: slot())
        return button

    def _enter(self):
        self.find(backward=bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(event)

    # --- opening and closing ---------------------------------------------------------

    def open(self, replacing=False):
        """Shows the bar, searching for the selected text if there is some."""
        focus = QApplication.focusWidget()
        edits = self.targets()
        if focus in edits:
            cursor = focus.textCursor()
            text = focus.toPlainText()
            self.current = (focus, from_utf16(text, cursor.selectionStart()), from_utf16(text, cursor.selectionEnd()))
            selected = cursor.selectedText()
            if selected and " " not in selected:  # not a multi-line selection
                self.find_input.setText(selected)
        self.show()
        target = self.replace_input if replacing and self.find_input.text() else self.find_input
        target.setFocus()
        target.selectAll()
        self.find(restart=True)

    def close_bar(self):
        self.hide()
        if self.current and isValid(self.current[0]):
            self.current[0].setFocus()

    def reset(self):
        """Forgets the selected match (the tab changed or was rebuilt)."""
        self.current = None
        self.count.setText("")

    # --- searching -------------------------------------------------------------------

    def _pattern(self):
        needle = self.find_input.text()
        if not needle:
            return None
        source = re.escape(needle)
        if self.words.isChecked():
            # \b only where the search text starts or ends with a word character.
            source = (r"\b" if re.match(r"\w", needle) else "") + source + (r"\b" if re.search(r"\w$", needle) else "")
        return re.compile(source, 0 if self.case.isChecked() else re.IGNORECASE)

    def _hits(self, pattern, edits):
        """Every match in the tab: (index of its text box, start, end)."""
        return [(i, match.start(), match.end()) for i, edit in enumerate(edits) for match in pattern.finditer(edit.toPlainText()) if match.end() > match.start()]

    def _place(self, edits):
        """Where the search stands: (index of the text box, start, end)."""
        if self.current and isValid(self.current[0]) and self.current[0] in edits:
            return edits.index(self.current[0]), self.current[1], self.current[2]
        return 0, 0, 0

    def find(self, backward=False, restart=False):
        """Selects the next match (or the previous one); with restart, the
        first match at or after where the search stands. Returns whether
        there was one."""
        pattern, edits = self._pattern(), self.targets()
        if pattern is None or not edits:
            self._report("")
            return False
        hits = self._hits(pattern, edits)
        if not hits:
            self._report("No matches", "error")
            return False
        at, start, end = self._place(edits)
        if backward:
            earlier = [hit for hit in hits if (hit[0], hit[2]) <= (at, start)]
            hit = earlier[-1] if earlier else hits[-1]
        else:
            later = [hit for hit in hits if (hit[0], hit[1]) >= (at, start if restart else end)]
            hit = later[0] if later else hits[0]
        self._select(edits[hit[0]], hit[1], hit[2])
        self._report(f"{hits.index(hit) + 1} of {len(hits)}")
        return True

    def _select(self, edit, start, end):
        previous = self.current[0] if self.current else None
        if previous is not None and previous is not edit and isValid(previous):
            cursor = previous.textCursor()  # leave only the new match highlighted
            cursor.clearSelection()
            previous.setTextCursor(cursor)
        text = edit.toPlainText()
        cursor = edit.textCursor()
        cursor.setPosition(utf16(text, start))
        cursor.setPosition(utf16(text, end), QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)
        self.current = (edit, start, end)
        # Open any folded cards around the match, then bring it into view
        # once they have been laid out.
        parent = edit.parentWidget()
        while parent is not None:
            if isinstance(parent, Collapsible):
                parent.set_open(True)
            parent = parent.parentWidget()
        QTimer.singleShot(0, lambda: isValid(edit) and self._scroll_to(edit))

    @staticmethod
    def _scroll_to(edit):
        edit.ensureCursorVisible()
        parent = edit.parentWidget()
        while parent is not None:
            if hasattr(parent, "ensureWidgetVisible"):
                parent.ensureWidgetVisible(edit, 50, 120)
                break
            parent = parent.parentWidget()

    def _report(self, text, state=""):
        self.count.setText(text)
        restyle(self.count, "state", state)

    # --- replacing -------------------------------------------------------------------

    def replace(self):
        """Replaces the selected match, then finds the next one."""
        pattern, edits = self._pattern(), self.targets()
        if pattern is None:
            return
        if self.current and isValid(self.current[0]) and self.current[0] in edits:
            edit, start, end = self.current
            if pattern.fullmatch(edit.toPlainText()[start:end]):
                replacement = self.replace_input.text()
                edit.textCursor().insertText(replacement)
                self.current = (edit, start, start + len(replacement))
        self.find()

    def replace_all(self):
        pattern, edits = self._pattern(), self.targets()
        if pattern is None:
            return
        replacement, total = self.replace_input.text(), 0
        for edit in edits:
            text, count = pattern.subn(lambda _match: replacement, edit.toPlainText())
            if count:
                cursor = edit.textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.insertText(text)  # one edit, so one undo step in that box
                total += count
        self.current = None
        self._report(f"Replaced {total}" if total else "No matches", "" if total else "error")
