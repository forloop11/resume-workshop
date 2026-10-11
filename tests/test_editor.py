"""Drives the editor's window, without a display, through what it does to a
resume folder: building, exporting, switching folders, and the rest."""
import filecmp
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests import RESUME, ROOT

# Before Qt loads: no display, and settings and launchers in a folder of the
# tests' own.
HOME = tempfile.TemporaryDirectory(prefix="resume-workshop-tests-")
os.environ.update(QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=f"{HOME.name}/config",
                  XDG_DATA_HOME=f"{HOME.name}/data")

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtPdf import QPdfDocument
except ImportError:
    QTimer = None
LATEX = bool(shutil.which("pdflatex") and shutil.which("make"))


def setUpModule():
    if QTimer is None:
        raise unittest.SkipTest("needs PySide6")
    global main, project, themes, launcher
    import launcher
    import main
    import project
    import themes
    main.application()


def tearDownModule():
    HOME.cleanup()


def wait(until, seconds=60):
    """Lets the editor run until until() is true."""
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: until() and loop.quit())
    poll.start(20)
    QTimer.singleShot(seconds * 1000, loop.quit)
    loop.exec()
    poll.stop()
    if not until():
        raise AssertionError("timed out")


def png():
    """A small one-color PNG image, as bytes."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\x1f\x3a\x5f" * 32 for _ in range(32))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def pdf_text(path):
    document = QPdfDocument()
    document.load(str(path))
    return [document.getAllText(page).text() for page in range(document.pageCount())]


def PaintWatch(widget):
    """Counts the times `widget` is redrawn from now on, as .paints."""
    from PySide6.QtCore import QEvent, QObject

    class Watch(QObject):
        paints = 0

        def eventFilter(self, _watched, event):
            self.paints += event.type() == QEvent.Type.Paint
            return False

    watch = Watch(widget)
    widget.installEventFilter(watch)
    return watch


class Editor(unittest.TestCase):
    def folder(self, name, resume=None):
        folder = Path(HOME.name) / f"{self.id().rsplit('.', 1)[-1]}-{name}"
        project.create(folder)
        if resume:
            (folder / "input" / "resume.json").write_text(json.dumps(resume, indent=2, ensure_ascii=False), encoding="utf-8")
        return folder

    def open(self, folder):
        window = main.Workshop(folder)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.live._stop)
        window.show()
        return window

    def built(self, window):
        wait(lambda: window.process is None and window.status.text().startswith(("Built", "The build failed")))
        self.assertTrue(window.status.text().startswith("Built"), window.make_log.toPlainText()[-2000:])

    @unittest.skipUnless(LATEX, "needs make and pdflatex")
    def test_builds_what_make_builds(self):
        ours, makes = self.folder("editor", RESUME), self.folder("make", RESUME)
        subprocess.run(["make", "build", "user"], cwd=makes, check=True, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        window = self.open(ours)
        wait(lambda: window.live.shown is not None)  # the live preview, built from a scratch copy
        self.assertEqual(list((ours / "output").iterdir()), [])
        window.run_build(named=True)
        self.built(window)
        names = sorted(path.name for path in (makes / "output").iterdir())
        self.assertEqual(sorted(path.name for path in (ours / "output").iterdir()), names)
        self.assertIn("ada_example_resume.pdf", names)
        for name in ("interim/header.tex", "interim/geometry.tex", "interim/resume_content.tex", "output/resume.txt",
                     "output/rxresume.json", "output/resume-workshop.json"):
            self.assertTrue(filecmp.cmp(ours / name, makes / name, shallow=False), name)
        self.assertEqual(pdf_text(ours / "output/resume.pdf"), pdf_text(makes / "output/resume.pdf"))
        self.assertIn("ADA EXAMPLE", pdf_text(ours / "output/resume.pdf")[0])

    def test_starts_and_quits_cleanly(self):
        """The editor as it is really started, told to quit as a closing
        terminal tells it: a crash on the way out fails this."""
        folder = self.folder("run", RESUME)
        shutil.copy(ROOT / "output/resume.pdf", folder / "output/resume.pdf")  # something for the preview to show
        editor = subprocess.Popen([sys.executable, "-B", str(ROOT / "editor/main.py")], stderr=subprocess.PIPE, text=True,
                                  env={**os.environ, "RESUME_WORKSHOP_ROOT": str(folder)})
        time.sleep(5)
        self.assertIsNone(editor.poll(), "the editor exited by itself")
        editor.send_signal(signal.SIGTERM)
        errors = editor.communicate(timeout=30)[1]
        self.assertEqual(editor.returncode, 0, errors[-2000:])
        self.assertNotIn("Traceback", errors)

    def test_preview_highlights_the_field_being_edited(self):
        folder = self.folder("highlight", RESUME)
        shutil.copy(ROOT / "output/resume.pdf", folder / "output/resume.pdf")
        window = self.open(folder)
        window.live.set_enabled(False)  # keep that PDF on show
        view, pages = window.pdf_view, pdf_text(folder / "output/resume.pdf")
        phrase = pages[-1].split("\n")[0].strip()  # a line of the last page
        self.assertTrue(view.highlight(["not in the resume at all", phrase]))
        # As the view's current match: the only kind it draws visibly.
        self.assertEqual((view._search.searchString(), view.currentSearchResultIndex()), (phrase, 0))
        wait(lambda: view.verticalScrollBar().value() > 0)  # scrolled to it
        # Another match, in view already: the preview is redrawn all the same.
        other = next(line.strip() for line in pages[-1].split("\n")[1:] if len(line.strip()) > 8)
        settled = time.monotonic() + 0.3  # past the redraw that scrolling causes
        wait(lambda: time.monotonic() > settled)
        watch = PaintWatch(view.viewport())
        self.assertTrue(view.highlight([other]))
        wait(lambda: watch.paints)
        self.assertFalse(view.highlight(["not in the resume at all"]))
        self.assertEqual(view._search.searchString(), "")

    @unittest.skipUnless(LATEX, "needs make and pdflatex")
    def test_every_field_builds(self):
        from tests.test_generators import EveryField

        resume = {**RESUME, **EveryField.RESUME}
        folder = self.folder("all", resume)
        (folder / "input/photo.png").write_bytes(png())
        window = self.open(folder)
        wait(lambda: window.live.shown is not None or window.live.failed is not None)
        self.assertIsNone(window.live.failed, window.preview_note.text())
        # The live preview's copy of the folder has no photo; pdflatex finds the folder's.
        self.assertIn("photo.png", (window.live.root / "output/resume.log").read_text(encoding="utf-8", errors="replace"))
        window.run_build()
        self.built(window)
        text = "\n".join(pdf_text(folder / "output/resume.pdf"))
        for printed in ("1 Main St, Apt 2, Springfield, IL 62701, US", "Mastodon: example.social/@ada", "Makers of anvils & rockets_2",
                        "Prize, The Academy (Jun 2024)", "Author, Maintainer, Tool Foundation, application", "Version v1.2.0"):
            self.assertIn(printed, text)
        # A layout from before the photo, without graphicx: it builds, leaving the photo out.
        layout = folder / "input/format.tex"
        layout.write_text(layout.read_text(encoding="utf-8").replace("\\usepackage{graphicx}", "%"), encoding="utf-8")
        window.run_build()
        self.built(window)

    def test_url_fields_can_be_tested_and_opened(self):
        from PySide6.QtWidgets import QPushButton

        from tests.test_links import site

        base, stop = site()
        self.addCleanup(stop)
        resume = json.loads(json.dumps(RESUME))
        resume["basics"]["url"] = base + "/200"
        resume["basics"]["profiles"] = [{"network": "Gone", "url": base + "/404"}]
        window = self.open(self.folder("links", resume))
        buttons = lambda text: [b for b in window.blocks.findChildren(QPushButton) if b.text() == text]  # noqa: E731
        self.assertEqual(len(buttons("Test")), len(buttons("Open")))  # a pair beside each address field
        opened = []
        self.addCleanup(setattr, main.QDesktopServices, "openUrl", main.QDesktopServices.openUrl)
        main.QDesktopServices.openUrl = lambda url: opened.append(url.toString()) or True
        buttons("Open")[0].click()
        self.assertEqual(opened, [base + "/200"])
        works, gone = buttons("Test")[:2]  # the website's, and the profile link's
        works.click()
        wait(lambda: works.text() == "✓ Test")
        self.assertIn("works", window.status.text())
        gone.click()
        wait(lambda: gone.text() == "✗ Test")
        self.assertIn("no such page", window.status.text())

    def test_exports_and_failures(self):
        window = self.open(self.folder("one", RESUME))
        saved = []
        window._save_copy = lambda source, name, kind, what: saved.append((Path(source).name, name))
        window.export_txt()
        window.download_rxresume()
        self.assertEqual(saved, [("resume.txt", "ada_example_resume.txt"), ("rxresume.json", "rxresume.json")])
        self.assertIn("ADA EXAMPLE", (window.root / "output/resume.txt").read_text(encoding="utf-8"))
        # A resume the generators refuse: reported, not raised.
        broken = json.loads(json.dumps(RESUME))
        del broken["basics"]["name"]
        (window.root / "input/resume.json").write_text(json.dumps(broken), encoding="utf-8")
        window.export_txt()
        self.assertEqual(len(saved), 2)
        window.run_build()
        self.assertIn("failed", window.status.text())
        self.assertIn("basics.name", window.make_log.toPlainText())

    def test_switching_folders(self):
        first, second = self.folder("first", RESUME), self.folder("second")
        (first / "etc/dictionary.txt").write_text("Zzyzxword\n", encoding="utf-8")
        window = self.open(first)
        knows = lambda word: window.speller.dictionary is None or window.speller.dictionary.check(word)  # noqa: E731
        self.assertTrue(knows("Zzyzxword"))
        window.open_folder(second)
        self.assertEqual(window.root, second)
        self.assertIn(second.name, window.windowTitle())
        self.assertIn('"Your Name"', window.files[main.RESUME])
        self.assertFalse(window.speller.dictionary and knows("Zzyzxword"))
        self.assertEqual(project.recent()[:2], [second, first])
        window.open_folder(Path(HOME.name) / "missing")
        self.assertEqual(window.root, second)
        self.assertIn("Could not open", window.status.text())

    def test_folder_with_older_build_files(self):
        folder = self.folder("old", RESUME)
        self.assertEqual(project.outdated(folder), [])
        (folder / "scripts/jsonresume.py").write_text("# an older version\n", encoding="utf-8")
        (folder / "makefile").unlink()
        self.assertEqual(project.outdated(folder), ["makefile", "scripts"])
        window = self.open(folder)
        if not main.build.missing(folder) and not window.speller.error:  # which would be said first
            self.assertIn("Update Folder's Build Files", window.status.text())
        project.update_build_files(folder)
        self.assertEqual(project.outdated(folder), [])
        self.assertIn('"Ada Example"', (folder / "input/resume.json").read_text(encoding="utf-8"))  # the resume is left alone

    def test_missing_tex_packages_are_named(self):
        folder = self.folder("tex")
        self.assertIsNone(main.build.missing(folder) if LATEX else None)
        (folder / "input/format.tex").write_text("\\usepackage{xcolor}\n\\usepackage[a]{nosuchpackage}\n", encoding="utf-8")
        if shutil.which("kpsewhich"):
            self.assertIn("nosuchpackage", main.build.missing(folder))
            self.assertNotIn("xcolor,", main.build.missing(folder))

    def test_themes(self):
        window = self.open(self.folder("themes", RESUME))
        app = main.QApplication.instance()
        qss = (ROOT / "editor/style.qss").read_text(encoding="utf-8")
        named = set(main.re.findall(r"@([a-z]+(?:-[a-z]+)*)", qss))
        self.assertLessEqual(named, set(themes.ROLES))
        for name in themes.THEMES:
            window.set_theme(name)
            self.assertEqual((themes.current, themes.saved()), (name, name))
            self.assertNotIn("@", app.styleSheet())
        window.set_theme(themes.DEFAULT)

    def test_launcher(self):
        appimage = Path(HOME.name) / 'odd "name" 100%.AppImage'
        os.environ["APPIMAGE"], launcher.SELF_UPDATING = str(appimage), True
        self.addCleanup(os.environ.pop, "APPIMAGE")
        self.addCleanup(setattr, launcher, "SELF_UPDATING", False)
        self.assertFalse(launcher.installed())
        launcher.install()
        entry = Path(HOME.name) / "data/applications/resume-workshop.desktop"
        self.assertIn('Exec="' + str(appimage).replace('"', '\\"').replace("%", "%%") + '"\n', entry.read_text(encoding="utf-8"))
        self.assertTrue(launcher.installed() and (Path(HOME.name) / "data/icons/hicolor/scalable/apps/resume-workshop.svg").exists())
        launcher.remove()
        self.assertFalse(launcher.installed() or entry.exists())


if __name__ == "__main__":
    unittest.main()
