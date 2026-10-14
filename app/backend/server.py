#!/usr/bin/env python3
"""The backend of the Tauri editor (app/): everything the window does that
isn't drawing it. The window sends a request per line on standard input,

    {"id": 1, "method": "open", "params": {"folder": "/home/me/resume"}}

and reads the answer, {"id": 1, "result": ...} or {"id": 1, "error": "..."},
from standard output. Requests are answered as they finish, not in order:
a build doesn't hold up a save.

The logic is in the modules beside this one, and the generators in
scripts/, which they import, so the editor and `make build` follow the same
rules. Nothing beyond the
standard library and jsonschema.
"""
import atexit
import base64
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402
import distribution  # noqa: E402
import launcher  # noqa: E402
import links  # noqa: E402
import project  # noqa: E402
import themes  # noqa: E402
import update  # noqa: E402
from document import LABELS, ORDER, RESUME, SECTION_LISTS, SECTIONS, Document, competency_duplicates, parse_order  # noqa: E402

import check_ats  # noqa: E402  (scripts/, which build puts on the path)
import generate_text  # noqa: E402

GEOMETRY = "geometry.yaml"
WORDS = "etc/dictionary.txt"  # in a resume folder
EXPORTS = {
    "pdf": ("output/resume.pdf", None),
    "txt": ("output/resume.txt", build.write_text),
    "json": (f"input/{RESUME}", None),
    "rxresume": ("output/rxresume.json", build.write_rxresume),
}


# Where `pip install --target` puts the grammar checker, an optional extra
# under a license of its own.
PACKAGES = project.data_folder() / "packages"
GRAMMAR_REQUIREMENTS = SOURCE / "requirements-grammar.txt"
MAX_SUGGESTIONS = 6
# Written into a packaged editor (packaging/collect_licenses.py).
LICENSES = SOURCE / "THIRD-PARTY-LICENSES.txt"


class Failure(Exception):
    """Something to tell the user, not a fault in the backend."""


def short(folder):
    """A folder's path, with the home folder as ~."""
    home = str(Path.home())
    return "~" + str(folder)[len(home):] if str(folder).startswith(home + os.sep) else str(folder)


def encoded(path):
    """A file's bytes for the window, or None if there is no such file."""
    try:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return None


def schema_errors(content):
    """resume.json text -> its JSON Resume schema violations."""
    try:
        from validate_resume import schema_errors as check
    except SystemExit as error:  # jsonschema isn't installed
        raise Failure(str(error)) from None
    return check(json.loads(content))


class Preview:
    """The live preview's builds. Unsaved text can't be built in the resume
    folder itself without saving it, so they happen in a scratch copy: a
    temporary folder with the window's current resume.json,
    section_order.yaml and geometry.yaml, and a link to the folder's
    format.tex; the TeX engine finds anything else the resume uses, such as
    a photo, in the folder. input/ and output/ are never touched."""

    def __init__(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="resume-workshop-preview-")
        self.root = Path(self.scratch.name)
        for folder in ("input", "interim", "output"):
            (self.root / folder).mkdir()
        self.lock = threading.Lock()  # one build at a time

    def build(self, folder, resume, order, geometry):
        """The PDF of the resume as it is in the window, saved or not."""
        folder = Path(folder)
        try:
            json.loads(resume)
        except ValueError:
            return {"ok": False, "reason": "resume.json isn't valid JSON"}
        with self.lock:
            link = self.root / build.TEX
            if not link.is_symlink() or link.resolve() != (folder / build.TEX).resolve():
                link.unlink(missing_ok=True)
                try:
                    link.symlink_to(folder / build.TEX)
                except OSError:  # Windows, without the right to make links
                    shutil.copyfile(folder / build.TEX, link)
            (self.root / "input" / RESUME).write_text(resume, encoding="utf-8")
            (self.root / "input" / ORDER).write_text(order, encoding="utf-8")
            (self.root / "input" / GEOMETRY).write_text(geometry, encoding="utf-8")
            try:
                build.write_tex(self.root)
                succeeded, output = build.run_blocking(self.root, passes=1, files=folder)
            except build.BuildError as error:
                return {"ok": False, "reason": self._reason(str(error))}
            if not succeeded:
                return {"ok": False, "reason": build.latex_error(output)}
            return {"ok": True, "pdf": encoded(self.root / build.PDF)}

    def _reason(self, message):
        """A generator's complaint, without the scratch folder's path."""
        message = " ".join(message.replace(f"{self.root}/", "").split())
        return message if len(message) <= 160 else message[:157] + "…"


def utf16(text, index):
    """A Python string index -> the same place as the window counts it (in
    UTF-16 units, where Python counts code points)."""
    return index if text.isascii() else len(text[:index].encode("utf-16-le")) // 2


class Grammar:
    """Grammar checking with LanguageTool, run on this machine by
    language-tool-python: started the first time a text is checked, which
    takes several seconds, and stopped as the backend exits."""

    def __init__(self):
        self.tool = None
        self.off = "an app store's build doesn't include it." if distribution.STORE else None  # why it is off, if it is
        self.missing = False  # off because language_tool_python isn't installed
        self.lock = threading.Lock()  # one check at a time, and one start
        self.results = {}  # text -> its problems
        atexit.register(self.close)

    @staticmethod
    def installed():
        """Whether language_tool_python is there to import, bundled or in PACKAGES."""
        if str(PACKAGES) not in sys.path:
            sys.path.append(str(PACKAGES))
        importlib.invalidate_caches()
        try:
            return importlib.util.find_spec("language_tool_python") is not None
        except (ImportError, ValueError):
            return False

    def _start(self):
        try:
            if not self.installed():
                raise ImportError
            import language_tool_python

            # Its server is on this machine: not one to reach through a proxy.
            for name in ("no_proxy", "NO_PROXY"):
                os.environ[name] = ",".join(filter(None, [os.environ.get(name), "localhost", "127.0.0.1"]))
            self.tool = language_tool_python.LanguageTool("en-US")
            self.tool.disabled_rules.add("MORFOLOGIK_RULE_EN_US")  # spelling is the web view's job
        except ImportError:
            self.missing = True
            self.off = "its package, an optional extra, isn't installed" + ("." if distribution.STORE else ". Edit > Install Grammar Checker adds it.")
        except Exception as error:  # no Java, or LanguageTool couldn't be downloaded or started
            self.off = str(error)

    def check(self, texts):
        """{text: its problems} for each of `texts`, or why there are none."""
        found = {}
        with self.lock:
            for text in texts:
                if self.off is None and self.tool is None:
                    self._start()
                if self.off is not None:
                    break
                if text not in self.results:
                    try:
                        self.results[text] = [
                            {"start": utf16(text, match.offset), "end": utf16(text, match.offset + match.error_length), "message": match.message,
                             "replacements": match.replacements[:MAX_SUGGESTIONS], "rule": match.rule_id}
                            for match in self.tool.check(text)] if text.strip() else []
                    except Exception as error:
                        self.off = str(error)
                        break
                found[text] = self.results[text]
        return {"off": self.off, "missing": self.missing, "results": found}

    def retry(self):
        """Starts afresh, once what kept it off has been put right."""
        with self.lock:
            if not distribution.STORE and self.tool is None:
                self.off, self.missing, self.results = None, False, {}

    def close(self):
        # Not for ever: a check may be waiting on LanguageTool, which can
        # take minutes the first time, as it is downloaded.
        waited = self.lock.acquire(timeout=15)
        try:
            tool, self.tool = self.tool, None
            if self.off is None:
                self.off = "the editor is closing."
        finally:
            if waited:
                self.lock.release()
        if tool is not None:
            try:
                tool.close()
            except Exception:
                pass


class Backend:
    def __init__(self):
        self.preview_builds = Preview()
        self.building = threading.Lock()
        self.grammar_checker = Grammar()
        self.installing = threading.Lock()
        self.release = None  # the release Check for Updates found last

    # --- folders -------------------------------------------------------------------

    def startup(self):
        """What the window needs before it shows anything, and the resume
        folder to open first, if there is one to go on."""
        folder, reason = project.startup_folder(), "There is no resume open."
        if folder is not None and project.missing(folder):
            folder, reason = None, f"{short(folder)} isn't a resume folder (it has no {', '.join(project.missing(folder))})."
        return {
            "version": distribution.VERSION, "channel": distribution.CHANNEL, "store": distribution.STORE,
            "themes": themes.THEMES, "theme": themes.saved(),
            "sections": [{"id": section, "label": LABELS.get(section, section), "list": SECTION_LISTS.get(section)} for section in SECTIONS],
            "folder": str(folder) if folder else None, "reason": reason, "recent": self.recent(), "home": str(Path.home()),
            "launcher": self.launcher(),
        }

    def recent(self):
        return [{"folder": str(folder), "short": short(folder)} for folder in project.recent()]

    def open(self, folder):
        folder = Path(folder).expanduser().resolve()
        missing = project.missing(folder)
        if missing:
            raise Failure(f"{short(folder)} isn't a resume folder. It has no {', '.join(missing)}.\n\nFile > New Resume makes one.")
        try:
            files = {name: (folder / "input" / name).read_text(encoding="utf-8") for name in (RESUME, ORDER, GEOMETRY)}
        except OSError as error:
            raise Failure(f"Could not open {short(folder)}: {error}") from None
        project.remember(folder)
        return {"root": str(folder), "short": short(folder), "files": files, "notice": self.notice(folder), "pdf": encoded(folder / build.PDF),
                "words": self.words(folder)}

    def words(self, root):
        """The resume folder's own spelling list (etc/dictionary.txt), which
        the window's spelling check takes as right, and cspell too."""
        try:
            lines = (Path(root) / WORDS).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [line.strip() for line in lines if line.strip() and not line.startswith("#")]

    def add_word(self, root, word):
        """Adds a word to that list."""
        word = word.strip()
        if not word or word in self.words(root):
            return {"added": False}
        path = Path(root) / WORDS
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + word + "\n", encoding="utf-8")
        except OSError as error:
            raise Failure(f"Could not add to {WORDS}: {error}") from None
        return {"added": True}

    def create(self, folder):
        try:
            project.create(Path(folder).expanduser())
        except (OSError, ValueError) as error:
            raise Failure(str(error)) from None
        return self.open(folder)

    def notice(self, root):
        """What stands in the way of working on a folder, most pressing first."""
        root = Path(root)
        missing, stale = build.missing(root), project.outdated(root)
        if missing:
            return {"text": missing, "kind": "error"}
        if stale:
            return {"text": f"This folder's own build files ({', '.join(stale)}) differ from the editor's, so `make build` here may not match "
                            "the editor's Build. File > Update Folder's Build Files brings them up to date.", "kind": "", "stale": stale}
        return {"text": "", "kind": ""}

    def update_build_files(self, root):
        stale = project.outdated(root)
        try:
            project.update_build_files(root)
        except OSError as error:
            raise Failure(f"Could not update the build files: {error}") from None
        return {"updated": stale}

    def set_theme(self, name):
        themes.save(name)
        return True

    # --- the resume ----------------------------------------------------------------

    def problems(self, resume, order):
        """What a save from the block editor would be turned down for, and
        what Core Competencies repeats (a warning only)."""
        try:
            document = Document(resume, order)
        except ValueError as error:
            raise Failure(str(error)) from None
        repeats = competency_duplicates(document.list_for("competencies"))
        return {"problems": document.problems(), "duplicates": repeats}

    def save(self, root, files):
        """Writes the edited files ({name: text}) to input/. Fails rather
        than save a resume.json that isn't JSON or doesn't match the JSON
        Resume schema."""
        if RESUME in files:
            try:
                errors = schema_errors(files[RESUME])
            except ValueError as error:
                raise Failure(f"Cannot save {RESUME}: invalid JSON — {error}") from None
            if errors:
                raise Failure(f"{RESUME} does not match the JSON Resume schema: " + "; ".join(errors))
        try:
            for name, content in files.items():
                if name not in (RESUME, ORDER, GEOMETRY):
                    raise Failure(f"{name} isn't one of the files the editor saves.")
                (Path(root) / "input" / name).write_text(content, encoding="utf-8")
        except OSError as error:
            raise Failure(str(error)) from None
        return {"saved": list(files)}

    def read(self, root):
        """The input files as they are on disk."""
        try:
            return {name: (Path(root) / "input" / name).read_text(encoding="utf-8") for name in (RESUME, ORDER, GEOMETRY)}
        except OSError as error:
            raise Failure(str(error)) from None

    def import_json(self, path):
        """A JSON Resume file's text for the editor, and what in it doesn't
        match the schema."""
        try:
            imported = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(imported, dict):
                raise ValueError("it isn't a JSON object")
            text = json.dumps(imported, indent=2, ensure_ascii=False)
            return {"text": text, "problems": schema_errors(text), "name": Path(path).name}
        except (OSError, ValueError) as error:
            raise Failure(f"Could not import {path}: {error}") from None

    # --- building ------------------------------------------------------------------

    def build(self, root, named=False):
        """Builds everything in output/ from the saved input files, as
        `make build` does, and with `named` the copy `make user` adds."""
        root = Path(root)
        if not self.building.acquire(blocking=False):
            raise Failure("A build is already running.")
        try:
            try:
                build.write_tex(root)
                succeeded, output = build.run_blocking(root)
                if not succeeded:
                    return {"ok": False, "output": output}
                build.clean(root)
                build.write_text(root)
                build.write_rxresume(root)
                build.write_schema(root)
                copy = build.named_copy(root) if named else None
            except build.BuildError as error:
                return {"ok": False, "output": str(error)}
            return {"ok": True, "output": output, "pdf": encoded(root / build.PDF),
                    "message": f"Built the resume in output/{f', and {copy.name}' if copy else ''}."}
        finally:
            self.building.release()

    def preview(self, root, resume, order, geometry):
        return self.preview_builds.build(root, resume, order, geometry)

    def pdf(self, root):
        return {"pdf": encoded(Path(root) / build.PDF), "path": str(Path(root) / build.PDF)}

    def export_name(self, root, kind):
        """A file name from the saved resume's basics.name, as `make user`
        derives one: "Todd Takala" -> todd_takala_resume.pdf."""
        if kind == "rxresume":
            return "rxresume.json"
        try:
            slug = build.slug(json.loads((Path(root) / "input" / RESUME).read_text(encoding="utf-8"))["basics"]["name"])
        except (OSError, ValueError, LookupError, AttributeError, TypeError):
            slug = ""
        return f"{slug}_resume.{kind}" if slug else f"resume.{kind}"

    def export(self, root, kind, target):
        """Writes one of the EXPORTS from the saved input files, and copies
        it to `target`."""
        root = Path(root)
        source, write = EXPORTS[kind]
        try:
            if kind == "pdf":
                built = self.build(root)
                if not built["ok"]:
                    return built
            elif write:
                write(root)
            shutil.copyfile(root / source, target)
        except build.BuildError as error:
            return {"ok": False, "output": str(error)}
        except OSError as error:
            raise Failure(str(error)) from None
        return {"ok": True, "target": str(target)}

    # --- checks --------------------------------------------------------------------

    def ats(self, resume, order, job=""):
        """How an applicant tracking system is likely to read the resume
        (scripts/check_ats.py), and which of a job description's terms it has."""
        text = None
        try:
            data = json.loads(resume)
            _, sections, _, headings = parse_order(order)
            found = check_ats.check(data, sections, headings)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            found = [check_ats.Finding("warn", f"The resume can't be checked until it is fixed: {error}")]
        else:
            try:
                text = generate_text.render(data, sections, headings)
            except (SystemExit, KeyError, TypeError, AttributeError):
                pass
        match = check_ats.keywords(job, text) if job.strip() and text else None
        return {"findings": [{"level": finding.level, "text": finding.text} for finding in found],
                "match": {"found": match.found, "missing": match.missing} if match else None}

    def test_link(self, url):
        """Asks a site for the page at `url`: {"state": "ok", "error" or ""
        (couldn't be told), "message": ...}."""
        address = links.address(url)
        if not address:
            return {"state": "error", "message": f"{url.strip() or 'That'} isn't a web address.", "address": None}
        state, message = links.check(address)
        return {"state": state, "message": message, "address": address}


    def grammar(self, texts):
        """The grammar problems in each of `texts`, with where they are in
        it as the window counts (UTF-16 units)."""
        return self.grammar_checker.check(texts)

    def grammar_status(self):
        return {"installed": Grammar.installed(), "running": self.grammar_checker.tool is not None, "packages": short(PACKAGES)}

    def install_grammar(self):
        """Downloads the grammar checker (requirements-grammar.txt) from
        PyPI into the user's own packages folder, with this Python's pip."""
        if distribution.STORE:
            raise Failure("An app store's build can't add the grammar checker.")
        if not self.installing.acquire(blocking=False):
            raise Failure("The grammar checker is being installed already.")
        try:
            command = [sys.executable, "-s", "-E", "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "--no-input",
                       "--target", str(PACKAGES), "-r", str(GRAMMAR_REQUIREMENTS)]
            try:
                run = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            except OSError as error:
                return {"ok": False, "output": f"Could not run pip: {error}"}
            if run.returncode:
                return {"ok": False, "output": run.stdout + run.stderr}
            updated = self.grammar_checker.tool is not None  # the version running stays until the editor is restarted
            self.grammar_checker.retry()
            return {"ok": True, "updated": updated}
        finally:
            self.installing.release()

    # --- the editor itself ---------------------------------------------------------

    def check_update(self):
        """Asks GitHub for the latest release, and says how it compares
        with this copy of the editor (update.py)."""
        if distribution.STORE:
            raise Failure("An app store's build is updated by the store.")
        try:
            release = update.latest()
        except (OSError, ValueError) as error:
            raise Failure(f"Could not check for updates: {update._plain(error)}") from None
        current = distribution.VERSION
        if release is None:
            return {"state": "none", "message": "No version of Resume Workshop has been released yet."}
        if distribution.VERSION and update.numbers(release.version) <= update.numbers(current):
            return {"state": "latest", "message": f"Resume Workshop {current} is the latest version."}
        self.release = release
        appimage = os.environ.get("APPIMAGE")
        return {"state": "newer", "version": release.version, "current": current, "page": release.page, "notes": release.notes,
                "checkout": distribution.CHANNEL == "source", "installable": bool(distribution.SELF_UPDATING and appimage and release.url)}

    def install_update(self):
        """Downloads the release check_update() found, and puts it in place
        of the AppImage that is running."""
        appimage = os.environ.get("APPIMAGE")
        if not (self.release and self.release.url and distribution.SELF_UPDATING and appimage):
            raise Failure("There is no update to install.")
        try:
            update.install(self.release, appimage)
        except (OSError, ValueError) as error:
            raise Failure(f"Could not update: {update._plain(error)}") from None
        return {"message": f"Resume Workshop {self.release.version} is installed, and starts the next time you open the editor."}

    def launcher(self):
        """Whether this is an AppImage, which can be put in the applications
        menu (launcher.py), and whether it is there."""
        return {"available": launcher.appimage() is not None, "installed": launcher.installed()}

    def toggle_launcher(self):
        """Adds the AppImage to the applications menu, or takes it out."""
        try:
            if launcher.installed():
                launcher.remove()
                said = "Removed Resume Workshop from the applications menu."
            else:
                launcher.install()
                said = f"Added Resume Workshop to the applications menu. It starts {launcher.appimage()}, so add it again if you move that file."
        except OSError as error:
            raise Failure(f"Could not change the applications menu: {error}") from None
        return {"message": said, **self.launcher()}

    def licenses(self):
        """The licenses of what a packaged editor carries besides the
        window's own libraries; empty from a checkout, which carries nothing."""
        try:
            return LICENSES.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


def serve(backend, lines, write):
    """Answers each request in `lines` with write(answer), a JSON string."""
    lock = threading.Lock()
    threads = []

    def answer(request):
        reply = {"id": request.get("id")}
        try:
            method = getattr(backend, str(request.get("method")), None)
            if method is None or str(request.get("method")).startswith("_"):
                raise Failure(f"There is no {request.get('method')} to call.")
            reply["result"] = method(**(request.get("params") or {}))
        except Failure as error:
            reply["error"] = str(error)
        except Exception as error:  # a fault of ours: say so, and stay up
            reply["error"] = f"{type(error).__name__}: {error}"
        with lock:
            write(json.dumps(reply, ensure_ascii=False))

    for line in lines:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        thread = threading.Thread(target=answer, args=(request,), daemon=True)
        threads.append(thread)
        thread.start()
    for thread in threads:  # the input ended: finish what was asked, within reason
        thread.join(timeout=10)


def trust_system_certificates():
    """Points Python's HTTPS (the update check, testing a web address) at
    the system's certificates, where the Python the app carries doesn't know
    where this system keeps them. (Windows and macOS need no telling.)"""
    import ssl

    paths = ssl.get_default_verify_paths()
    if os.environ.get("SSL_CERT_FILE") or (paths.cafile and os.path.exists(paths.cafile)) or sys.platform in ("win32", "darwin"):
        return
    for bundle in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem",
                   "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"):
        if os.path.exists(bundle):
            os.environ["SSL_CERT_FILE"] = bundle
            return


def exit_on_signals():
    """Has `kill`, a closed terminal, or Ctrl+C end the backend as the end
    of its input does, so that what it started (the grammar checker's
    server) is stopped rather than left running."""
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: sys.exit(0))


def main():
    def write(text):
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    exit_on_signals()
    trust_system_certificates()
    serve(Backend(), sys.stdin, write)


if __name__ == "__main__":
    main()
