"""Building a resume folder's files from inside the editor.

The same steps as the folder's makefile, with the same results, but without
make, a Python on the machine, or anything else found on the PATH except
the TeX engine (pdflatex or Tectonic; see engine()): the generators are the
editor's own copy of scripts/, called here as functions. (The folder keeps its copy, and its makefile, for building
without the editor.)

    write_tex()        make header geometry resume   interim/*.tex
    run_blocking()     the TeX run of make pdf       output/resume.pdf
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
import subprocess
import sys
from pathlib import Path

import distribution
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
# Set to "pdflatex" or "tectonic", or the path of either, to say which
# builds the PDF.
ENGINE_VARIABLE = "RESUME_WORKSHOP_TEX"
# Where a packaged editor carries a Tectonic of its own.
BUNDLED = project.SOURCE / "bin"
# ...and the TeX packages its layout loads, as a Tectonic cache folder
# (packaging/tex_packages.py), so that building needs no network.
PACKAGES = project.SOURCE / "tex"
# How TeX says a layout loads something it doesn't have.
NOT_FOUND = re.compile(r"not found|cannot be found")
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


def _headings(root):
    """The headings the folder's section order gives sections of their own."""
    return generate_resume.parse_headings(root / generate_resume.ORDER_SRC)


def write_tex(root):
    def step():
        data, order = _resume(root)
        header = generate_header.render(*generate_header.header_fields(data["basics"]))
        geometry = generate_geometry.render(generate_geometry.parse_geometry(root / generate_geometry.SRC))
        _write(root / generate_header.DEST, header)
        _write(root / generate_geometry.DEST, geometry)
        _write(root / generate_resume.DEST, generate_resume.render(data, order, _headings(root)))

    _generated(step)


def write_text(root):
    _generated(lambda: _write(root / generate_text.DEST, generate_text.render(*_resume(root), _headings(root))))


def write_rxresume(root):
    def step():
        document = export_rxresume.export(*_resume(root), root, _headings(root))
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


def _search_path():
    return os.pathsep.join([os.environ.get("PATH", os.defpath), *TEX_FOLDERS])


def engine():
    """The program that builds the PDF, as (name, path): "pdflatex" or
    "tectonic". None if this machine has neither.

    $RESUME_WORKSHOP_TEX decides, if it is set. Otherwise it is the
    Tectonic a packaged editor carries, then the pdflatex `make pdf` runs,
    and then a Tectonic on the PATH."""
    path = _search_path()
    chosen = os.environ.get(ENGINE_VARIABLE)
    if chosen:
        program = shutil.which(chosen, path=path)
        return ("tectonic" if "tectonic" in Path(chosen).name.lower() else "pdflatex", program) if program else None
    for name, where in (("tectonic", str(BUNDLED)), ("pdflatex", path), ("tectonic", path)):
        program = shutil.which(name, path=where)
        if program:
            return name, program
    return None


NO_ENGINE = "Building the PDF needs pdflatex (from a TeX distribution such as TeX Live) or Tectonic, and neither is installed or on the PATH."


def missing(root):
    """What building the folder's PDF needs that this machine doesn't
    have, as a sentence to show; None if nothing is known to be missing."""
    found = engine()
    if found is None:
        return NO_ENGINE
    if found[0] == "tectonic":
        return None  # which has the packages a layout loads, or fetches them
    path = _search_path()
    kpsewhich = shutil.which("kpsewhich", path=path)
    try:
        # The packages the layout loads outright (not inside \IfFileExists).
        packages = re.findall(r"^\\usepackage(?:\[[^\]]*\])?\{([\w-]+)\}", (root / TEX).read_text(encoding="utf-8"), re.MULTILINE)
        found = subprocess.run([kpsewhich, *(f"{name}.sty" for name in packages)], capture_output=True, text=True, timeout=10,
                               env={**os.environ, "PATH": path}).stdout
    except (OSError, TypeError, subprocess.SubprocessError):
        return None  # no kpsewhich to ask, or no layout to read
    absent = [name for name in packages if f"/{name}.sty" not in found]
    if absent:
        return f"Building the PDF needs the TeX package{'s' if len(absent) > 1 else ''} {', '.join(absent)}: install with tlmgr, or from your system's packages."
    return None


def plan(passes=2, files=None):
    """How to build a folder's PDF: (the engine's name, its program, the
    runs to make of it, the PATH to give them). A run is (arguments, the
    Tectonic cache folder to use or None). pdflatex makes each run in turn;
    Tectonic makes the next only if the one before lacked a package.
    Raises BuildError if there is no engine()."""
    found = engine()
    if found is None:
        raise BuildError(NO_ENGINE)
    name, program = found
    if name == "tectonic":
        # Tectonic looks beside the layout, in input/, where pdflatex looks
        # in the folder; and names the PDF after the layout.
        arguments = ["-Z", "search-path=.", *(["-Z", f"search-path={files}"] if files else []), *(["--reruns", "0"] if passes == 1 else []),
                     "--outdir", PDF.parent.as_posix(), TEX.as_posix()]
        runs = [(arguments, None)]
        if PACKAGES.is_dir():
            # First with the packages the editor carries, and no network.
            # A layout that loads others has them fetched, into the user's
            # own cache, where that is allowed.
            runs = [(["--only-cached", *arguments], PACKAGES)] + ([] if distribution.STORE else runs)
    else:
        runs = [([f"-jobname={PDF.with_suffix('').as_posix()}", "-interaction=nonstopmode", TEX.as_posix()], None)] * passes
    return name, program, runs, _search_path()


def _environment(path, files, tectonic, cache):
    """The environment variables of one run of the engine."""
    environment = {**os.environ, "PATH": path}  # pdflatex runs helpers of its own
    if files and not tectonic:
        # After the folder itself, and before TeX's own (the empty last entry).
        environment["TEXINPUTS"] = os.pathsep.join([".", str(files), os.environ.get("TEXINPUTS", "")])
    environment.pop("TECTONIC_CACHE_DIR", None)
    if cache:
        environment["TECTONIC_CACHE_DIR"] = str(cache)
    return environment


def _again(tectonic, succeeded, output):
    """Whether to go on to the next run: pdflatex's next pass, or Tectonic's
    next place to find packages."""
    return bool(not succeeded and NOT_FOUND.search(output)) if tectonic else succeeded


def _finish(root, tectonic, succeeded, output, earlier):
    """What a build came to, as (succeeded, output), once its last run ends."""
    if tectonic and not succeeded and earlier:
        # What the layout lacks first, then why it couldn't be fetched.
        output = f"{earlier[0]}\n{output}"
    if succeeded and tectonic:
        try:
            os.replace(root / PDF.with_name(TEX.with_suffix(".pdf").name), root / PDF)
        except OSError as error:
            succeeded, output = False, f"{output}\n! {error}"
    return succeeded, output


def run_blocking(root, passes=2, files=None, started=None):
    """Runs the TeX engine on the folder's input/format.tex, as `make pdf`
    does once write_tex() has run, and returns (succeeded, output) when
    that is done. Raises BuildError if there is no engine(). `started` is
    called with each subprocess.Popen as it starts, for a caller that may
    need to stop it.

    Like `make pdf` it runs pdflatex twice, the second time for the PDF's
    bookmarks; `passes` is 1 where what the last build left will do.
    Tectonic reruns itself as often as that takes, or not at all if
    `passes` is 1. It uses the PACKAGES a packaged editor carries, and
    downloads what a layout loads beyond those; an app store's build, which
    may not, fails on such a layout.
    `files` is a second folder to find files in that `root` lacks: the
    resume folder, when `root` is the live preview's partial copy of it."""
    name, program, runs, path = plan(passes, files)
    tectonic = name == "tectonic"
    (root / PDF).parent.mkdir(parents=True, exist_ok=True)
    earlier = []  # the output of the runs before this one
    while True:
        arguments, cache = runs.pop(0)
        try:
            process = subprocess.Popen([program, *arguments], cwd=root, env=_environment(path, files, tectonic, cache), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # on Windows: no console beside the editor
        except OSError as error:
            return False, f"Could not run {program}: {error}"
        if started:
            started(process)
        output = process.communicate()[0].decode("utf-8", "replace")
        succeeded = process.returncode == 0
        if process.returncode >= 0 and runs and _again(tectonic, succeeded, output):
            earlier.append(output)
            continue
        return _finish(root, tectonic, succeeded, output, earlier)


def latex_error(output):
    """The first error in pdflatex's or Tectonic's output, in a line."""
    errors = [line.strip().lstrip("! ") for line in output.splitlines() if line.startswith("!")]
    errors += [line.removeprefix("error:").strip() for line in output.splitlines() if line.startswith("error:")]
    reason = errors[0] if errors else "the TeX run failed"
    return reason if len(reason) <= 160 else reason[:157] + "…"
