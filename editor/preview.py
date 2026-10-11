"""The PDF preview: the resume's pages, drawn by Qt's own PDF module.

A plain view: it scrolls, fits the pages to the panel's width, highlights
the text of the field being edited, and opens the PDF's links when they are
clicked. (It was once Mozilla's PDF.js viewer in Qt WebEngine, which had a
toolbar, selectable text, and a search of its own, but was most of the
editor's download, and isn't accepted by app stores.)
"""
from PySide6.QtCore import QModelIndex, QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtPdf import QPdfDocument, QPdfLinkModel, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView

# The kinds of link a click opens: a web page, or a message to write.
OPENABLE = {"http", "https", "mailto"}


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
        self._links = {}  # page -> [(where on the page, in points; its address)], once asked for
        self._pressed = None  # the link the mouse button went down on
        self.viewport().setMouseTracking(True)  # for the hand over a link

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
        self._links = {}
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

    # --- links ---------------------------------------------------------------------

    def page_rects(self):
        """Where each page is drawn, in the view's own coordinates (the
        viewport's, scrolled): QPdfView lays its pages out so -- one above
        the other, each as wide as the view less its margins, and centered
        -- but doesn't say where."""
        margins, viewport = self.documentMargins(), self.viewport()
        dots = self.logicalDpiX() / 72  # screen dots per PDF point
        sizes = []
        for page in range(self._document.pageCount()):
            size = (self._document.pagePointSize(page) * dots).toSize()
            sizes.append(size * ((viewport.width() - margins.left() - margins.right()) / size.width()) if size.width() else size)
        width = max([viewport.width(), *(size.width() for size in sizes)])
        rects, top = [], margins.top()
        for size in sizes:
            left = (width - size.width()) // 2
            rects.append(QRectF(left - self.horizontalScrollBar().value(), top - self.verticalScrollBar().value(), size.width(), size.height()))
            top += size.height() + self.pageSpacing()
        return rects

    def _page_links(self, page):
        if page not in self._links:
            model = QPdfLinkModel()
            model.setDocument(self._document)
            model.setPage(page)
            found = []
            for row in range(model.rowCount(QModelIndex())):
                index = model.index(row, 0)
                url = model.data(index, QPdfLinkModel.Role.Url.value)
                if isinstance(url, QUrl) and url.scheme() in OPENABLE:
                    found.append((model.data(index, QPdfLinkModel.Role.Rectangle.value), url))
            self._links[page] = found
        return self._links[page]

    def link_at(self, position):
        """The address of the link drawn at `position` in the viewport, or None."""
        for page, rect in enumerate(self.page_rects()):
            if rect.contains(QPointF(position)) and rect.width():
                scale = self._document.pagePointSize(page).width() / rect.width()  # points per dot
                point = QPointF((position.x() - rect.left()) * scale, (position.y() - rect.top()) * scale)
                return next((url for where, url in self._page_links(page) if where.contains(point)), None)
        return None

    def mouseMoveEvent(self, event):
        url = self.link_at(event.position())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if url else Qt.CursorShape.ArrowCursor)
        self.viewport().setToolTip(url.toString() if url else "")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = self.link_at(event.position()) if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # A click: the button let go on the link it went down on.
        pressed, self._pressed = self._pressed, None
        if pressed is not None and event.button() == Qt.MouseButton.LeftButton and self.link_at(event.position()) == pressed:
            QDesktopServices.openUrl(pressed)
        super().mouseReleaseEvent(event)
