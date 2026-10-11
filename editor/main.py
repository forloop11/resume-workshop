#!/usr/bin/env python3
"""Desktop editor for a resume folder's input files (`make editor`).

A Qt (PySide6) window: tabs that edit the files in input/ -- the
drag-and-drop block editor (blocks.py) for resume.json and
section_order.yaml, and a raw text editor for resume.json -- beside a
preview of the generated PDF (preview.py), with commands that build the
resume as the folder's Makefile targets do (build.py).
The section list and the JSON Resume schema check are the generators' and
`make validate`'s own (see document.py and scripts/validate_resume.py).

Needs the packages in requirements.txt: pip install -r requirements.txt
"""
import json
import os
import re
import shutil
import signal
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QPoint, QProcess, QProcessEnvironment, QRect, QSize, QStandardPaths, Qt, QTimer, QUrl
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QKeySequence, QPageSize, QPainter, QPalette, QTextCharFormat, QTextOption
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
except ImportError:
    sys.exit("The editor needs PySide6: pip install -r requirements.txt")


import preview
import project

preview.prepare()  # must come before the QApplication


def dark_palette():
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#282a36", QPalette.ColorRole.WindowText: "#f8f8f2",
        QPalette.ColorRole.Base: "#191a21", QPalette.ColorRole.AlternateBase: "#21222c",
        QPalette.ColorRole.Text: "#f8f8f2", QPalette.ColorRole.PlaceholderText: "#6f7493",
        QPalette.ColorRole.Button: "#44475a", QPalette.ColorRole.ButtonText: "#f8f8f2",
        QPalette.ColorRole.Highlight: "#6272a4", QPalette.ColorRole.HighlightedText: "#f8f8f2",
        QPalette.ColorRole.ToolTipBase: "#191a21", QPalette.ColorRole.ToolTipText: "#f8f8f2",
        QPalette.ColorRole.Link: "#8be9fd", QPalette.ColorRole.Dark: "#6272a4",
    }.items():
        palette.setColor(role, QColor(color))
    return palette


def application():
    """The QApplication, created and styled on first use."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("Resume Workshop")
        app.setDesktopFileName("resume-workshop")  # ties the window to the installed launcher and its icon
        app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
        app.setStyle("Fusion")
        app.setPalette(dark_palette())
        app.setStyleSheet((Path(__file__).with_name("style.qss")).read_text(encoding="utf-8"))
    return app


def fatal(message):
    """Reports a startup failure in a dialog (a launcher shows no terminal)
    as well as on stderr, and exits."""
    application()
    QMessageBox.critical(None, "Resume Workshop", message)
    sys.exit(message)


def new_resume(parent=None):
    """Asks for a new or empty folder and makes it a resume folder (see
    project.py). Returns the folder, or None if that didn't happen."""
    folder = QFileDialog.getExistingDirectory(parent, "New Resume: choose a new or empty folder", str(Path.home()))
    if not folder:
        return None
    try:
        project.create(folder)
    except (OSError, ValueError) as error:
        QMessageBox.warning(parent, "New Resume", str(error))
        return None
    return Path(folder)


def open_resume(parent=None):
    """Asks for a resume folder. Returns it, or None if none was chosen."""
    folder = QFileDialog.getExistingDirectory(parent, "Open Resume Folder", str(Path.home()))
    if not folder:
        return None
    missing = project.missing(folder)
    if missing:
        QMessageBox.warning(parent, "Open Resume", f"{folder} isn't a resume folder. It has no {', '.join(missing)}.\n\nFile > New Resume makes one.")
        return None
    return Path(folder)


def choose_resume(reason):
    """Startup with no resume folder to open: offers to make or open one.
    Returns the folder, or exits."""
    application()
    while True:
        box = QMessageBox(QMessageBox.Icon.Question, "Resume Workshop", reason)
        box.setInformativeText("Create a new resume, or open the folder of one you have?")
        create = box.addButton("New Resume…", QMessageBox.ButtonRole.AcceptRole)
        choose = box.addButton("Open Resume…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() not in (create, choose):
            sys.exit(0)
        folder = new_resume() if box.clickedButton() is create else open_resume()
        if folder:
            project.remember(folder)
            return folder


def startup_resume():
    """The resume folder to open first, asking for one if need be."""
    folder = project.startup_folder()
    if folder is None:
        return choose_resume("There is no resume open.")
    if project.missing(folder):
        return choose_resume(f"{folder} isn't a resume folder (it has no {', '.join(project.missing(folder))}).")
    return folder


import build  # noqa: E402
import distribution  # noqa: E402
from blocks import BlocksEditor, button, label, on_edit  # noqa: E402
from document import ORDER, RESUME  # noqa: E402
from find import FindBar  # noqa: E402
from live import GEOMETRY, LivePreview  # noqa: E402
from page_setup import PageSetup  # noqa: E402
from proofing import Grammar, Proofer, Speller, utf16  # noqa: E402
from update import RELEASES, Updater  # noqa: E402
from widgets import Collapsible, restyle  # noqa: E402

EDITABLE_FILES = [ORDER, RESUME]
# Files the blocks tab fully covers: still loaded and saved, but with no raw tab of their own.
NO_TAB = {ORDER}
PRINT_DPI = 600

JSON_KEY = re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)')
JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
JSON_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}|\\.")


def schema_errors(content):
    """resume.json text -> its JSON Resume schema violations."""
    try:
        from validate_resume import schema_errors as check
    except SystemExit as error:  # jsonschema isn't installed
        raise ValueError(str(error)) from None
    return check(json.loads(content))


def print_pages(document, pages, printer):
    """Prints pages (0-based) of a QPdfDocument, each scaled to fill the
    paper. False if the printer couldn't be started."""
    printer.setFullPage(True)
    painter = QPainter()
    if not painter.begin(printer):
        return False
    paper = painter.viewport()
    # Pages are drawn as images, at the printer's resolution up to PRINT_DPI.
    dpi = min(printer.resolution(), PRINT_DPI)
    for count, page in enumerate(pages):
        if count:
            printer.newPage()
        points = document.pagePointSize(page)
        image = document.render(page, QSize(round(points.width() * dpi / 72), round(points.height() * dpi / 72)))
        size = image.size().scaled(paper.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(QPoint((paper.width() - size.width()) // 2, (paper.height() - size.height()) // 2), size)
        painter.fillRect(target, Qt.GlobalColor.white)
        painter.drawImage(target, image)
    painter.end()
    return True


class Highlighter(Proofer):
    """Colors the object keys in raw JSON, and spell-checks its string
    values (the resume's text)."""

    def __init__(self, edit, speller):
        super().__init__(edit, speller)
        self.key_format = QTextCharFormat()
        self.key_format.setForeground(QColor("#8be9fd"))
        self.key_format.setFontWeight(QFont.Weight.DemiBold)

    def prose(self, text):
        # JSON string values, with escapes like \n blanked out.
        return [(match.start(), JSON_ESCAPE.sub(lambda escape: " " * len(escape.group()), match.group()))
                for match in JSON_STRING.finditer(text) if not text[match.end():].lstrip().startswith(":")]

    def highlightBlock(self, text):
        super().highlightBlock(text)
        for match in JSON_KEY.finditer(text):
            self.setFormat(utf16(text, match.start()), utf16(text, match.end()) - utf16(text, match.start()), self.key_format)


class RawTab(QWidget):
    """A plain-text editor for a JSON input file (resume.json)."""

    def __init__(self, window, name):
        super().__init__()
        self.win, self.name = window, name
        self.editor = QPlainTextEdit()
        self.editor.setProperty("kind", "raw")
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setTabStopDistance(2 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.document().setDocumentMargin(16)
        self.highlighter = Highlighter(self.editor, window.speller)
        on_edit(self.editor, self._edited)

        self.wrap_button = button("Wrap: On", self.toggle_wrap)
        actions = QFrame()
        actions.setProperty("kind", "actions")
        bar = QHBoxLayout(actions)
        bar.addWidget(button("Save file", self.save, "primary"))
        bar.addWidget(button("Reload file", window.reload))
        bar.addWidget(button("Pretty-print JSON", self.format_json))
        bar.addWidget(self.wrap_button)
        bar.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.editor)
        layout.addWidget(actions)

    def show_file(self):
        """Picks up edits made elsewhere (the blocks tab, a reload)."""
        if self.editor.toPlainText() != self.win.files[self.name]:
            self.editor.setPlainText(self.win.files[self.name])

    def _edited(self):
        self.win.files[self.name] = self.editor.toPlainText()
        self.win.refresh_tabs()

    def toggle_wrap(self):
        self.set_wrap(self.editor.wordWrapMode() == QTextOption.WrapMode.NoWrap)

    def set_wrap(self, wrap):
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if wrap else QTextOption.WrapMode.NoWrap)
        self.wrap_button.setText("Wrap: On" if wrap else "Wrap: Off")
        self.win.wrap_action.setChecked(wrap)

    def format_json(self):
        try:
            formatted = json.dumps(json.loads(self.editor.toPlainText()), indent=2, ensure_ascii=False)
        except ValueError as error:
            self.win.report(f"Cannot format {self.name}: {error}", "error")
            return
        self.editor.setPlainText(formatted)
        self.win.report(f'Formatted {self.name}. Click "Save file" to persist.')

    def save(self):
        """Saves the file; False if it couldn't."""
        try:
            json.loads(self.win.files[self.name])
        except ValueError as error:
            self.win.report(f"Cannot save {self.name}: invalid JSON — {error}", "error")
            return False
        try:
            self.win.save_file(self.name)
        except (OSError, ValueError) as error:
            self.win.report(str(error), "error")
            return False
        self.win.report(f"Saved input/{self.name}.", "ok")
        return True


class Workshop(QMainWindow):
    def __init__(self, root):
        """Opens the resume folder `root`; OSError if its files can't be read."""
        super().__init__()
        self.root = root  # the resume folder that is open; open_folder() changes it
        self.reopen = None  # the resume folder to restart the editor on, once the window closes
        self.resize(1500, 1000)
        self.files = {}  # each input file's text as edited
        self.saved = {}  # ...and as it is on disk
        self.process = None  # the pdflatex run in progress, if any
        self.updater = Updater(self)
        self.speller = Speller()
        self.speller.open(root)
        self.grammar = Grammar()
        # Missing the optional grammar checker isn't an error; anything else is.
        self.grammar.failed.connect(lambda reason: self.report(f"Grammar checking is off: {reason}", "" if self.grammar.missing else "error"))
        QApplication.instance().aboutToQuit.connect(self.grammar.close)

        title = QLabel("Resume Workshop")
        title.setProperty("kind", "title")
        self.status = QLabel()
        self.status.setProperty("kind", "status")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(title)
        heading.addWidget(label("Edit source files, run the pipeline, and inspect the generated PDF from one window.", "subtitle"))
        heading.addWidget(self.status)
        header = QHBoxLayout()
        header.addLayout(heading, 1)

        self.blocks = BlocksEditor(self)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.blocks, "")
        self.raw_tabs = {}
        for name in EDITABLE_FILES:
            if name not in NO_TAB:
                self.raw_tabs[name] = RawTab(self, name)
                self.tabs.addTab(self.raw_tabs[name], "")
        self.tabs.currentChanged.connect(self._tab_changed)

        self.make_log = QPlainTextEdit()
        self.make_log.setReadOnly(True)
        self.make_log.setProperty("kind", "log")
        self.make_log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.make_log.setFixedHeight(260)
        self.make_output = Collapsible("more")
        self.make_output.head.addWidget(label("Last build output"))
        self.make_output.head.addStretch(1)
        self.make_output.content.addWidget(self.make_log)
        self.make_output.hide()
        self.pdf_view = preview.PdfPreview(self.pdf)
        self.pdf_view.print_requested.connect(self.print_pdf)  # the viewer's own Print button
        side = QFrame()
        side.setProperty("kind", "panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(18, 18, 18, 18)
        side_layout.setSpacing(12)
        side_layout.addWidget(self.make_output)
        self.preview_note = label("")
        self.preview_note.setWordWrap(True)
        self.preview_note.hide()
        side_layout.addWidget(self.preview_note)
        side_layout.addWidget(self.pdf_view, 1)
        self.live = LivePreview(self, self.pdf_view, self.preview_note)

        panel = QFrame()
        panel.setProperty("kind", "panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(self.tabs)
        self.find_bar = FindBar(self.search_targets)
        panel_layout.addWidget(self.find_bar)
        splitter = QSplitter()
        splitter.addWidget(panel)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 15)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([1000, 470])
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(14)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self._build_menus()

        self._open(self.root)
        if self.speller.error:
            self.report(f"Spell checking is off: {self.speller.error}", "error")

    @property
    def input_dir(self):
        return self.root / "input"

    @property
    def pdf(self):
        return self.root / build.PDF

    def _open(self, root):
        """Shows the resume folder `root` in place of the one that is open.
        Raises OSError, changing nothing, if its files can't be read."""
        files = {name: (root / "input" / name).read_text(encoding="utf-8") for name in EDITABLE_FILES}
        self.root = root
        self.setWindowTitle(f"Resume Workshop — {self._short(root)}")
        if self.speller.words != root / "etc" / "dictionary.txt":
            self.speller.open(root)
        self.files, self.saved = files, dict(files)
        self.blocks.reset()
        self._tab_changed(self.tabs.currentIndex())
        self.refresh_tabs()
        self.show_build_output("")
        self.live.open()

    # --- menus -------------------------------------------------------------------

    def _build_menus(self):
        def add(menu, text, slot, shortcut=None, checkable=False):
            action = menu.addAction(text)
            action.triggered.connect(slot if checkable else lambda: slot())
            action.setCheckable(checkable)
            if shortcut:
                action.setShortcut(shortcut)
            return action

        Key, blocks, raw = QKeySequence.StandardKey, self.blocks, self.raw_tabs[RESUME]

        file_menu = self.menuBar().addMenu("&File")
        add(file_menu, "&New Resume…", lambda: self.open_folder(new_resume(self)), Key.New)
        add(file_menu, "&Open Resume Folder…", lambda: self.open_folder(open_resume(self)), Key.Open)
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addSeparator()
        add(file_menu, "&Save", self.save_current, Key.Save)
        add(file_menu, "Save && &Build", self.save_and_build, "Ctrl+B")
        add(file_menu, "&Reload from Disk", self.reload, "Ctrl+R")
        file_menu.addSeparator()
        add(file_menu, "Build Resu&me", self.run_build)
        add(file_menu, "Build and &Name PDF", lambda: self.run_build(named=True))
        file_menu.addSeparator()
        add(file_menu, "Page Set&up…", self.page_setup, "Ctrl+Shift+P")
        add(file_menu, "&Print PDF…", self.print_pdf, Key.Print)
        add(file_menu, "Open P&DF", self.open_pdf, "Ctrl+Shift+O")
        file_menu.addSeparator()
        add(file_menu, "&Import JSON Resume…", self.import_json, "Ctrl+I")
        add(file_menu, "&Export PDF…", self.export_pdf, "Ctrl+E")
        add(file_menu, "Export &TXT…", self.export_txt)
        add(file_menu, "Export &JSON…", self.export_json)
        add(file_menu, "&Download rxresume.json…", self.download_rxresume)
        file_menu.addSeparator()
        add(file_menu, "&Quit", self.close, "Ctrl+Q")

        # Undo to Select All act on whichever text box (or the PDF) has the focus.
        edit_menu = self.menuBar().addMenu("&Edit")
        add(edit_menu, "&Undo", lambda: self._edit("undo"), Key.Undo)
        add(edit_menu, "&Redo", lambda: self._edit("redo"), Key.Redo)
        self.undo_block_action = add(edit_menu, "Undo &Block Change", blocks.undo, "Ctrl+Alt+Z")
        edit_menu.addSeparator()
        add(edit_menu, "Cu&t", lambda: self._edit("cut"), Key.Cut)
        add(edit_menu, "&Copy", lambda: self._edit("copy"), Key.Copy)
        add(edit_menu, "&Paste", lambda: self._edit("paste"), Key.Paste)
        add(edit_menu, "Select &All", lambda: self._edit("selectAll"), Key.SelectAll)
        edit_menu.addSeparator()
        add(edit_menu, "&Find…", self.find_bar.open, Key.Find)
        add(edit_menu, "Find &Next", self.find_bar.find, "F3")
        add(edit_menu, "Find Pre&vious", lambda: self.find_bar.find(backward=True), "Shift+F3")
        add(edit_menu, "R&eplace…", lambda: self.find_bar.open(replacing=True), "Ctrl+H")
        edit_menu.addSeparator()
        self.insert_actions = [
            add(edit_menu, "Insert &Middle Dot (·)", lambda: blocks.insert_char("·"), "Ctrl+."),
            add(edit_menu, "Insert &En Dash (–)", lambda: blocks.insert_char("–"), "Ctrl+-"),
        ]
        self.format_action = add(edit_menu, "Pretty-print &JSON", raw.format_json)

        view_menu = self.menuBar().addMenu("&View")
        add(view_menu, "Resume (&blocks)", lambda: self.tabs.setCurrentWidget(blocks), "Ctrl+1")
        add(view_menu, "&resume.json", lambda: self.select_file(RESUME), "Ctrl+2")
        view_menu.addSeparator()
        self.fold_actions = [
            add(view_menu, "&Expand All", lambda: blocks.set_all_open(True), "Ctrl+Shift+E"),
            add(view_menu, "&Collapse All", lambda: blocks.set_all_open(False), "Ctrl+Shift+C"),
        ]
        self.wrap_action = add(view_menu, "&Wrap Lines", raw.set_wrap, checkable=True)
        self.wrap_action.setChecked(True)
        view_menu.addSeparator()
        add(view_menu, "&Live Preview", self.live.set_enabled, checkable=True).setChecked(True)
        add(view_menu, "&Full Screen", lambda on: self.showFullScreen() if on else self.showNormal(), "F11", checkable=True)

        help_menu = self.menuBar().addMenu("&Help")
        if not distribution.STORE:  # the store updates its own
            add(help_menu, "Check for &Updates…", self.updater.check)
        add(help_menu, "&About Resume Workshop", self.about)

        for menu in (edit_menu, view_menu):
            menu.aboutToShow.connect(self._update_menus)
        self.tabs.currentChanged.connect(self._update_menus)
        self._update_menus()

    @staticmethod
    def _short(folder):
        """A folder's path, with the home folder as ~."""
        home = str(Path.home())
        return "~" + str(folder)[len(home):] if str(folder).startswith(home + os.sep) else str(folder)

    def _fill_recent(self):
        self.recent_menu.clear()
        folders = [folder for folder in project.recent() if folder != self.root]
        for folder in folders:
            self.recent_menu.addAction(self._short(folder)).triggered.connect(lambda _=False, folder=folder: self.open_folder(folder))
        if not folders:
            self.recent_menu.addAction("No other resumes opened yet").setEnabled(False)

    def open_folder(self, folder):
        """Switches to the resume in `folder` (None: the choice was
        canceled), asking about unsaved changes first."""
        if folder is None:
            return
        folder = Path(folder).resolve()
        if folder == self.root:
            self.report(f"{self._short(folder)} is already open.")
            return
        if self.process is not None:
            self.report("Wait for the build to finish before opening another resume.")
            return
        if self.any_dirty() and not self.confirm("Some edits haven't been saved to input/. Discard them?", "Discard changes"):
            return
        previous = self.root
        try:
            self._open(folder)
        except OSError as error:
            self.report(f"Could not open {self._short(folder)}: {error}", "error")
            return
        project.remember(previous)
        project.remember(folder)
        self.report(f"Opened {self._short(folder)}.", "ok")

    def restart(self):
        """Starts the editor again on this folder, as after an update (see
        update.py): closes this window, asking about unsaved changes, and
        has main() start it. False if the window stayed open."""
        self.reopen = self.root
        if not self.close():
            self.reopen = None
        return self.reopen is not None

    def about(self):
        running = f"Version {distribution.VERSION}" if distribution.VERSION else "Running from a checkout"
        QMessageBox.about(self, "About Resume Workshop", f"<b>Resume Workshop</b><br>{running}<br><br><a href=\"{RELEASES}\">{RELEASES}</a>")

    def _update_menus(self, *_):
        """Enables the items that apply to the tab that is showing."""
        on_blocks = self.tabs.currentWidget() is self.blocks
        self.undo_block_action.setEnabled(on_blocks and bool(self.blocks.undo_stack))
        for action in self.insert_actions + self.fold_actions:
            action.setEnabled(on_blocks)
        for action in (self.format_action, self.wrap_action):
            action.setEnabled(not on_blocks)

    def _edit(self, command):
        """Runs an Edit menu command on the focused text box, or copies from the PDF."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QTextEdit, QPlainTextEdit)):
            getattr(focus, command)()
        elif focus is not None and (focus is self.pdf_view or self.pdf_view.isAncestorOf(focus)):
            self.pdf_view.edit(command)

    # --- files -------------------------------------------------------------------

    def report(self, message, kind=""):
        self.status.setText(message)
        restyle(self.status, "state", kind)

    def proof(self, edit, grammar=False):
        """Spell-checks a text box, and grammar-checks it too if asked."""
        Proofer(edit, self.speller, self.grammar if grammar else None)

    def is_dirty(self, name):
        return self.files[name] != self.saved[name]

    def any_dirty(self):
        return any(self.is_dirty(name) for name in self.files)

    def refresh_tabs(self):
        """A dot marks a tab with unsaved changes."""
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if tab is self.blocks:
                text, dirty = "Resume (blocks)", self.is_dirty(RESUME) or self.is_dirty(ORDER)
            else:
                text, dirty = tab.name, self.is_dirty(tab.name)
            self.tabs.setTabText(index, f"{text} •" if dirty else text)
        self.live.changed()

    def search_targets(self):
        """The text boxes Find looks through: the showing tab's, in order."""
        tab = self.tabs.currentWidget()
        return list(self.blocks.controls) if tab is self.blocks else [tab.editor]

    def _tab_changed(self, _index):
        self.find_bar.reset()
        tab = self.tabs.currentWidget()
        if tab is self.blocks:
            self.blocks.open()
        else:
            tab.show_file()

    def select_file(self, name):
        self.tabs.setCurrentWidget(self.raw_tabs[name])

    def load_files(self):
        self.files = {name: (self.input_dir / name).read_text(encoding="utf-8") for name in EDITABLE_FILES}
        self.saved = dict(self.files)
        self.blocks.reset()
        self._tab_changed(self.tabs.currentIndex())
        self.refresh_tabs()

    def reload(self):
        if self.any_dirty() and not self.confirm("Discard unsaved changes and reload all files from disk?", "Reload"):
            return
        try:
            self.load_files()
        except OSError as error:
            self.report(str(error), "error")

    def save_file(self, name):
        """Writes a file's edited text to input/. Raises ValueError rather
        than save a resume.json that doesn't match the JSON Resume schema
        (etc/resume-schema.json), and OSError if the file can't be written."""
        content = self.files[name]
        if name == RESUME:
            errors = schema_errors(content)
            if errors:
                raise ValueError("resume.json does not match the JSON Resume schema: " + "; ".join(errors))
        (self.input_dir / name).write_text(content, encoding="utf-8")
        self.saved[name] = content
        self.refresh_tabs()

    def save_current(self):
        """Saves the tab that is showing; False if it couldn't."""
        return self.tabs.currentWidget().save()

    def save_and_build(self):
        if self.save_current():
            self.run_build()

    def confirm(self, question, action):
        box = QMessageBox(QMessageBox.Icon.Question, "Resume Workshop", question, parent=self)
        discard = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole))
        box.exec()
        return box.clickedButton() is discard

    def closeEvent(self, event):
        if self.any_dirty() and not self.confirm("Some edits haven't been saved to input/. Discard them?", "Discard changes"):
            event.ignore()
        else:
            event.accept()

    # --- building and the PDF ------------------------------------------------------

    def show_build_output(self, text, expand=False):
        self.make_log.setPlainText(text)
        self.make_output.setVisible(bool(text))
        if expand:
            self.make_output.set_open(True)

    def _build_pdf(self, finished):
        """Builds output/resume.pdf from the saved input files, as `make pdf`
        does, without blocking the window; then calls finished(succeeded,
        output), where output is pdflatex's or says what went wrong."""
        if self.process is not None:
            self.report("A build is already running.")
            return

        def done(succeeded, output):
            self.process = None
            if succeeded:
                build.clean(self.root)
            finished(succeeded, output)

        try:
            build.write_tex(self.root)
            self.process = build.run_latex(self, self.root, done)
        except build.BuildError as error:
            finished(False, str(error))

    def _build_failed(self, output):
        self.show_build_output(output, expand=True)
        self.report('The build failed — see "Last build output".', "error")

    def run_build(self, named=False):
        """Builds everything in output/ from the saved input files, as
        `make build` does -- and, if `named`, the copy of the PDF named
        after the resume that `make user` adds."""
        def finished(succeeded, output):
            if not succeeded:
                self._build_failed(output)
                return
            self.live.show_output(built=True)
            try:
                build.write_text(self.root)
                build.write_rxresume(self.root)
                build.write_schema(self.root)
                copy = build.named_copy(self.root) if named else None
            except build.BuildError as error:
                self._build_failed(str(error))
                return
            self.show_build_output(output)
            self.report(f"Built the resume in output/{f', and {copy.name}' if copy else ''}.", "ok")

        self.report("Building the resume...")
        self._build_pdf(finished)

    def import_json(self):
        """Replaces the resume in the editor with a JSON Resume file's. It
        isn't written to input/resume.json until it is saved, so Reload from
        Disk brings the old resume back."""
        path, _ = QFileDialog.getOpenFileName(self, "Import JSON Resume", str(Path.home()), "JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            imported = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(imported, dict):
                raise ValueError("it isn't a JSON object")
            text = json.dumps(imported, indent=2, ensure_ascii=False)
            problems = schema_errors(text)
        except (OSError, ValueError) as error:
            self.report(f"Could not import {path}: {error}", "error")
            return
        if not self.confirm(f"Replace the resume in the editor with {Path(path).name}?\n\ninput/resume.json itself isn't changed until you save.", "Replace"):
            return
        self.files[RESUME] = text
        self.blocks.reset()
        self._tab_changed(self.tabs.currentIndex())
        self.refresh_tabs()
        if problems:
            shown = "; ".join(problems[:3]) + (f"; and {len(problems) - 3} more" if len(problems) > 3 else "")
            self.report(f"Imported {path}, which doesn't match the JSON Resume schema: {shown}. Fix that before saving.", "error")
        else:
            self.report(f"Imported {path}. Save to keep it.", "ok")

    def _save_copy(self, source, name, kind, what):
        """Asks where to save a copy of `source` (an exported file), offering
        `name` in the Downloads folder, and copies it there."""
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        path, _ = QFileDialog.getSaveFileName(self, f"Export {what}", str(Path(downloads) / name), kind)
        if not path:
            self.report("Export canceled.")
            return
        try:
            shutil.copyfile(source, path)
        except OSError as error:
            self.report(str(error), "error")
            return
        unsaved = " It has the saved files only; save and export again to include your unsaved changes." if self.any_dirty() else ""
        self.report(f"Exported {what} to {path}.{unsaved}", "ok")

    def _export_name(self, extension):
        """A file name from the saved resume's basics.name, as `make user`
        derives one: "Todd Takala" -> todd_takala_resume.pdf."""
        try:
            slug = build.slug(json.loads(self.saved[RESUME])["basics"]["name"])
        except (ValueError, LookupError, AttributeError, TypeError):
            slug = ""
        return f"{slug}_resume.{extension}" if slug else f"resume.{extension}"

    def _export_written(self, write, source, name, kind, what):
        """Writes `source` from the saved input files with build.py's
        `write`, then asks where to save a copy."""
        try:
            write(self.root)
        except build.BuildError as error:
            self._build_failed(str(error))
            return
        self._save_copy(self.root / source, name, kind, what)

    def export_pdf(self):
        """Rebuilds output/resume.pdf and asks where to save a copy."""
        def finished(succeeded, output):
            if succeeded:
                self._save_copy(self.pdf, self._export_name("pdf"), "PDF (*.pdf)", "the PDF")
            else:
                self._build_failed(output)

        self.report("Exporting the PDF...")
        self._build_pdf(finished)

    def export_txt(self):
        self._export_written(build.write_text, "output/resume.txt", self._export_name("txt"), "Text (*.txt)", "the text resume")

    def export_json(self):
        """Saves a copy of input/resume.json, the JSON Resume document."""
        self._save_copy(self.input_dir / RESUME, self._export_name("json"), "JSON (*.json)", "the JSON Resume")

    def download_rxresume(self):
        """Regenerates output/rxresume.json from the saved input files and
        asks where to save a copy."""
        self._export_written(build.write_rxresume, "output/rxresume.json", "rxresume.json", "JSON (*.json)", "the Reactive Resume file")

    def page_setup(self):
        """Edits the page margins (input/geometry.yaml) in a dialog. The live
        preview follows the dialog; OK writes the file, Cancel leaves it."""
        try:
            geometry = self.input_dir / GEOMETRY
            text = geometry.read_text(encoding="utf-8")
            dialog = PageSetup(self, text, self._preview_geometry)
        except (OSError, ValueError) as error:
            self.report(f"Page Setup can't edit input/{GEOMETRY} ({error}); edit the file in a text editor.", "error")
            return
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        try:
            if accepted and dialog.text() != text:
                geometry.write_text(dialog.text(), encoding="utf-8")
                self.report(f"Saved input/{GEOMETRY}. Build the resume to update output/resume.pdf.", "ok")
        except OSError as error:
            self.report(str(error), "error")
        finally:
            self._preview_geometry(None)

    def _preview_geometry(self, text):
        self.live.geometry = text
        self.live.changed()

    def print_pdf(self, *_):
        """Prints output/resume.pdf, after asking which printer and pages."""
        document = QPdfDocument(self)
        if not self.pdf.exists() or document.load(str(self.pdf)) != QPdfDocument.Error.None_:
            self.report("Build the resume before printing the PDF.", "error")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.pdf.name)
        # Start from the resume's own paper size (US Letter) rather than the system default.
        printer.setPageSize(QPageSize(document.pagePointSize(0), QPageSize.Unit.Point))
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Print PDF")
        dialog.setOption(QPrintDialog.PrintDialogOption.PrintPageRange)
        dialog.setMinMax(1, document.pageCount())
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        pages = range(document.pageCount())
        if printer.printRange() == QPrinter.PrintRange.PageRange and printer.fromPage():
            pages = range(printer.fromPage() - 1, min(printer.toPage(), document.pageCount()))
        if print_pages(document, pages, printer):
            self.report(f"Sent {self.pdf.name} to {printer.printerName() or printer.outputFileName()}.", "ok")
        else:
            self.report(f"Could not print {self.pdf.name}.", "error")

    def open_pdf(self):
        if not self.pdf.exists():
            self.report("Build the resume before viewing the PDF.", "error")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pdf))):
            self.report(f"Could not open {self.pdf}.", "error")




def main():
    app = application()
    # Ctrl+C, a closed terminal, or `kill` quits like closing the window does
    # (minus the unsaved-changes question), so the grammar checker's server
    # is stopped too. Python only sees a signal while its own code runs, so
    # a timer gives it a turn a few times a second.
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: app.quit())
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(250)
    folder = startup_resume()
    try:
        window = Workshop(folder)
    except OSError as error:
        fatal(f"The editor could not read the input files in {folder / 'input'}: {error}")
    window.show()
    code = app.exec()
    if window.reopen:
        start_editor(window.reopen)
    sys.exit(code)


def start_editor(folder):
    """Starts the editor again on `folder`, as this one closes: after an
    update, this is the new version."""
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("RESUME_WORKSHOP_ROOT", str(folder))
    process = QProcess()
    process.setProcessEnvironment(environment)
    if os.environ.get("APPIMAGE"):
        # The AppImage itself, not the Python inside this run's mount of it.
        process.setProgram(os.environ["APPIMAGE"])
    else:
        process.setProgram(sys.executable)
        process.setArguments(sys.orig_argv[1:])
    process.startDetached()


if __name__ == "__main__":
    main()
