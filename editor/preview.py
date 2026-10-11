"""The PDF preview: Mozilla's PDF.js viewer (vendored in pdfjs/, so it works
offline) in a Qt WebEngine view.

The viewer is made of JavaScript modules, which Chromium won't load from
file: URLs, so the view gets it -- and the PDF -- through a URL scheme of its
own, which serves just those files. register_scheme() must run before the
QApplication is created.
"""
import json
import mimetypes
import time
from pathlib import Path

from PySide6.QtCore import QFile, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog

SCHEME = b"resume-workshop"
ORIGIN = "resume-workshop://editor"
PDFJS = Path(__file__).resolve().parent / "pdfjs"
VIEWER = "/pdfjs/web/viewer.html"
DOCUMENT = "/resume.pdf"
PREFERENCES = {"viewerCssTheme": 2, "defaultZoomValue": "page-width", "sidebarViewOnLoad": 0}
MIME_TYPES = {".mjs": "text/javascript", ".wasm": "application/wasm", ".ftl": "text/plain", ".pdf": "application/pdf"}


def register_scheme():
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled | QWebEngineUrlScheme.Flag.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)


class _Files(QWebEngineUrlSchemeHandler):
    """Serves the PDF.js viewer's files and the PDF, and nothing else."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def requestStarted(self, job):
        path = job.requestUrl().path()
        if path == DOCUMENT:
            target = self.view.pdf
        else:
            target = (PDFJS.parent / path.lstrip("/")).resolve()
            if not target.is_relative_to(PDFJS):
                job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
                return
        file = QFile(str(target), job)  # closed and deleted along with the request
        if not file.open(QFile.OpenModeFlag.ReadOnly):
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = MIME_TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        job.reply(mime.encode(), file)


class _Page(QWebEnginePage):
    def acceptNavigationRequest(self, url, _kind, _is_main_frame):
        """Keeps the view on the viewer; a link in the PDF opens in the browser."""
        if url.scheme() == SCHEME.decode() or url.scheme() == "about":
            return True
        QDesktopServices.openUrl(url)
        return False


class PdfPreview(QWebEngineView):
    def __init__(self, pdf):
        super().__init__()
        self.pdf = pdf  # the PDF on show
        page = _Page(self)
        page.setBackgroundColor(QColor("#282a36"))
        page.profile().installUrlSchemeHandler(SCHEME, _Files(self))
        page.profile().downloadRequested.connect(self._download)
        # The viewer keeps its settings in localStorage. Ask for its dark
        # theme, pages fitted to the panel's width, and the "Manage pages"
        # sidebar closed whenever a PDF opens -- otherwise it pops open after
        # each build, because the resume's PDF asks for its outline to show.
        settings = QWebEngineScript()
        settings.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        settings.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        settings.setSourceCode(f"localStorage.setItem('pdfjs.preferences', JSON.stringify({json.dumps(PREFERENCES)}));")
        page.scripts().insert(settings)
        # resumeWorkshopOpen() and resumeWorkshopHighlight(), used below.
        helpers = QWebEngineScript()
        helpers.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        helpers.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)  # where the viewer's own scripts run
        helpers.setSourceCode(Path(__file__).with_name("preview.js").read_text(encoding="utf-8"))
        page.scripts().insert(helpers)
        self.setPage(page)
        self.setMinimumWidth(360)
        self._ready = False  # the viewer has loaded
        self._loading = False  # ...or is on its way
        self._waiting = None  # what to highlight in the PDF a show_pdf() during loading asked for
        self.loadStarted.connect(lambda: setattr(self, "_ready", False))
        self.loadFinished.connect(self._loaded)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    def show_pdf(self, pdf=None, phrases=()):
        """(Re)loads the PDF -- or shows `pdf` from now on -- if it has been
        built, then highlights `phrases` as highlight() does."""
        self.pdf = pdf or self.pdf
        if not self.pdf.exists():
            self._loading, self._waiting = False, None
            self.setUrl(QUrl("about:blank"))
            return
        # The timestamp gets the rebuilt file past the viewer's cache.
        document = f"{DOCUMENT}?ts={time.time_ns()}"
        if self._ready:
            # Swap the document in place, without reloading the viewer.
            self.page().runJavaScript(f"resumeWorkshopOpen({json.dumps(document)}, {json.dumps(list(phrases))})")
        elif self._loading:
            # Asking the viewer to load again while it is still loading can
            # stall it for good; hand it this PDF once it is up instead.
            self._waiting = list(phrases)
        else:
            self._loading = True
            url = QUrl(ORIGIN + VIEWER)
            url.setQuery("file=" + document.replace("?", "%3F").replace("=", "%3D"))
            self.load(url)

    def _loaded(self, ok):
        self._loading = False
        self._ready = ok and self.url().path() == VIEWER
        if self._ready and self._waiting is not None:
            phrases, self._waiting = self._waiting, None
            self.show_pdf(phrases=phrases)

    def highlight(self, phrases):
        """Highlights, and scrolls to, the first of `phrases` that the PDF
        contains; none of them clears the highlight."""
        if self._ready:
            self.page().runJavaScript(f"resumeWorkshopHighlight({json.dumps(list(phrases))})")

    def _download(self, download):
        """The viewer's Download button."""
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", str(Path(download.downloadDirectory()) / self.pdf.name), "PDF (*.pdf)")
        if not path:
            download.cancel()
            return
        download.setDownloadDirectory(str(Path(path).parent))
        download.setDownloadFileName(Path(path).name)
        download.accept()
