"""Building a resume folder's files from inside the editor.

The same steps as the folder's makefile, with the same results, but without
make, a Python on the machine, or anything else found on the PATH except
pdflatex: the generators are the editor's own copy of scripts/, called here
as functions. (The folder keeps its copy, and its makefile, for building
without the editor.)

    write_tex()        make header geometry resume   interim/*.tex
    run_latex()        the pdflatex run of make pdf  output/resume.pdf
    write_text()       make txt                      output/resume.txt
    write_rxresume()   make rxresume                 output/rxresume.json
    write_schema()     make schema                   output/resume-workshop.json
    named_copy()       the copy make user makes      output/<name>_resume.pdf

Each takes the resume folder. A generator that can't go on -- a missing
field, a file it can't read -- raises BuildError with the reason.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment

import project

SCRIPTS = project.SOURCE / "scripts"
sys.path.insert(0, str(SCRIPTS))

import export_rxresume  # noqa: E402
import generate_geometry  # noqa: E402
import generate_header  # noqa: E402
import generate_resume  # noqa: E402
import generate_schema  # noqa: E402
import generate_text  # noqa: E402
import jsonresume  # noqa: E402

PDF = Path("output/resume.pdf")
TEX = Path("input/format.tex")
SCHEMA = project.SOURCE / "etc" / "resume-schema.json"
# What pdflatex leaves beside the PDF, which `make build` removes.
LEFTOVERS = [".aux", ".fdb_latexmk", ".fls", ".log", ".out", ".synctex.gz"]
# Where TeX is installed on a Mac. An app started from the Finder isn't
# given the PATH a terminal has, so these are looked in as well.
TEX_FOLDERS = ["/Library/TeX/texbin", "/opt/homebrew/bin", "/usr/local/bin"] if sys.platform == "darwin" else []


class BuildError(Exception):
    pass


def _generated(step, *arguments):
    """step(*arguments), with the ways a generator gives up as BuildError."""
    try:
        return step(*arguments)
    except SystemExit as error:  # how the generators report bad input
        raise BuildError(str(error)) from None
    except OSError as error:
        raise BuildError(str(error)) from None
    except KeyError as error:
        raise BuildError(f"{jsonresume.SRC} has no {error.args[0]}") from None
    except (ValueError, TypeError, AttributeError) as error:
        raise BuildError(f"{jsonresume.SRC}: {error}") from None


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resume(root):
    """The folder's resume and section order, checked as `make resume` checks them."""
    data = jsonresume.load(root / jsonresume.SRC)
    order = generate_resume.parse_section_order(root / generate_resume.ORDER_SRC)
    generate_resume.validate(data, order)
    return data, order


def write_tex(root):
    def step():
        data, order = _resume(root)
        header = generate_header.render(*generate_header.header_fields(data["basics"]))
        geometry = generate_geometry.render(generate_geometry.parse_geometry(root / generate_geometry.SRC))
        _write(root / generate_header.DEST, header)
        _write(root / generate_geometry.DEST, geometry)
        _write(root / generate_resume.DEST, generate_resume.render(data, order))

    _generated(step)


def write_text(root):
    _generated(lambda: _write(root / generate_text.DEST, generate_text.render(*_resume(root))))


def write_rxresume(root):
    def step():
        document = export_rxresume.export(*_resume(root), root)
        _write(root / export_rxresume.DEST, json.dumps(document, indent=2, ensure_ascii=False) + "\n")

    _generated(step)


def write_schema(root):
    def step():
        schema = generate_schema.build(json.loads(SCHEMA.read_text(encoding="utf-8")))
        _write(root / generate_schema.DEST, json.dumps(schema, indent=2, ensure_ascii=False) + "\n")

    _generated(step)


def clean(root):
    """Removes what pdflatex left beside the PDF."""
    for suffix in LEFTOVERS:
        (root / PDF).with_suffix(suffix).unlink(missing_ok=True)


def slug(name):
    """A name as `make user` puts it in a file name: "Todd Takala" -> todd_takala."""
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


def named_copy(root):
    """Copies the built PDF to output/<name>_resume.pdf, named from the
    resume's basics.name; returns the copy's path."""
    def step():
        name = slug(jsonresume.load(root / jsonresume.SRC)["basics"]["name"])
        target = (root / PDF).with_name(f"{name}_resume.pdf")
        shutil.copyfile(root / PDF, target)
        return target

    return _generated(step)


def run_latex(parent, root, finished, passes=2):
    """Starts pdflatex on the folder's input/format.tex, as `make pdf` does
    once write_tex() has run, without blocking the window. Calls
    finished(succeeded, output) when it ends, however it ends, and returns
    the QProcess. Raises BuildError if there is no pdflatex.

    Like `make pdf` it runs pdflatex twice, the second time for the PDF's
    bookmarks; `passes` is 1 where what the last build left will do."""
    path = os.pathsep.join([os.environ.get("PATH", os.defpath), *TEX_FOLDERS])
    program = shutil.which("pdflatex", path=path)
    if program is None:
        raise BuildError("pdflatex isn't installed, or isn't on the PATH. Building the PDF needs a TeX distribution such as TeX Live.")
    (root / PDF).parent.mkdir(parents=True, exist_ok=True)
    process = QProcess(parent)
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PATH", path)  # pdflatex runs helpers of its own
    process.setProcessEnvironment(environment)
    process.setWorkingDirectory(str(root))
    process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    reported = []  # a process that can't start reports that, and then that it finished

    def done(succeeded, output):
        if not reported:
            reported.append(True)
            process.deleteLater()
            finished(succeeded, output)

    arguments = [f"-jobname={PDF.with_suffix('').as_posix()}", "-interaction=nonstopmode", TEX.as_posix()]
    remaining = [passes - 1]

    def on_finished(code, status):
        output = bytes(process.readAll()).decode("utf-8", "replace")
        succeeded = status == QProcess.ExitStatus.NormalExit and code == 0
        if succeeded and remaining[0] and not reported:
            remaining[0] -= 1
            process.start(program, arguments)
        else:
            done(succeeded, output)

    def on_error(error):
        if error == QProcess.ProcessError.FailedToStart:
            done(False, f"Could not run {program}: {process.errorString()}")

    process.finished.connect(on_finished)
    process.errorOccurred.connect(on_error)
    process.start(program, arguments)
    return process


def latex_error(output):
    """The first error in pdflatex's output, in a line."""
    errors = [line.strip().lstrip("! ") for line in output.splitlines() if line.startswith("!")]
    reason = errors[0] if errors else "pdflatex failed"
    return reason if len(reason) <= 160 else reason[:157] + "…"
