#!/usr/bin/env python3
"""Writes the licenses of everything a packaged editor carries besides the
editor itself into one text file (packaging/build_app.py), which Help >
Third-Party Licenses shows: the bundled Python, each pip package installed
in it, the schemas, the color themes, the web view, Tectonic with its TeX
files, and the Rust crates of the shell, for the system this runs on. (The
window's own libraries are listed as it is built: app/vite.config.ts.)

Run with the bundled Python, so that importlib.metadata sees its packages:

    collect_licenses.py <output file> [--crates Cargo.toml] [--tex cache]
"""
import argparse
import json
import re
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = "=" * 78
ROOT = HERE.parent
# What the Python carried is built with (python-build-standalone), whose
# download has Python's license alone.
PYTHON = """This Python is one built by python-build-standalone, with the libraries
its modules use compiled into it, each under its own license: among them
OpenSSL (Apache License 2.0), SQLite (public domain), zlib, bzip2, XZ Utils,
Zstandard, libffi, Expat, and mpdecimal, and, except on Windows, ncurses,
libedit, and libuuid. The project lists each one's license and source:

  https://github.com/astral-sh/python-build-standalone
  https://gregoryszorc.com/docs/python-build-standalone/main/running.html#licensing

Python's own license follows.
"""
# The schemas a resume is checked against (etc/), as (title, what it is, its license).
SCHEMAS = [
    ("JSON Resume schema", "etc/resume-schema.json, which a resume is checked against, is resume-schema 1.2.1:\n\n"
     "  https://github.com/jsonresume/resume-schema", "resume-schema.LICENSE.md"),
    ("Reactive Resume schema", "etc/rxresume-schema.json, which the Reactive Resume export is checked against, is the schema at\n\n"
     "  https://rxresu.me/schema.json\n\nResume Workshop isn't affiliated with Reactive Resume.", "rxresume-schema.LICENSE.md"),
]
# The palettes app/backend/themes.py takes its colors from.
THEMES = """Five of the editor's color themes (Theme > Color Theme) are built on the
colors of published palettes, each used under the MIT license:

  Dracula, by Zeno Rocha and the Dracula Theme contributors
    https://draculatheme.com/
  Nord, by Sven Greb
    https://www.nordtheme.com/
  Gruvbox (Gruvbox Dark), by Pavel Pertsev
    https://github.com/morhetz/gruvbox
  Solarized (Solarized Dark and Solarized Light), by Ethan Schoonover
    https://ethanschoonover.com/solarized/
"""
# The web view, for each system (sys.platform): its section's title and
# text, and the licenses printed below it.
WEB_VIEWS = {
    "linux": ("WebKitGTK, GTK, and the system libraries", """The window is drawn by WebKitGTK, with GTK 3 and the libraries they use.
In the AppImage they are the build machine's own, copied into its usr/lib
folder as separate libraries, which you may replace with builds of your
own; a .deb or .rpm package uses the system's instead. Most are under the
GNU Lesser General Public License, version 2.1 or later (the text of
version 3 is printed below, with the GNU General Public License it builds
on); each library's own license is in its source:

  https://webkitgtk.org/
  https://www.gtk.org/

The Rust crates the Tauri shell is built from are listed further on.
""", ("LGPL-3.0.txt", "GPL-3.0.txt")),
    "darwin": ("The web view", """The window is drawn by WKWebView, the web view that is part of macOS.
Resume Workshop carries no copy of it.

The Rust crates the Tauri shell is built from are listed further on.
""", ()),
    "win32": ("The web view", """The window is drawn by Microsoft Edge WebView2, which is part of Windows
11, and which the installer downloads from Microsoft where it is missing.
It is Microsoft's, under Microsoft's own terms, and Resume Workshop
carries no copy of it.

The Rust crates the Tauri shell is built from are listed further on.
""", ()),
}
# Tectonic's download is the program alone.
TECTONIC = """Tectonic, the TeX engine in the bin folder beside the backend,
that builds the PDFs, is used under the MIT license printed below. It is
built from XeTeX and xdvipdfmx, and includes libraries of its own, each
under its license; its source code, with theirs, is at

  https://github.com/tectonic-typesetting/tectonic

The TeX packages and fonts in its tex folder, which it builds a
resume's layout with, are files of TeX Live as Tectonic distributes them,
each under its own license: for most the LaTeX Project Public License, and
for the TeX Gyre fonts the GUST Font License. The TeX Catalogue lists each
package's license and source:

  https://ctan.org/
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


def python_license():
    """Python's own license, from where this Python keeps it: with its
    library, or on Windows at its top."""
    for folder in (sysconfig.get_path("stdlib"), sys.base_prefix):
        for name in ("LICENSE.txt", "LICENSE"):
            if (Path(folder) / name).is_file():
                return read(Path(folder) / name)
    return "Python is used under the Python Software Foundation License: https://docs.python.org/3/license.html"


def schema(title, what, license_file):
    return section(title, what, read(ROOT / "etc" / license_file).replace("&copy;", "(c)"))


def crates(manifest):
    """The Rust crates the Tauri shell is built from (app/src-tauri), with
    their licenses: each distinct license text once, under the crates that
    come with it. Asks Cargo, which has their sources, for the crates built
    into the shell on this system: not another system's."""
    compiler = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    host = re.search(r"^host: (\S+)$", compiler, re.MULTILINE).group(1)
    listed = json.loads(subprocess.run(["cargo", "metadata", "--format-version", "1", "--filter-platform", host, "--manifest-path", str(manifest)],
                                       capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    packages = {package["id"]: package for package in listed["packages"]}
    nodes = {node["id"]: node for node in listed["resolve"]["nodes"]}
    # What the program is made of: not what only builds or tests it.
    built_from, waiting = set(), [listed["resolve"]["root"]]
    while waiting:
        crate = waiting.pop()
        if crate not in built_from:
            built_from.add(crate)
            waiting += [dependency["pkg"] for dependency in nodes[crate]["deps"] if any(kind["kind"] is None for kind in dependency["dep_kinds"])]
    built_from.discard(listed["resolve"]["root"])
    names, texts = [], {}
    for package in sorted((packages[crate] for crate in built_from), key=lambda package: (package["name"].lower(), package["version"])):
        name = f"{package['name']} {package['version']}"
        names.append(f"{name}: {package.get('license') or 'see its source'}")
        for file in sorted(Path(package["manifest_path"]).parent.iterdir()):
            if file.is_file() and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE")):
                texts.setdefault(read(file).strip(), []).append(name)
    parts = [section("The Tauri shell's Rust crates", f"{len(names)} crates, from https://crates.io/, each under the license named, and Rust's standard library "
                     "(https://www.rust-lang.org/), under the MIT license or the Apache License 2.0:\n\n" + "\n".join(names))]
    parts += [section("License of " + ", ".join(sorted(set(users))), text) for text, users in sorted(texts.items(), key=lambda item: item[1])]
    return parts


def tex(cache):
    """The TeX files the editor carries (packaging/tex_packages.py), by name."""
    files = sorted({file.name for file in Path(cache).glob("bundles/data/*/*") if file.is_file()}, key=str.lower)
    return section("TeX packages and fonts", f"The {len(files)} files of TeX Live that the editor carries, to build a resume's layout with:\n\n" + "\n".join(files))


def main():
    arguments = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    arguments.add_argument("output")
    arguments.add_argument("--crates", help="the Tauri shell's Cargo.toml, to list its crates")
    arguments.add_argument("--tex", help="the Tectonic cache folder carried, to list its files")
    options = arguments.parse_args()
    parts = [
        "Resume Workshop includes the software below, each under its own license.\n",
        section(f"Python {sysconfig.get_python_version()}", PYTHON, python_license()),
    ]
    distributions = sorted(metadata.distributions(), key=lambda distribution: distribution.metadata["Name"].lower())
    parts += [package(distribution) for distribution in distributions]
    parts += [schema(*described) for described in SCHEMAS]
    parts.append(section("Color themes", THEMES))
    title, text, licenses = WEB_VIEWS[sys.platform]
    parts.append(section(title, text, *(read(HERE / "licenses" / name) for name in licenses)))
    parts.append(section("Tectonic", TECTONIC, read(HERE / "licenses" / "Tectonic-MIT.txt")))
    if options.tex:
        parts.append(tex(options.tex))
    if options.crates:
        parts += crates(options.crates)
    Path(options.output).write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
