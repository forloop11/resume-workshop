"""The live preview: a moment after the resume's text stops changing, it is
built into a PDF and shown in the preview, with the text of the field being
edited highlighted there.

Unsaved text can't be built in the project itself without saving it, so the
build happens in a scratch copy: a temporary folder with the editor's current
resume.json and section_order.yaml (and geometry.yaml, which Page Setup may
be editing), and links to everything else `make pdf` reads. input/ and output/ are never touched; output/resume.pdf still changes
only when a make target is run.
"""
import json
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer
from PySide6.QtWidgets import QApplication

from document import ORDER, RESUME, ROOT

BUILD_DELAY = 900  # ms after the last change
HIGHLIGHT_DELAY = 200  # ms after moving to another field
LINKED = ["makefile", "scripts", "etc", "input/format.tex"]
GEOMETRY = ROOT / "input" / "geometry.yaml"


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
        self.process = None
        self.again = False  # the text changed during a build
        self.scratch = tempfile.TemporaryDirectory(prefix="resume-workshop-preview-")
        root = Path(self.scratch.name)
        for folder in ("input", "interim", "output"):
            (root / folder).mkdir()
        for name in LINKED:
            (root / name).symlink_to(ROOT / name)
        self.built = root / "output" / "resume.pdf"
        self.builds = 0

        self.build_timer = QTimer(self, singleShot=True, interval=BUILD_DELAY)
        self.build_timer.timeout.connect(self.build)
        self.highlight_timer = QTimer(self, singleShot=True, interval=HIGHLIGHT_DELAY)
        self.highlight_timer.timeout.connect(lambda: self.view.highlight(self.win.blocks.preview_phrases()))
        QApplication.instance().focusChanged.connect(self._focus_changed)
        QApplication.instance().aboutToQuit.connect(self._stop)

    def _content(self):
        return self.win.files[RESUME], self.win.files[ORDER], self._geometry() if self.geometry is None else self.geometry

    @staticmethod
    def _geometry():
        try:
            return GEOMETRY.read_text(encoding="utf-8")
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
        self.view.show_pdf(self.win.output_pdf)
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
        root = Path(self.scratch.name)
        (root / "input" / RESUME).write_text(content[0], encoding="utf-8")
        (root / "input" / ORDER).write_text(content[1], encoding="utf-8")
        (root / "input" / GEOMETRY.name).write_text(content[2], encoding="utf-8")
        process = self.process = QProcess(self)
        process.setWorkingDirectory(str(root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(lambda code, status: self._finished(content, status == QProcess.ExitStatus.NormalExit and code == 0))
        process.errorOccurred.connect(lambda error: error == QProcess.ProcessError.FailedToStart and self._finished(content, False))
        process.start("make", ["pdf"])

    def _finished(self, content, succeeded):
        process, self.process = self.process, None
        if process is None:
            return  # already handled (a failed start also reports "finished")
        output = bytes(process.readAll()).decode("utf-8", "replace")
        process.deleteLater()
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
            self._failed(content, self._reason(output))
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

    @staticmethod
    def _reason(output):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        latex = [line.lstrip("! ") for line in lines if line.startswith("!")]
        ours = [line for line in lines if not line.startswith(("make", "python3 ", "pdflatex ", "mkdir "))]
        reason = (latex or ours or ["make pdf failed"])[0 if latex else -1]
        return reason if len(reason) <= 160 else reason[:157] + "…"

    def _focus_changed(self, _old, new):
        if self.enabled and new in self.win.blocks.controls:
            self.highlight_timer.start()

    def _stop(self):
        self.enabled = False
        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished(1000)
