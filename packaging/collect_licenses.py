#!/usr/bin/env python3
"""Writes the licenses of everything the AppImage carries besides the editor
itself into one text file (packaging/build_app.py), which Help >
Third-Party Licenses shows: the bundled Python, each pip package installed
in it, the web view, and Tectonic. (The window's own libraries are listed
as it is built: app/vite.config.ts.)

Run with the bundled Python, so that importlib.metadata sees its packages:

    collect_licenses.py <output file> [--crates Cargo.toml] [--tex cache]
"""
import argparse
import json
import subprocess
import sysconfig
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = "=" * 78
WEBKIT = """The window is drawn by WebKitGTK, with GTK 3 and the libraries they use.
They are the build machine's own, copied into this AppImage's usr/lib
folder as separate libraries, which you may replace with builds of your
own. Most are under the GNU Lesser General Public License, version 2.1 or
later (the text of version 3 is printed below, with the GNU General Public
License it builds on); each library's own license is in its source:

  https://webkitgtk.org/
  https://www.gtk.org/

The Rust crates the Tauri shell is built from are listed further on.
"""
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


def crates(manifest):
    """The Rust crates the Tauri shell is built from (app/src-tauri), with
    their licenses: each distinct license text once, under the crates that
    come with it. Asks Cargo, which has their sources."""
    listed = json.loads(subprocess.run(["cargo", "metadata", "--format-version", "1", "--manifest-path", str(manifest)],
                                       capture_output=True, text=True, check=True).stdout)
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
    parts = [section("The Tauri shell's Rust crates", f"{len(names)} crates, from https://crates.io/, each under the license named:\n\n" + "\n".join(names))]
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
        section(f"Python {sysconfig.get_python_version()}", read(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")),
    ]
    distributions = sorted(metadata.distributions(), key=lambda distribution: distribution.metadata["Name"].lower())
    parts += [package(distribution) for distribution in distributions]
    parts.append(section("WebKitGTK, GTK, and the system libraries", WEBKIT, read(HERE / "licenses" / "LGPL-3.0.txt"), read(HERE / "licenses" / "GPL-3.0.txt")))
    parts.append(section("Tectonic", TECTONIC, read(HERE / "licenses" / "Tectonic-MIT.txt")))
    if options.tex:
        parts.append(tex(options.tex))
    if options.crates:
        parts += crates(options.crates)
    Path(options.output).write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
