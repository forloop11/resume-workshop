"""Resume folders: which one the editor opens, and how a new one is made.

A resume folder is self-contained: besides the resume itself (input/), it
has its own copy of the makefile and the generator scripts, so `make build`
works there without the editor. File > New Resume makes one by copying those
files from the editor's own folder -- a checkout of the project, or the copy
the AppImage carries -- and writing a starter resume.

No Qt at import: this runs before the editor knows which folder it has, and
packaging/build-appimage.sh runs it to fill the AppImage's copy.
"""
import filecmp
import json
import os
import shutil
import sys
from pathlib import Path

import distribution

# The folder New Resume copies from.
SOURCE = Path(__file__).resolve().parent.parent
# What makes a folder a resume folder.
REQUIRED = ["makefile", "scripts/generate_resume.py", "input/resume.json", "input/section_order.yaml",
            "input/geometry.yaml", "input/format.tex"]
# What New Resume copies, on top of writing the starter resume: the build
# files, the schemas `make validate` and `make schema` read, and the layout.
TEMPLATE = ["makefile", "requirements.txt", "LICENSE", ".gitignore", ".dockerignore", "docker", "scripts",
            "etc/cspell.json", "etc/resume-schema.json", "etc/resume-schema.LICENSE.md", "etc/rxresume-schema.json",
            "etc/rxresume-schema.LICENSE.md", "input/format.tex", "input/geometry.yaml"]
# The part of TEMPLATE a folder needs for building without the editor,
# which later versions of the editor may improve on. The rest, in input/,
# is the resume's own layout.
BUILD_FILES = [name for name in TEMPLATE if not name.startswith("input/")]
RECENT_LIMIT = 8

# A new resume's section_order.yaml: every section, in a usual order.
SECTION_ORDER = """\
# Resume sections, in the order they appear. Omit one to leave it out.
# A `- pagebreak` line starts the next section on a new page.
- summary
- experience
- early_career
- volunteer
- projects
- education
- certifications
- publications
- recognition
- competencies
- languages
- interests
- references
"""
STARTER = {
    "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.2.1/schema.json",
    "basics": {
        "name": "Your Name",
        "label": "Your Title",
        "email": "you@example.com",
        "phone": "+1 (555) 555-0100",
        "url": "https://example.com",
        "summary": "Two or three sentences on who you are and what you do best.",
        "location": {"city": "City", "region": "ST"},
        "profiles": [],
    },
    "work": [
        {
            "name": "Employer",
            "location": "City, ST",
            "position": "Position",
            "startDate": "2024-01",
            "highlights": ["Something you did here, and what came of it."],
        }
    ],
    "education": [{"institution": "Institution", "studyType": "Degree", "area": "Field of study"}],
    "skills": [{"name": "Competency", "keywords": ["first skill", "second skill"]}],
}


def missing(folder):
    """The REQUIRED files `folder` lacks; none means it is a resume folder."""
    return [name for name in REQUIRED if not (Path(folder) / name).is_file()]


def copy_template(destination, names=TEMPLATE):
    """Copies the TEMPLATE files from the editor's folder into `destination`."""
    for name in names:
        source, target = SOURCE / name, Path(destination) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        else:
            shutil.copyfile(source, target)


def _files(name):
    """The files of one TEMPLATE entry in the editor's folder, as paths
    relative to it."""
    source = SOURCE / name
    if not source.is_dir():
        return [Path(name)]
    return [path.relative_to(SOURCE) for path in sorted(source.rglob("*")) if path.is_file() and "__pycache__" not in path.parts]


def outdated(folder):
    """The BUILD_FILES entries `folder` has differently from the editor's
    own copy, or not at all: its `make build` and the editor's Build may
    then differ. None for the folder the editor itself is in."""
    folder = Path(folder)
    if folder.resolve() == SOURCE:
        return []
    def same(path):
        try:
            return filecmp.cmp(SOURCE / path, folder / path, shallow=False)
        except OSError:
            return False

    return [name for name in BUILD_FILES if not all(same(path) for path in _files(name))]


def update_build_files(folder):
    """Brings `folder`'s BUILD_FILES up to date with the editor's copy;
    OSError if they can't be written."""
    copy_template(folder, BUILD_FILES)


def create(folder):
    """Makes `folder` a new resume folder with a starter resume. Raises
    ValueError rather than write into a folder that already has files, and
    OSError if it can't be written."""
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"{folder} isn't empty. Choose a new or empty folder.")
    copy_template(folder)
    (folder / "input" / "resume.json").write_text(json.dumps(STARTER, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "input" / "section_order.yaml").write_text(SECTION_ORDER, encoding="utf-8")
    (folder / "etc" / "dictionary.txt").write_text("", encoding="utf-8")  # this resume's own spelling list
    for name in ("interim", "output"):
        (folder / name).mkdir(exist_ok=True)


def _standard(location):
    # Qt knows where each system keeps these, including an app store
    # build's own container.
    from PySide6.QtCore import QStandardPaths

    return Path(QStandardPaths.writableLocation(location)) / "resume-workshop"


def config_folder():
    """Where the editor keeps its own settings: ~/.config/resume-workshop
    on Linux, ~/Library/Preferences/resume-workshop on a Mac."""
    from PySide6.QtCore import QStandardPaths

    return _standard(QStandardPaths.StandardLocation.GenericConfigLocation)


def data_folder():
    """Where the editor looks for what the user adds to it:
    ~/.local/share/resume-workshop on Linux,
    ~/Library/Application Support/resume-workshop on a Mac."""
    from PySide6.QtCore import QStandardPaths

    return _standard(QStandardPaths.StandardLocation.GenericDataLocation)


def _recent_file():
    return config_folder() / "recent-folders"


def recent():
    """The folders opened from the File menu, latest first, that still exist."""
    try:
        lines = _recent_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [Path(line) for line in lines if line and not missing(line)]


def remember(folder):
    """Puts `folder` at the head of recent()."""
    folders = [Path(folder)] + [other for other in recent() if other != Path(folder)]
    try:
        _recent_file().parent.mkdir(parents=True, exist_ok=True)
        _recent_file().write_text("".join(f"{path}\n" for path in folders[:RECENT_LIMIT]), encoding="utf-8")
    except OSError:
        pass  # not worth failing over


def startup_folder():
    """The resume folder to open at startup, or None if there's none to go
    on (the editor then asks). In order: the one asked for
    ($RESUME_WORKSHOP_ROOT; the AppImage sets it from its argument), the
    checkout the editor is running from, the one last opened from the File
    menu, and the installed launcher's default ($RESUME_WORKSHOP_DEFAULT)."""
    asked = os.environ.get("RESUME_WORKSHOP_ROOT")
    if asked:
        return Path(asked).expanduser().resolve()
    candidates = recent()[:1]
    if not distribution.PACKAGED:  # packaged, SOURCE is the editor's read-only template
        candidates.insert(0, SOURCE)
    if os.environ.get("RESUME_WORKSHOP_DEFAULT"):
        candidates.append(Path(os.environ["RESUME_WORKSHOP_DEFAULT"]).expanduser())
    return next((folder.resolve() for folder in candidates if not missing(folder)), None)


if __name__ == "__main__":
    # project.py --template DIR: used by packaging/build-appimage.sh.
    if len(sys.argv) != 3 or sys.argv[1] != "--template":
        sys.exit("usage: project.py --template DIR")
    copy_template(sys.argv[2])
