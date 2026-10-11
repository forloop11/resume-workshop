"""The PDF preview: the resume's pages, drawn by Qt's own PDF module.

A plain view: it scrolls, fits the pages to the panel's width, and
highlights the text of the field being edited. (It was once Mozilla's
PDF.js viewer in Qt WebEngine, which had a toolbar, selectable text, and a
search of its own, but was most of the editor's download, and isn't accepted
by app stores.)
"""
from PySide6.QtCore import QTimer
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView


class PdfPreview(QPdfView):
    def __init__(self, pdf):
        super().__init__(None)
        self.pdf = pdf  # the PDF on show
        # Not children of the view: Qt crashes on the way out if the view
        # deletes its own search model.
        self._document = QPdfDocument()
        self._search = QPdfSearchModel()
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
        # The view doesn't redraw by itself when its "current" match is the
        # same number of a different search, as it nearly always is here.
        self.viewport().update()
        for phrase in phrases:
            self._search.setSearchString(phrase)
            for page in range(self._document.pageCount()):
                found = self._search.resultsOnPage(page)
                if found:
                    # The view draws its "current" match boldly; the others
                    # it only tints, too faintly to see. This page's first
                    # match is the first of all: no earlier page had one.
                    self.setCurrentSearchResultIndex(0)
                    # ...which scrolls there only when the number changes;
                    # so go there, once a PDF just loaded has been laid out.
                    place = found[0].location()
                    QTimer.singleShot(0, lambda: self.pageNavigator().jump(page, place, 0))  # zoom 0: as it is
                    return True
        self._search.setSearchString("")
        return False
