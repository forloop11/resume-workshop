"""The PDF preview, in one of two forms with the same methods.

PdfPreview() gives the PDF.js viewer (preview_web.py), which has a toolbar
of its own, text that can be selected and copied, and its own search. It
runs in Qt WebEngine -- a Chromium -- which app stores don't accept. So
there is also QtPdfPreview, a plain view drawn by Qt's own PDF module: it
scrolls, fits the pages to the panel's width, and highlights the field being
edited, and that is all. It is used in an app store's build, when Qt
WebEngine isn't there to import, and when $RESUME_WORKSHOP_PREVIEW is
"qtpdf" (to try it).
"""
import os

from PySide6.QtCore import QTimer, Signal
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView

from distribution import STORE


def _web():
    if STORE or os.environ.get("RESUME_WORKSHOP_PREVIEW") == "qtpdf":
        return None
    try:
        import preview_web
    except ImportError:
        return None
    return preview_web


WEB = _web()


def prepare():
    """What the preview needs done before the QApplication is created."""
    if WEB:
        WEB.register_scheme()


def PdfPreview(pdf):
    """A preview showing the file `pdf`, once it exists."""
    return WEB.PdfPreview(pdf) if WEB else QtPdfPreview(pdf)


class QtPdfPreview(QPdfView):
    print_requested = Signal()  # never emitted: this view has no Print button of its own

    def __init__(self, pdf):
        super().__init__(None)
        self.pdf = pdf  # the PDF on show
        self._document = QPdfDocument(self)
        self._search = QPdfSearchModel(self)
        self._search.setDocument(self._document)
        self.setDocument(self._document)
        self.setSearchModel(self._search)  # the view highlights what it finds
        self.setPageMode(QPdfView.PageMode.MultiPage)
        self.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.setMinimumWidth(360)

    def show_pdf(self, pdf=None, phrases=()):
        """(Re)loads the PDF -- or shows `pdf` from now on -- if it has been
        built, then highlights `phrases` as highlight() does."""
        self.pdf = pdf or self.pdf
        self._search.setSearchString("")
        if not self.pdf.exists():
            self._document.close()
            return
        place = self.verticalScrollBar().value()
        self._document.load(str(self.pdf))
        if not self.highlight(phrases):
            # Stay where the reader was, once the new pages are laid out.
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(place))

    def highlight(self, phrases):
        """Highlights, and scrolls to, the first of `phrases` that the PDF
        contains; none of them clears the highlight. Returns whether one
        was found."""
        for phrase in phrases:
            self._search.setSearchString(phrase)
            for page in range(self._document.pageCount()):
                found = self._search.resultsOnPage(page)
                if found:
                    self.pageNavigator().jump(page, found[0].location(), 0)  # zoom 0: as it is
                    return True
        self._search.setSearchString("")
        return False

    def edit(self, command):
        """An Edit menu command; this view has no text to select or copy."""

    def retheme(self):
        """Follows a change of the editor's color theme, which it does anyway."""
