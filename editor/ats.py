"""The ATS check (the ☰ button, File > ATS Check): what scripts/check_ats.py
finds in the resume as it is in the editor, saved or not, and which of a
pasted job description's terms it has.
"""
import html
import json
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSplitter, QTextBrowser, QVBoxLayout, QWidget

import project
import themes
from document import ORDER, RESUME, parse_order

sys.path.insert(0, str(project.SOURCE / "scripts"))

import check_ats  # noqa: E402
import generate_text  # noqa: E402

MARKS = {"ok": ("✓", "ok"), "note": ("•", "warning"), "warn": ("✗", "error")}  # the mark, and its color in the theme


def findings(files):
    """The checker's findings for the editor's files ({name: text}), and
    the resume as text, or None if it can't be written. A resume that
    can't be read at all is one finding saying so."""
    try:
        data = json.loads(files[RESUME])
        _, order, _, headings = parse_order(files[ORDER])
        found = check_ats.check(data, order, headings)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return [check_ats.Finding("warn", f"The resume can't be checked until it is fixed: {error}")], None
    try:
        return found, generate_text.render(data, order, headings)
    except (SystemExit, KeyError, TypeError, AttributeError):
        return found, None


def findings_html(found):
    rows = []
    for finding in found:
        mark, color = MARKS[finding.level]
        rows.append(f'<tr><td style="color:{themes.color(color)}; padding-right:8px">{mark}</td><td style="padding-bottom:5px">{html.escape(finding.text)}</td></tr>')
    counts = {level: sum(finding.level == level for finding in found) for level in MARKS}
    summary = f"{counts['ok']} fine, {counts['note']} to note, {counts['warn']} to fix."
    return f"<p><b>{summary}</b></p><table>{''.join(rows)}</table>"


def match_html(match):
    total = len(match.found) + len(match.missing)
    if not total:
        return "<p>That text has no terms to look for.</p>"
    parts = [f"<p><b>The resume has {len(match.found)} of the job description's {total} main terms.</b></p>"]
    if match.missing:
        parts.append(f'<p><span style="color:{themes.color("error")}">Missing:</span> {html.escape(", ".join(match.missing))}</p>')
    if match.found:
        parts.append(f'<p><span style="color:{themes.color("ok")}">Found:</span> {html.escape(", ".join(match.found))}</p>')
    return "".join(parts)


class AtsPanel(QFrame):
    """The check as a card that slides out at the window's left (the ☰
    button), beside the editor rather than over it: the findings follow the
    resume as it is edited."""

    WIDTH = 360
    REFRESH_DELAY = 600  # ms after the last edit

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.text = None  # the resume as text, for comparing with a job description
        self.setProperty("kind", "panel")
        self.setMaximumWidth(0)  # closed
        self.hide()

        title = QLabel("ATS check")
        title.setProperty("kind", "card-title")
        intro = QLabel("How an applicant tracking system is likely to read the resume as it is in the editor. These are rules of thumb: "
                       "no two systems read alike.")
        intro.setWordWrap(True)
        intro.setProperty("kind", "label")
        self.results = QTextBrowser()
        self.job = QPlainTextEdit()
        self.job.setPlaceholderText("Paste a job description here to see which of its terms the resume has.")
        self.job.textChanged.connect(self._compare)
        self.matches = QTextBrowser()
        self.matches.hide()
        # The three boxes share the card's height; drag the gaps between
        # them to give one more of it.
        self.boxes = QSplitter(Qt.Orientation.Vertical)
        self.boxes.setChildrenCollapsible(False)
        self.boxes.setHandleWidth(10)
        for box, height, least in ((self.results, 420, 80), (self.job, 130, 50), (self.matches, 170, 50)):
            box.setMinimumHeight(least)
            self.boxes.addWidget(box)
        self.boxes.setSizes([420, 130, 170])
        self.boxes.setStretchFactor(0, 1)  # a taller window gives the findings the room

        # The content keeps its width while the card slides, instead of rewrapping.
        content = QWidget()
        content.setFixedWidth(self.WIDTH)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.boxes, 1)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content)
        outer.addStretch(1)

        self.slide = QPropertyAnimation(self, b"maximumWidth", self)
        self.slide.setDuration(180)
        self.slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.slide.finished.connect(lambda: self.setVisible(self.is_open))
        self.is_open = False
        self.timer = QTimer(self, singleShot=True, interval=self.REFRESH_DELAY)
        self.timer.timeout.connect(self.refresh)

    def set_open(self, is_open):
        """Slides the card out, or back in."""
        self.is_open = is_open
        if is_open:
            self.refresh()
            self.show()
        self.slide.stop()
        self.slide.setStartValue(self.maximumWidth())
        self.slide.setEndValue(self.WIDTH if is_open else 0)
        self.slide.start()

    def changed(self):
        """The resume may have changed: check it again once the typing pauses."""
        if self.is_open:
            self.timer.start()

    def refresh(self):
        """Checks the resume as it is in the editor now."""
        found, self.text = findings(self.win.files)
        place = self.results.verticalScrollBar().value()
        self.results.setHtml(findings_html(found))
        self.results.verticalScrollBar().setValue(place)
        self._compare()

    def _compare(self):
        job = self.job.toPlainText()
        if self.text is None or not job.strip():
            self.matches.hide()
            return
        self.matches.setHtml(match_html(check_ats.keywords(job, self.text)))
        self.matches.show()
