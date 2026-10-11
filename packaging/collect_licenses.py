#!/usr/bin/env python3
"""Writes the licenses of everything the AppImage carries besides the editor
itself into one text file (packaging/build-appimage.sh), which Help >
Third-Party Licenses shows: the bundled Python, each pip package installed
in it, and Qt.

Run with the bundled Python, so that importlib.metadata sees its packages:

    collect_licenses.py <output file>
"""
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = "=" * 78
# PySide6's wheels name their license without including its text.
QT = """PySide6 (Qt for Python), Shiboken6, and the Qt libraries they include are
used under the GNU Lesser General Public License, version 3, printed below
with the GNU General Public License, version 3, which it builds on. They are
separate libraries in this AppImage's opt/python folder, which you may
replace with builds of your own. Their source code:

  https://download.qt.io/official_releases/QtForPython/
  https://download.qt.io/official_releases/qt/

Qt PDF draws with PDFium, under the BSD-style license described at
https://doc.qt.io/qt-6/qtpdf-licensing.html
"""


def section(title, *texts):
    return "\n".join([RULE, title, RULE, "", *(text.strip("\n") + "\n" for text in texts)])


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def package(distribution):
    """A pip package's section: what it says its license is, and the
    license files it came with."""
    meta = distribution.metadata
    declared = meta.get("License-Expression") or meta.get("License") or ", ".join(
        value.rsplit("::", 1)[-1].strip() for value in meta.get_all("Classifier", []) if value.startswith("License ::"))
    # A License field holding the whole text is printed as that text.
    lines = [f"License: {declared.strip()}" if declared and "\n" not in declared.strip() else declared or ""]
    if meta.get("Home-page"):
        lines.append(f"Homepage: {meta['Home-page']}")
    files = [file for file in distribution.files or []
             if file.parent.name in ("licenses", "license_files") or file.parent.suffix == ".dist-info"
             and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS"))]
    texts = [read(file.locate()) for file in sorted(files, key=str) if file.locate().is_file()]
    return section(f"{meta['Name']} {distribution.version}", "\n".join(line for line in lines if line), *texts)


def main():
    output = Path(sys.argv[1])
    parts = [
        "Resume Workshop includes the software below, each under its own license.\n",
        section(f"Python {sysconfig.get_python_version()}", read(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")),
    ]
    distributions = sorted(metadata.distributions(), key=lambda distribution: distribution.metadata["Name"].lower())
    parts += [package(distribution) for distribution in distributions]
    parts.append(section("Qt", QT, read(HERE / "licenses" / "LGPL-3.0.txt"), read(HERE / "licenses" / "GPL-3.0.txt")))
    output.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
