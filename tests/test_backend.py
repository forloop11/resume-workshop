"""The Tauri editor's backend (app/backend/server.py): its answers to the
window's requests, asked as the window asks them, a line of JSON each.

Needs jsonschema; the tests that build a PDF also need pdflatex or Tectonic.
"""
import base64
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import RESUME, ROOT

sys.path.insert(0, str(ROOT / "app" / "backend"))

try:
    import jsonschema  # noqa: F401
    import server
except (ImportError, SystemExit):
    server = None


@unittest.skipUnless(server, "needs jsonschema")
class Backend(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="resume-workshop-backend-")
        self.addCleanup(self.home.cleanup)
        # Its own settings folder, so the tests don't touch the user's list of recent resumes.
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": f"{self.home.name}/config", "XDG_DATA_HOME": f"{self.home.name}/data"})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("RESUME_WORKSHOP_ROOT", None)
        self.backend = server.Backend()
        self.addCleanup(self.backend.preview_builds.scratch.cleanup)
        self.folder = Path(self.home.name) / "resume"
        self.requests = 0

    def ask(self, method, **params):
        """The backend's answer to one request, through serve()."""
        self.requests += 1
        answers = []
        server.serve(self.backend, [json.dumps({"id": self.requests, "method": method, "params": params})], answers.append)
        answer = json.loads(answers[0])
        self.assertEqual(answer["id"], self.requests)
        return answer

    def result(self, method, **params):
        answer = self.ask(method, **params)
        self.assertNotIn("error", answer)
        return answer["result"]

    def opened(self):
        return self.result("create", folder=str(self.folder))

    def test_starts_with_what_the_window_needs(self):
        started = self.result("startup")
        self.assertIn("Dracula", started["themes"])
        self.assertIn({"id": "education", "label": "Education", "list": "education"}, started["sections"])
        self.assertEqual(started["channel"], "source")

    def test_creates_and_opens_a_resume_folder(self):
        opened = self.opened()
        self.assertEqual(opened["root"], str(self.folder.resolve()))
        self.assertEqual(json.loads(opened["files"]["resume.json"])["basics"]["name"], "Your Name")
        self.assertIn("- summary", opened["files"]["section_order.yaml"])
        self.assertIn("top:", opened["files"]["geometry.yaml"])
        self.assertIsNone(opened["pdf"])
        self.assertEqual([entry["folder"] for entry in self.result("recent")], [str(self.folder.resolve())])
        self.assertIn("isn't empty", self.ask("create", folder=str(self.folder))["error"])
        self.assertIn("isn't a resume folder", self.ask("open", folder=self.home.name)["error"])

    def test_saves_only_a_resume_that_matches_the_schema(self):
        opened = self.opened()
        resume = json.loads(opened["files"]["resume.json"])
        resume["basics"]["name"] = "Ada Example"
        self.assertEqual(self.result("save", root=opened["root"], files={"resume.json": json.dumps(resume, indent=2)}), {"saved": ["resume.json"]})
        self.assertEqual(json.loads(self.result("read", root=opened["root"])["resume.json"])["basics"]["name"], "Ada Example")
        resume["basics"]["email"] = "not an address"
        self.assertIn("does not match the JSON Resume schema", self.ask("save", root=opened["root"], files={"resume.json": json.dumps(resume)})["error"])
        self.assertIn("invalid JSON", self.ask("save", root=opened["root"], files={"resume.json": "{"})["error"])
        self.assertIn("isn't one of the files", self.ask("save", root=opened["root"], files={"../makefile": ""})["error"])
        self.assertEqual(json.loads((self.folder / "input/resume.json").read_text(encoding="utf-8"))["basics"]["email"], "you@example.com")

    def test_says_what_a_save_would_be_turned_down_for(self):
        opened = self.opened()
        resume = json.loads(opened["files"]["resume.json"])
        self.assertEqual(self.result("problems", resume=json.dumps(resume), order=opened["files"]["section_order.yaml"])["problems"], [])
        resume["basics"]["name"] = ""
        resume["skills"].append({"name": "competency", "keywords": ["first skill"]})
        found = self.result("problems", resume=json.dumps(resume), order=opened["files"]["section_order.yaml"])
        self.assertEqual(found["problems"], ["Header: name is required."])
        self.assertTrue(all(found["duplicates"]))
        self.assertIn("error", self.ask("problems", resume="[]", order=""))

    def test_checks_the_resume_as_an_ats_reads_it(self):
        opened = self.opened()
        files = opened["files"]
        found = self.result("ats", resume=files["resume.json"], order=files["section_order.yaml"], job="We need Python, and a first skill.")
        self.assertTrue(any(finding["level"] == "ok" for finding in found["findings"]))
        self.assertIn("python", found["match"]["missing"])
        self.assertIsNone(self.result("ats", resume=files["resume.json"], order=files["section_order.yaml"])["match"])
        self.assertEqual(self.result("ats", resume="{", order="")["findings"][0]["level"], "warn")

    def test_tells_a_web_address_from_what_is_not_one(self):
        self.assertEqual(self.result("test_link", url="mailto:me@example.com")["state"], "error")

    def test_an_unknown_request_is_an_error_not_a_crash(self):
        self.assertIn("no nope", self.ask("nope")["error"])
        self.assertIn("TypeError", self.ask("open")["error"])

    def test_compares_this_version_with_the_latest_release(self):
        import update

        release = update.Release("9.0.0", "https://example.com/release", "What's new.", "https://example.com/a", 3, None)
        with mock.patch.object(update, "latest", return_value=release):
            found = self.result("check_update")
            self.assertEqual((found["state"], found["version"], found["checkout"], found["installable"]), ("newer", "9.0.0", True, False))
            with mock.patch.object(server.distribution, "VERSION", "9.0.0"):
                self.assertEqual(self.result("check_update"), {"state": "latest", "message": "Resume Workshop 9.0.0 is the latest version."})
            with mock.patch.object(server.distribution, "STORE", True):  # the store updates its own
                self.assertIn("store", self.ask("check_update")["error"])
        with mock.patch.object(update, "latest", return_value=None):
            self.assertEqual(self.result("check_update")["state"], "none")
        with mock.patch.object(update, "latest", side_effect=OSError("no network")):
            self.assertEqual(self.ask("check_update")["error"], "Could not check for updates: no network")
        self.assertIn("no update", self.ask("install_update")["error"])

    def test_installs_an_update_over_the_running_appimage(self):
        import update

        appimage = Path(self.home.name) / "Resume_Workshop-x86_64.AppImage"
        appimage.write_bytes(b"old")
        release = update.Release("9.0.0", "https://example.com/release", "", "https://example.com/a", 3, None)

        def install(found, target):
            self.assertIs(found, release)
            Path(target).write_bytes(b"new")

        with mock.patch.object(update, "latest", return_value=release), mock.patch.object(update, "install", side_effect=install), \
                mock.patch.object(server.distribution, "SELF_UPDATING", True), mock.patch.object(server.distribution, "VERSION", "1.0.0"), \
                mock.patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
            self.assertTrue(self.result("check_update")["installable"])
            self.assertIn("9.0.0 is installed", self.result("install_update")["message"])
        self.assertEqual(appimage.read_bytes(), b"new")

    def test_writes_the_page_a_json_resume_theme_made(self):
        root = self.opened()["root"]
        written = self.result("write_html", root=root, html="<p>Ada</p>")
        self.assertEqual(written["path"], str(self.folder.resolve() / "output/resume.html"))
        self.assertEqual((self.folder / "output/resume.html").read_text(encoding="utf-8"), "<p>Ada</p>")
        target = Path(self.home.name) / "elsewhere" / "ada.html"
        self.assertEqual(self.result("write_html", root=root, html="<p>Ada</p>", target=str(target))["path"], str(target))
        self.assertEqual(self.result("export_name", root=root, kind="html"), "your_name_resume.html")

    def test_shows_the_licenses_a_packaged_editor_carries(self):
        self.assertEqual(self.result("licenses"), "")  # a checkout carries nothing
        licenses = Path(self.home.name) / "licenses.txt"
        licenses.write_text("Python 3.14\n", encoding="utf-8")
        with mock.patch.object(server, "LICENSES", licenses):
            self.assertEqual(self.result("licenses"), "Python 3.14\n")

    def test_grammar_is_off_without_its_package_and_in_a_store_build(self):
        with mock.patch.object(server.Grammar, "installed", return_value=False):
            found = self.result("grammar", texts=["She go to the office."])
            self.assertEqual((found["missing"], found["results"]), (True, {}))
            self.assertIn("Install Grammar Checker", found["off"])
            self.assertEqual(self.result("grammar_status")["installed"], False)
        with mock.patch.object(server.distribution, "STORE", True):
            self.assertIn("store", self.ask("install_grammar")["error"])
            self.assertIn("store", server.Grammar().off)

    def test_grammar_problems_are_placed_as_the_window_counts(self):
        """With a stand-in for LanguageTool, which counts in code points
        where the window counts in UTF-16 units."""
        match = mock.Mock(offset=5, error_length=2, message="Use goes.", replacements=list("abcdefgh"), rule_id="RULE")
        checker = self.backend.grammar_checker
        checker.tool = mock.Mock(check=mock.Mock(return_value=[match]))
        found = self.result("grammar", texts=["😀 She go.", " "])
        self.assertEqual(found["results"]["😀 She go."], [{"start": 6, "end": 8, "message": "Use goes.", "replacements": list("abcdef"), "rule": "RULE"}])
        self.assertEqual(found["results"][" "], [])
        self.result("grammar", texts=["😀 She go."])
        checker.tool.check.assert_called_once()  # a text is checked once
        tool = checker.tool
        checker.close()
        tool.close.assert_called_once()

    @unittest.skipUnless(shutil.which("pdflatex") or shutil.which("tectonic"), "needs pdflatex or tectonic")
    def test_builds_and_previews(self):
        opened = self.opened()
        files, root = opened["files"], opened["root"]
        resume = json.loads(files["resume.json"])
        resume["basics"]["name"] = "Ada Example"
        # The preview is of the text in the window; the folder is left as it was.
        previewed = self.result("preview", root=root, resume=json.dumps(resume), order=files["section_order.yaml"], geometry=files["geometry.yaml"])
        self.assertTrue(previewed["ok"], previewed.get("reason"))
        self.assertTrue(base64.b64decode(previewed["pdf"]).startswith(b"%PDF"))
        self.assertEqual(list((self.folder / "output").iterdir()), [])
        self.assertEqual(self.result("preview", root=root, resume="{", order="", geometry="")["reason"], "resume.json isn't valid JSON")
        resume["basics"]["name"] = ""
        self.assertIn("name", self.result("preview", root=root, resume=json.dumps(resume), order=files["section_order.yaml"], geometry=files["geometry.yaml"])["reason"])

        built = self.result("build", root=root, named=True)
        self.assertTrue(built["ok"], built["output"][-2000:])
        self.assertEqual(built["message"], "Built the resume in output/, and your_name_resume.pdf.")
        self.assertEqual(sorted(path.name for path in (self.folder / "output").iterdir()),
                         ["resume-workshop.json", "resume.pdf", "resume.txt", "rxresume.json", "your_name_resume.pdf"])
        self.assertEqual(self.result("export_name", root=root, kind="txt"), "your_name_resume.txt")
        target = Path(self.home.name) / "copy.txt"
        self.assertTrue(self.result("export", root=root, kind="txt", target=str(target))["ok"])
        self.assertIn("YOUR NAME", target.read_text(encoding="utf-8"))

        layout = self.folder / "input/format.tex"
        layout.write_text(layout.read_text(encoding="utf-8").replace("\\begin{document}", "\\begin{document}\\nosuchcommand"), encoding="utf-8")
        failed = self.result("build", root=root)
        self.assertFalse(failed["ok"])
        self.assertIn("Undefined control sequence", failed["output"])


def pdf_text(path):
    """A PDF's text, with pdftotext; None without it."""
    if not shutil.which("pdftotext"):
        return None
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout


def png():
    """A small one-color PNG image, as bytes."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\x1f\x3a\x5f" * 32 for _ in range(32))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


@unittest.skipUnless(server, "needs jsonschema")
class Building(unittest.TestCase):
    """What the editor builds, against what make builds and with each engine."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="resume-workshop-building-")
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": f"{self.home.name}/config", "XDG_DATA_HOME": f"{self.home.name}/data"})
        patch.start()
        self.addCleanup(patch.stop)
        self.backend = server.Backend()
        self.addCleanup(self.backend.preview_builds.scratch.cleanup)

    def folder(self, name, resume=RESUME):
        folder = Path(self.home.name) / name
        server.project.create(folder)
        (folder / "input/resume.json").write_text(json.dumps(resume, indent=2, ensure_ascii=False), encoding="utf-8")
        return folder

    def files(self, folder):
        return {name: (folder / "input" / name).read_text(encoding="utf-8") for name in ("resume.json", "section_order.yaml", "geometry.yaml")}

    def preview(self, folder):
        files = self.files(folder)
        return self.backend.preview(str(folder), files["resume.json"], files["section_order.yaml"], files["geometry.yaml"])

    @unittest.skipUnless(shutil.which("pdflatex") and shutil.which("make"), "needs make and pdflatex")
    def test_builds_what_make_builds(self):
        ours, makes = self.folder("editor"), self.folder("make")
        subprocess.run(["make", "build", "user"], cwd=makes, check=True, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertTrue(self.preview(ours)["ok"])  # built in a scratch copy:
        self.assertEqual(list((ours / "output").iterdir()), [])
        built = self.backend.build(str(ours), named=True)
        self.assertTrue(built["ok"], built["output"][-2000:])
        names = sorted(path.name for path in (makes / "output").iterdir())
        self.assertEqual(sorted(path.name for path in (ours / "output").iterdir()), names)
        self.assertIn("ada_example_resume.pdf", names)
        for name in ("interim/header.tex", "interim/geometry.tex", "interim/resume_content.tex", "output/resume.txt",
                     "output/rxresume.json", "output/resume-workshop.json"):
            self.assertTrue(filecmp.cmp(ours / name, makes / name, shallow=False), name)
        if pdf_text(ours / "output/resume.pdf") is not None:
            self.assertEqual(pdf_text(ours / "output/resume.pdf"), pdf_text(makes / "output/resume.pdf"))
            self.assertIn("ADA EXAMPLE", pdf_text(ours / "output/resume.pdf"))

    @unittest.skipUnless(shutil.which("pdflatex"), "needs pdflatex")
    def test_every_field_builds(self):
        from tests.test_generators import EveryField

        folder = self.folder("all", {**RESUME, **EveryField.RESUME})
        (folder / "input/photo.png").write_bytes(png())
        previewed = self.preview(folder)
        self.assertTrue(previewed["ok"], previewed.get("reason"))
        # The preview's copy of the folder has no photo; pdflatex finds the folder's.
        self.assertIn("photo.png", (self.backend.preview_builds.root / "output/resume.log").read_text(encoding="utf-8", errors="replace"))
        built = self.backend.build(str(folder))
        self.assertTrue(built["ok"], built["output"][-2000:])
        text = pdf_text(folder / "output/resume.pdf")
        for printed in ("1 Main St, Apt 2, Springfield, IL 62701, US", "Mastodon: example.social/@ada", "Makers of anvils & rockets_2",
                        "Prize, The Academy (Jun 2024)", "Author, Maintainer, Tool Foundation, application", "Version v1.2.0") if text else ():
            self.assertIn(printed, " ".join(text.split()))
        # A layout from before the photo, without graphicx: it builds, leaving the photo out.
        layout = folder / "input/format.tex"
        layout.write_text(layout.read_text(encoding="utf-8").replace("\\usepackage{graphicx}", "%"), encoding="utf-8")
        self.assertTrue(self.backend.build(str(folder))["ok"])

    @unittest.skipUnless(shutil.which("tectonic"), "needs tectonic")
    def test_builds_with_tectonic(self):
        from tests.test_generators import EveryField

        resume = {**RESUME, **EveryField.RESUME}
        resume["basics"] = {**resume["basics"], "summary": "Certified in the field: files, floors, and fleets."}
        folder = self.folder("tectonic", resume)
        (folder / "input/photo.png").write_bytes(png())
        with mock.patch.dict(os.environ, {server.build.ENGINE_VARIABLE: "tectonic"}):
            self.assertEqual(server.build.engine()[0], "tectonic")
            self.assertIsNone(server.build.missing(folder))
            # The preview's copy of the folder has no photo; Tectonic finds the folder's.
            previewed = self.preview(folder)
            self.assertTrue(previewed["ok"], previewed.get("reason"))
            built = self.backend.build(str(folder), named=True)
            self.assertTrue(built["ok"], built["output"][-2000:])
            self.assertEqual(sorted(path.name for path in (folder / "output").iterdir()),
                             ["ada_example_resume.pdf", "resume-workshop.json", "resume.pdf", "resume.txt", "rxresume.json"])
            text = pdf_text(folder / "output/resume.pdf")
            # As letters, not the ligatures a parser may not know.
            for printed in ("ADA EXAMPLE", "Certified in the field: files, floors, and fleets.", "Makers of anvils & rockets_2") if text else ():
                self.assertIn(printed, " ".join(text.split()))
            # A layout that doesn't build says why.
            layout = folder / "input/format.tex"
            good = layout.read_text(encoding="utf-8")
            layout.write_text(good.replace("\\begin{document}", "\\begin{document}\\nosuchcommand"), encoding="utf-8")
            self.assertIn("Undefined control sequence", server.build.latex_error(self.backend.build(str(folder))["output"]))
            if shutil.which("make"):
                layout.write_text(good, encoding="utf-8")
                (folder / "output/resume.pdf").unlink()
                subprocess.run(["make", "pdf", "LATEX=tectonic"], cwd=folder, check=True, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertTrue((folder / "output/resume.pdf").stat().st_size)

    @unittest.skipUnless(shutil.which("tectonic") and (ROOT / "build/app/tex").is_dir(), "needs tectonic, and the TeX packages `make appimage` collects")
    def test_builds_offline_with_the_packages_it_carries(self):
        folder, cache = self.folder("offline"), Path(self.home.name) / "no-cache"
        # No network, and nothing in the user's own Tectonic cache.
        environment = {server.build.ENGINE_VARIABLE: "tectonic", "https_proxy": "http://127.0.0.1:9", "XDG_CACHE_HOME": str(cache)}
        with mock.patch.dict(os.environ, environment), mock.patch.object(server.build, "PACKAGES", ROOT / "build/app/tex"):
            self.assertTrue(self.preview(folder)["ok"])
            layout = folder / "input/format.tex"
            text = layout.read_text(encoding="utf-8")
            for fonts in ("\\ifPDFTeX", "\\iftrue"):  # the layout, and one from before Tectonic
                layout.write_text(text.replace("\\ifPDFTeX", fonts), encoding="utf-8")
                built = self.backend.build(str(folder))
                self.assertTrue(built["ok"], built["output"][-2000:])
            self.assertFalse(list(cache.rglob("*.fmt")))
            # A layout that loads a package the editor doesn't carry: it says which.
            layout.write_text(text.replace("\\usepackage{titlesec}", "\\usepackage{titlesec}\\usepackage{lipsum}"), encoding="utf-8")
            for store in (False, True):
                with mock.patch.object(server.distribution, "STORE", store):
                    self.assertIn("lipsum.sty' not found", server.build.latex_error(self.backend.build(str(folder))["output"]))

    def test_folder_with_older_build_files(self):
        folder = self.folder("old")
        self.assertEqual(server.project.outdated(folder), [])
        (folder / "scripts/jsonresume.py").write_text("# an older version\n", encoding="utf-8")
        (folder / "makefile").unlink()
        notice = self.backend.notice(folder)
        if not server.build.missing(folder):  # which would be said first
            self.assertEqual(notice["stale"], ["makefile", "scripts"])
            self.assertIn("Update Folder's Build Files", notice["text"])
        self.assertEqual(self.backend.update_build_files(str(folder)), {"updated": ["makefile", "scripts"]})
        self.assertEqual(server.project.outdated(folder), [])
        self.assertIn('"Ada Example"', (folder / "input/resume.json").read_text(encoding="utf-8"))  # the resume is left alone

    @unittest.skipUnless(shutil.which("pdflatex") and shutil.which("kpsewhich"), "needs pdflatex and kpsewhich")
    def test_missing_tex_packages_are_named(self):
        folder = self.folder("tex")
        with mock.patch.dict(os.environ, {server.build.ENGINE_VARIABLE: "pdflatex"}):
            self.assertIsNone(server.build.missing(folder))
            (folder / "input/format.tex").write_text("\\usepackage{xcolor}\n\\usepackage[a]{nosuchpackage}\n", encoding="utf-8")
            self.assertIn("nosuchpackage", server.build.missing(folder))
            self.assertNotIn("xcolor,", server.build.missing(folder))

    def test_remembers_the_theme(self):
        self.assertEqual(self.backend.startup()["theme"], server.themes.DEFAULT)
        self.backend.set_theme("Nord")
        self.assertEqual(self.backend.startup()["theme"], "Nord")
        for theme in server.themes.THEMES.values():
            self.assertEqual(list(theme), server.themes.ROLES)

    def test_changes_the_resume_theme(self):
        listed = self.backend.startup()["layouts"]
        self.assertEqual(listed[0], {"id": "classic", "name": "Classic", "about": "Helvetica, with navy headings over a rule"})
        self.assertEqual(sorted(theme["id"] for theme in listed), sorted(path.stem for path in (ROOT / "themes").glob("*.tex")))
        folder = self.folder("themed")
        self.assertEqual(self.backend.open(str(folder))["layout"], "classic")  # what a new resume starts with
        self.assertEqual(self.backend.set_layout(str(folder), "traditional")["layout"], "traditional")
        self.assertTrue(filecmp.cmp(folder / "input/format.tex", ROOT / "themes/traditional.tex", shallow=False))
        with self.assertRaisesRegex(server.Failure, "no resume theme called nosuch"):
            self.backend.set_layout(str(folder), "nosuch")
        # A layout edited by hand is none of them.
        with open(folder / "input/format.tex", "a", encoding="utf-8") as layout:
            layout.write("% mine\n")
        self.assertIsNone(self.backend.open(str(folder))["layout"])

    def test_every_theme_has_what_the_generated_files_use(self):
        for theme in server.layouts.available():
            layout = (ROOT / "themes" / f"{theme['id']}.tex").read_text(encoding="utf-8")
            for needed in ("\\newcommand{\\role}", "\\newcommand{\\position}", "\\newcommand{\\subrole}", "\\newcommand{\\entry}", "\\newcommand{\\blurb}",
                           "\\newcommand{\\stack}", "\\newlist{duties}", "\\definecolor{accent}", "\\definecolor{muted}", "\\definecolor{body}",
                           "\\usepackage{graphicx}", "{hyperref}", "\\input{interim/geometry.tex}", "\\input{interim/header.tex}",
                           "\\input{interim/resume_content.tex}", "\\ifPDFTeX"):
                self.assertIn(needed, layout, theme["id"])
            # What an applicant tracking system may not read: more than one column, drawings, and ligatures.
            for avoided in ("multicol", "minipage", "tikz", "fontawesome", "\\parbox"):
                self.assertNotIn(avoided, layout, theme["id"])
            self.assertIn("Ligatures=NoCommon", layout, theme["id"])
            self.assertIn("\\pdfgentounicode=1", layout, theme["id"])

    @unittest.skipUnless(shutil.which("pdflatex"), "needs pdflatex")
    def test_every_theme_builds_a_resume_that_reads_in_order(self):
        resume = json.loads(json.dumps(RESUME))
        resume["work"][0]["highlights"].append("An efficient workflow for the office.")
        folder = self.folder("themes", resume)
        root = str(folder)
        with mock.patch.dict(os.environ, {"RESUME_WORKSHOP_TEX": "pdflatex"}):
            for theme in server.layouts.available():
                self.backend.set_layout(root, theme["id"])
                built = self.backend.build(root)
                self.assertTrue(built["ok"], f"{theme['id']}: {built['output'][-2000:]}")
                text = pdf_text(folder / "output/resume.pdf")
                if text is None:
                    continue
                read = " ".join(text.split())
                self.assertIn("An efficient workflow for the office.", read, theme["id"])  # with "ffi" and "fl" as letters
                places = [read.upper().find(heading) for heading in ("ADA EXAMPLE", "PROFESSIONAL SUMMARY", "PROFESSIONAL EXPERIENCE", "EDUCATION", "REFERENCES")]
                self.assertNotIn(-1, places, theme["id"])
                self.assertEqual(places, sorted(places), theme["id"])

    def test_puts_the_appimage_in_the_applications_menu(self):
        appimage = Path(self.home.name) / 'odd "name" 100%.AppImage'
        self.assertEqual(self.backend.launcher(), {"available": False, "installed": False})  # a checkout isn't one
        with mock.patch.dict(os.environ, {"APPIMAGE": str(appimage)}), mock.patch.object(server.launcher, "SELF_UPDATING", True):
            self.assertEqual(self.backend.launcher(), {"available": True, "installed": False})
            self.assertTrue(self.backend.toggle_launcher()["installed"])
            entry = Path(self.home.name) / "data/applications/resume-workshop.desktop"
            self.assertIn('Exec="' + str(appimage).replace('"', '\\"').replace("%", "%%") + '"\n', entry.read_text(encoding="utf-8"))
            self.assertTrue((Path(self.home.name) / "data/icons/hicolor/scalable/apps/resume-workshop.svg").exists())
            self.assertFalse(self.backend.toggle_launcher()["installed"])
            self.assertFalse(entry.exists())


if __name__ == "__main__":
    unittest.main()
