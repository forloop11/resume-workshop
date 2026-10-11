"""Drives the editor's window, without a display, through what it does to a
resume folder: building, exporting, switching folders, and the rest."""
import filecmp
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import RESUME, ROOT

# Before Qt loads: no display, the plain PDF preview (no Chromium to start),
# and settings and launchers in a folder of the tests' own.
HOME = tempfile.TemporaryDirectory(prefix="resume-workshop-tests-")
os.environ.update(QT_QPA_PLATFORM="offscreen", RESUME_WORKSHOP_PREVIEW="qtpdf", XDG_CONFIG_HOME=f"{HOME.name}/config",
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


def pdf_text(path):
    document = QPdfDocument()
    document.load(str(path))
    return [document.getAllText(page).text() for page in range(document.pageCount())]


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
