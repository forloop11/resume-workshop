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

    def test_ats_check(self):
        window = self.open(self.folder("ats", RESUME))
        panel = window.ats
        self.assertFalse(panel.isVisible())
        window.ats_button.click()  # the ☰ button slides it out
        wait(lambda: panel.width() == panel.WIDTH)
        self.assertTrue(panel.isVisible() and window.ats_action.isChecked())
        self.assertIn("has a work experience section", panel.results.toPlainText())
        self.assertIn("no LinkedIn", panel.results.toPlainText())
        self.assertTrue(panel.matches.isHidden())
        panel.job.setPlainText("We need Python and Kubernetes. Python daily, Kubernetes weekly.")
        self.assertIn("has 1 of the job description's 2 main terms", panel.matches.toPlainText())
        self.assertIn("Missing: kubernetes", panel.matches.toPlainText())
        # The three boxes are a splitter: the lower two can be given the height.
        panel.boxes.setSizes([200, 300, 250])
        findings, job, matches = panel.boxes.sizes()
        self.assertTrue(job > findings and matches > findings, panel.boxes.sizes())
        self.assertEqual((panel.job.height(), panel.matches.height()), (job, matches))
        # The editor stays usable beside it, and the findings follow the edits, saved or not.
        resume = json.loads(window.files[main.RESUME])
        resume["basics"]["profiles"].append({"network": "LinkedIn", "url": "https://www.linkedin.com/in/ada"})
        resume["skills"][0]["keywords"].append("Kubernetes")
        window.select_file(main.RESUME)
        window.raw_tabs[main.RESUME].editor.setPlainText(json.dumps(resume, indent=2))
        wait(lambda: "There is a LinkedIn profile link" in panel.results.toPlainText())
        self.assertIn("has 2 of the job description's 2 main terms", panel.matches.toPlainText())
        # A resume that can't be read is said, not raised.
        window.raw_tabs[main.RESUME].editor.setPlainText("{ not json")
        wait(lambda: "can't be checked until it is fixed" in panel.results.toPlainText())
        self.assertTrue(panel.matches.isHidden())
        window.ats_action.trigger()  # File > ATS Check closes it again
        wait(lambda: not panel.isVisible())
        self.assertFalse(window.ats_button.isChecked())

    def test_ats_check_makes_room_in_a_narrow_window(self):
        window = self.open(self.folder("narrow", RESUME))
        window.resize(1900, 1000)
        window.show_ats(True)
        self.assertTrue(window.side.isVisible())  # room for the check, the editor, and the preview
        window.resize(1400, 1000)
        self.assertFalse(window.side.isVisible())  # the preview steps aside
        window.show_ats(False)
        self.assertTrue(window.side.isVisible())

    def test_a_section_heading_of_its_own(self):
        folder = self.folder("headings", RESUME)
        order = folder / "input/section_order.yaml"
        order.write_text(order.read_text(encoding="utf-8").replace("- competencies\n", "- competencies: Skills\n"), encoding="utf-8")
        window = self.open(folder)
        doc = window.blocks.doc
        self.assertEqual((doc.headings, doc.heading("competencies"), doc.heading("education")), ({"competencies": "Skills"}, "Skills", "Education"))
        # The card has a Heading field; typing in it rewrites that section's line, and only that.
        field = next(control for control in window.blocks.controls if control.toPlainText() == "Skills")
        field.setPlainText("Technical Skills")
        self.assertIn("- competencies: Technical Skills\n", window.files[main.ORDER])
        self.assertIn("- education\n", window.files[main.ORDER])
        self.assertTrue(window.files[main.ORDER].startswith("# Resume sections"))  # the file's comments are kept
        field.setPlainText("")
        self.assertIn("- competencies\n", window.files[main.ORDER])
        field.setPlainText("Technical Skills")
        window.ats.refresh()
        self.assertIn("'Recognition & Speaking' is not the usual name", window.ats.results.toPlainText())
        self.assertTrue(window.blocks.save())
        main.build.write_text(folder)
        self.assertIn("\nTECHNICAL SKILLS\n", (folder / "output/resume.txt").read_text(encoding="utf-8"))
        if LATEX:
            window.run_build()
            self.built(window)
            self.assertIn("TECHNICAL SKILLS", "\n".join(pdf_text(folder / "output/resume.pdf")))

    def test_bold(self):
        from PySide6.QtGui import QFont, QTextCursor

        window = self.open(self.folder("bold", RESUME))
        blocks = window.blocks
        field = next(control for control in blocks.controls if control.toPlainText().startswith("Builds things 100%"))
        select = lambda start, end: (field.setFocus(), field.setTextCursor(span(field, start, end)))  # noqa: E731
        blocks.last_field = field

        def span(field, start, end):
            cursor = QTextCursor(field.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            return cursor

        select(7, 19)  # "things 100% " with the space after it
        blocks.toggle_bold()
        self.assertEqual(field.toPlainText(), "Builds **things 100%** of the time & writes about them.")
        self.assertIn("Builds **things 100%** of the time", window.files[main.RESUME])
        self.assertEqual(field.textCursor().selectedText(), "**things 100%**")
        # ...shown bold in the field, its stars faint.
        weights = lambda: {(piece.start, piece.length): piece.format.fontWeight()  # noqa: E731
                           for piece in field.document().firstBlock().layout().formats()}
        wait(lambda: weights().get((9, 11)) == QFont.Weight.Bold, 10)  # once the field has been redrawn
        # The preview is searched for the words, without the stars.
        self.assertIn("Builds things 100% of the time & writes about them.", blocks.preview_phrases())
        # Again turns it off: with the stars selected, with just the words, and from a cursor inside.
        blocks.toggle_bold()
        self.assertEqual(field.toPlainText(), "Builds things 100% of the time & writes about them.")
        blocks.toggle_bold()
        select(9, 20)
        blocks.toggle_bold()
        self.assertEqual(field.toPlainText(), "Builds things 100% of the time & writes about them.")
        select(2, 2)  # no selection: the word the cursor is in
        blocks.toggle_bold()
        self.assertEqual(field.toPlainText(), "**Builds** things 100% of the time & writes about them.")
        select(5, 5)
        blocks.toggle_bold()
        self.assertEqual(field.toPlainText(), "Builds things 100% of the time & writes about them.")
        if LATEX:
            select(0, 6)
            blocks.toggle_bold()
            self.assertTrue(blocks.save())
            window.run_build()
            self.built(window)
            self.assertIn("Builds things 100% of the time", "\n".join(pdf_text(window.root / "output/resume.pdf")))
            self.assertIn("\\textbf{Builds} things", (window.root / "interim/resume_content.tex").read_text(encoding="utf-8"))

    def test_links_in_the_preview_open_when_clicked(self):
        from PySide6.QtCore import QObject, QPoint, QUrl, Slot
        from PySide6.QtTest import QTest

        folder = self.folder("pdflinks", RESUME)
        shutil.copy(ROOT / "output/resume.pdf", folder / "output/resume.pdf")
        window = self.open(folder)
        window.live.set_enabled(False)  # keep that PDF on show
        view = window.pdf_view

        class Browser(QObject):
            opened = []

            @Slot(QUrl)
            def open(self, url):
                self.opened.append(url.toString())

        browser = Browser()
        for scheme in ("http", "https", "mailto"):  # in place of the system's browser and mail program
            main.QDesktopServices.setUrlHandler(scheme, browser, "open")
            self.addCleanup(main.QDesktopServices.unsetUrlHandler, scheme)
        wait(lambda: view.viewport().width() > 300 and view.page_rects())
        page = view.page_rects()[0]
        scale = page.width() / view._document.pagePointSize(0).width()
        links = view._page_links(0)
        self.assertGreaterEqual(len(links), 3)
        for where, url in links:
            spot = QPoint(round(page.left() + where.center().x() * scale), round(page.top() + where.center().y() * scale))
            QTest.mouseMove(view.viewport(), spot)
            self.assertEqual(view.viewport().cursor().shape(), main.Qt.CursorShape.PointingHandCursor)
            self.assertEqual(view.viewport().toolTip(), url.toString())
            QTest.mouseClick(view.viewport(), main.Qt.MouseButton.LeftButton, pos=spot)
            self.assertEqual(browser.opened[-1], url.toString())
        # Off a link: an arrow, and a click opens nothing.
        blank, count = QPoint(round(page.left()) + 3, round(page.top()) + 3), len(browser.opened)
        QTest.mouseMove(view.viewport(), blank)
        self.assertEqual(view.viewport().cursor().shape(), main.Qt.CursorShape.ArrowCursor)
        QTest.mouseClick(view.viewport(), main.Qt.MouseButton.LeftButton, pos=blank)
        self.assertEqual(len(browser.opened), count)
        # Where the pages are worked out to be is where Qt draws them: a search match is painted in its place.
        plain = view.viewport().grab().toImage()
        self.assertTrue(view.highlight([pdf_text(folder / "output/resume.pdf")[0].split("\n")[0].strip()]))
        match = view._search.resultsOnPage(0)[0].rectangles()[0]
        marked = view.viewport().grab().toImage()
        changed = [(x, y) for y in range(marked.height()) for x in range(marked.width()) if marked.pixel(x, y) != plain.pixel(x, y)]
        self.assertTrue(changed)
        painted = (min(x for x, _ in changed), min(y for _, y in changed), max(x for x, _ in changed), max(y for _, y in changed))
        page = view.page_rects()[0]
        worked_out = (page.left() + match.left() * scale, page.top() + match.top() * scale,
                      page.left() + match.right() * scale, page.top() + match.bottom() * scale)
        for drawn, expected in zip(painted, worked_out):
            self.assertAlmostEqual(drawn, expected, delta=4)

    def test_installing_the_grammar_checker(self):
        import proofing

        window = self.open(self.folder("grammar", RESUME))
        packages = Path(HOME.name) / "data/resume-workshop/packages"
        self.assertEqual(proofing.PACKAGES, packages)
        program, arguments = proofing.install_command()
        self.assertEqual((program, arguments[2:5], arguments[-4:-2]), (sys.executable, ["-m", "pip", "install"], ["--target", str(packages)]))
        self.assertTrue(Path(arguments[-1]).is_file())  # requirements-grammar.txt
        if proofing.grammar_installed():
            self.skipTest("language_tool_python is installed on this machine already")
        edit_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "&Edit")
        edit_menu.aboutToShow.emit()
        self.assertEqual(window.grammar_action.text(), "Install &Grammar Checker…")
        # Without it, grammar checking turns itself off, saying why.
        window.grammar.request("She go to school.")
        wait(lambda: window.grammar.off)
        self.assertTrue(window.grammar.missing)
        # Install: a stand-in for pip, that writes a stand-in for the package.
        package = "\n".join([
            "class Match:",
            "    offset, error_length, message, replacements, rule_id = 4, 2, 'Use goes.', ['goes'], 'RULE'",
            "class LanguageTool:",
            "    def __init__(self, language): self.disabled_rules = set()",
            "    def check(self, text): return [Match()]",
            "    def close(self): pass",
        ])
        stand_in = ("import pathlib, sys\n"
                    "folder = pathlib.Path(sys.argv[1]) / 'language_tool_python'\n"
                    "folder.mkdir(parents=True)\n"
                    "(folder / '__init__.py').write_text(sys.argv[2])\n")
        main.install_command = lambda: (sys.executable, ["-c", stand_in, str(packages), package])
        self.addCleanup(setattr, main, "install_command", proofing.install_command)
        self.addCleanup(sys.modules.pop, "language_tool_python", None)
        self.addCleanup(shutil.rmtree, packages, True)
        QTimer.singleShot(200, lambda: next(button for button in main.QApplication.activeModalWidget().buttons() if button.text() == "Install").click())
        window.install_grammar()
        wait(lambda: window.installing is None and "grammar checker" in window.status.text())
        self.assertIn("Installed the grammar checker", window.status.text())
        self.assertTrue(proofing.grammar_installed())
        edit_menu.aboutToShow.emit()
        self.assertEqual(window.grammar_action.text(), "Update &Grammar Checker…")
        # ...and it is at work, without restarting the editor.
        self.assertFalse(window.grammar.off)
        window.grammar.request("She go to school.")
        wait(lambda: window.grammar.problems("She go to school."))
        self.assertEqual(window.grammar.problems("She go to school.")[0][:3], (4, 6, "Use goes."))
        window.grammar.close()

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
