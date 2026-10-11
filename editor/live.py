"""The live preview: a moment after the resume's text stops changing, it is
built into a PDF and shown in the preview, with the text of the field being
edited highlighted there.

Unsaved text can't be built in the resume folder itself without saving it,
so the build (build.py) happens in a scratch copy: a temporary folder with
the editor's current resume.json and section_order.yaml (and geometry.yaml,
which Page Setup may be editing), and a link to the folder's format.tex;
pdflatex finds anything else the resume uses, such as a photo, in the folder.
input/ and output/ are never touched; output/resume.pdf still changes only
when the resume is built.
"""
import json
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

import build
from document import ORDER, RESUME

BUILD_DELAY = 900  # ms after the last change
HIGHLIGHT_DELAY = 200  # ms after moving to another field
GEOMETRY = "geometry.yaml"


class LivePreview(QObject):
    def __init__(self, window, view, note):
        """`view` is the PdfPreview to update, and `note` a label that says
        what the preview is showing when that isn't output/resume.pdf."""
        super().__init__(window)
        self.win, self.view, self.note = window, view, note
        self.enabled = True
        self.geometry = None  # geometry.yaml as Page Setup is editing it, while it is open
        self.shown = None  # the (resume.json, section_order.yaml, geometry.yaml) text the preview shows, once known
        self.failed = None  # ...and the text that last failed to build
        self.process = None  # the pdflatex run in progress, if any
        self.run = None  # ...and what tells it from one abandoned since
        self.again = False  # the text changed during a build
        self.scratch = tempfile.TemporaryDirectory(prefix="resume-workshop-preview-")
        self.root = Path(self.scratch.name)
        for folder in ("input", "interim", "output"):
            (self.root / folder).mkdir()
        self.built = self.root / build.PDF
        self.builds = 0

        self.build_timer = QTimer(self, singleShot=True, interval=BUILD_DELAY)
        self.build_timer.timeout.connect(self.build)
        self.highlight_timer = QTimer(self, singleShot=True, interval=HIGHLIGHT_DELAY)
        self.highlight_timer.timeout.connect(lambda: self.view.highlight(self.win.blocks.preview_phrases()))
        QApplication.instance().focusChanged.connect(self._focus_changed)
        QApplication.instance().aboutToQuit.connect(self._stop)

    def open(self):
        """Starts afresh on the resume folder the window has just opened."""
        self.build_timer.stop()
        self._abandon()
        self.geometry = self.shown = self.failed = None
        link = self.root / build.TEX
        link.unlink(missing_ok=True)
        link.symlink_to(self.win.root / build.TEX)
        self.show_output()

    def _content(self):
        return self.win.files[RESUME], self.win.files[ORDER], self._geometry() if self.geometry is None else self.geometry

    def _geometry(self):
        try:
            return (self.win.root / "input" / GEOMETRY).read_text(encoding="utf-8")
        except OSError:
            return ""

    def _saved(self):
        return self.win.saved[RESUME], self.win.saved[ORDER], self._geometry()

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.changed()
        else:
            self.build_timer.stop()
            self.show_output()

    def show_output(self, built=False):
        """Shows output/resume.pdf; `built` says make has just built it from
        the saved files."""
        self.shown = self._saved() if built else None
        self._note("")
        self.view.show_pdf(self.win.pdf)
        if self.enabled:
            self.changed()

    def changed(self):
        """The resume's text, or whether it is saved, may have changed:
        rebuild once it settles."""
        if not self.enabled:
            return
        self._update_note()
        if self._content() not in (self.shown, self.failed):
            self.build_timer.start()

    def build(self):
        content = self._content()
        if not self.enabled or content in (self.shown, self.failed):
            return
        if self.process is not None:
            self.again = True
            return
        try:
            json.loads(content[0])
        except ValueError:
            self._failed(content, "resume.json isn't valid JSON")
            return
        (self.root / "input" / RESUME).write_text(content[0], encoding="utf-8")
        (self.root / "input" / ORDER).write_text(content[1], encoding="utf-8")
        (self.root / "input" / GEOMETRY).write_text(content[2], encoding="utf-8")
        run = self.run = object()
        try:
            build.write_tex(self.root)
            self.process = build.run_latex(self, self.root, lambda succeeded, output: self._finished(run, content, succeeded, output), passes=1,
                                          files=self.win.root)
        except build.BuildError as error:
            self._failed(content, self._reason(str(error)))

    def _finished(self, run, content, succeeded, output):
        if run is not self.run:
            return  # abandoned
        self.process = None
        if succeeded:
            # The viewer gets a copy of its own, as it may still be reading
            # this build's PDF when the next build rewrites it.
            self.builds += 1
            snapshot = self.built.with_name(f"preview-{self.builds}.pdf")
            shutil.copyfile(self.built, snapshot)
            self.built.with_name(f"preview-{self.builds - 2}.pdf").unlink(missing_ok=True)
            self.shown, self.failed = content, None
            self.view.show_pdf(snapshot, self.win.blocks.preview_phrases())
        else:
            self._failed(content, build.latex_error(output))
        self.again = False
        self.changed()

    def _note(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))  # no gap above the preview while there's nothing to say

    def _failed(self, content, reason):
        """Keeps the last good preview on show, and says why it is stale."""
        self.failed, self.reason = content, reason
        self._update_note()

    def _update_note(self):
        content = self._content()
        if content == self.failed:
            self._note(f"Preview not updated: {self.reason}")
        elif content == self.shown and content != self._saved():
            self._note("Preview includes unsaved changes.")
        else:
            self._note("")

    def _reason(self, message):
        """A generator's complaint, without the scratch folder's path."""
        message = " ".join(message.replace(f"{self.root}/", "").split())
        return message if len(message) <= 160 else message[:157] + "…"

    def _focus_changed(self, _old, new):
        if self.enabled and new in self.win.blocks.controls:
            self.highlight_timer.start()

    def _abandon(self):
        """Stops the build in progress, if any, and forgets it."""
        process, self.process, self.run = self.process, None, None
        if process is not None:
            process.kill()
            process.waitForFinished(1000)
        self.again = False

    def _stop(self):
        self.enabled = False
        self._abandon()
