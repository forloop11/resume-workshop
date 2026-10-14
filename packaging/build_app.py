#!/usr/bin/env python3
"""Builds the editor (app/) as something to install, for the system this
runs on (`make appimage`):

    Linux     dist/Resume_Workshop-x86_64.AppImage
    macOS     dist/Resume_Workshop-<arch>.dmg
    Windows   dist/Resume_Workshop-x86_64-setup.exe

with what its backend needs to run without anything installed: a Python of
its own with jsonschema, the backend and the generators, the template File
> New Resume copies, Tectonic, and the TeX packages the layout loads, so
building a resume needs no network. Tauri's bundler packs it; on Linux it
adds the web view (WebKitGTK) and GTK from this machine to the AppImage.

A resume lives in its own folder, outside the app. The grammar checker
(requirements-grammar.txt) is GPL-licensed, so it is left out; Edit >
Install Grammar Checker adds it for one user.

Needs Node, Rust with Cargo, the system packages Tauri lists
(app/README.md), and an internet connection: it downloads a relocatable
Python (github.com/astral-sh/python-build-standalone) and Tectonic, each
pinned to a version and checked against its SHA-256 sum, then the TeX
packages, and what Tauri bundles with.

    build_app.py [--bundles appimage,deb,rpm]

Standard library only, for whichever Python is at hand.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "app"
RESOURCES = BUILD / "resources"
DIST = ROOT / "dist"

PYTHON_RELEASE = "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.14.8+20261009-"
TECTONIC_RELEASE = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-"
# For each system: its Python and its Tectonic, as (file name, SHA-256 sum);
# what Tauri is to bundle; and what the result is called in dist/. The
# Linux Tectonic is the statically linked build, which runs whatever C
# library the machine has.
TARGETS = {
    ("Linux", "x86_64"): {
        "python": ("x86_64-unknown-linux-gnu-install_only_stripped.tar.gz", "ddc902fd26460f728758c67d80417c1031edf97589f1f162c4ba3aa158a35998"),
        "tectonic": ("x86_64-unknown-linux-musl.tar.gz", "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7"),
        "bundles": "appimage", "name": "Resume_Workshop-x86_64", "channel": "appimage",
    },
    ("Darwin", "arm64"): {
        "python": ("aarch64-apple-darwin-install_only_stripped.tar.gz", "936217c0e6893f51af939474bee18ecf5e6fe47b986d2c163f19b57c682e4a83"),
        "tectonic": ("aarch64-apple-darwin.tar.gz", "a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667"),
        "bundles": "app,dmg", "name": "Resume_Workshop-arm64", "channel": "package",
    },
    ("Darwin", "x86_64"): {
        "python": ("x86_64-apple-darwin-install_only_stripped.tar.gz", "0fe0c68a7f90458abd13b50a3d8f5f0cb5b2f0a1f33b6ef1445751cf2dc8b36e"),
        "tectonic": ("x86_64-apple-darwin.tar.gz", "7c90ef5b6ddb1eb1937e4337add5237b79338e4b9676459fa91187d24d6cdf80"),
        "bundles": "app,dmg", "name": "Resume_Workshop-x86_64", "channel": "package",
    },
    ("Windows", "AMD64"): {
        "python": ("x86_64-pc-windows-msvc-install_only_stripped.tar.gz", "5b6fa7ddeabe23ae83d7b54e5043eb4fa1ccb10a73fa4c6b0f541dea8160d505"),
        "tectonic": ("x86_64-pc-windows-msvc.zip", "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f"),
        "bundles": "nsis", "name": "Resume_Workshop-x86_64", "channel": "package",
    },
}
# What each kind of bundle is, in Tauri's bundle folder, and after the name in dist/.
BUNDLED = {"appimage": ("*.AppImage", ".AppImage"), "deb": ("*.deb", ".deb"), "rpm": ("*.rpm", ".rpm"), "dmg": ("*.dmg", ".dmg"),
           "nsis": ("*-setup.exe", "-setup.exe"), "msi": ("*.msi", ".msi")}
WINDOWS = platform.system() == "Windows"


def say(text):
    print(text, flush=True)


def fetch(url, sha256):
    """The file at `url`, downloaded unless it is here already, and checked."""
    downloads = BUILD / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    path = downloads / url.rsplit("/", 1)[-1].replace("%40", "@")
    if not path.exists():
        say(f"Downloading {path.name}...")
        with urllib.request.urlopen(url, timeout=120) as response, open(path, "wb") as file:
            shutil.copyfileobj(response, file)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        sys.exit(f"{path} isn't the file expected. Delete it and run this again to download it afresh.")
    return path


def unpack(archive, folder):
    folder.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as file:
            file.extractall(folder)
    else:
        with tarfile.open(archive) as file:
            file.extractall(folder, filter="tar")


def run(command, **options):
    """Runs a command, showing what it printed only if it fails."""
    done = subprocess.run([str(part) for part in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **options)
    if done.returncode:
        sys.exit(f"{' '.join(str(part) for part in command[:4])}... failed:\n{done.stdout[-6000:]}")
    return done.stdout


def version():
    """The version the editor says it is and compares with the latest
    release (app/backend/update.py): $VERSION if set, as the release
    workflow does from the tag, or else what git calls this commit (the last
    tag, plus how far past it). A leading v is dropped."""
    found = os.environ.get("VERSION")
    if not found:
        described = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"], capture_output=True, text=True)
        found = described.stdout.strip() if described.returncode == 0 else "unknown"
    return found.removeprefix("v")


def stage(target, named):
    """Fills RESOURCES with what the app carries besides its own program."""
    shutil.rmtree(RESOURCES, ignore_errors=True)
    say("Unpacking Python...")
    unpack(fetch(PYTHON_RELEASE + target["python"][0], target["python"][1]), RESOURCES)  # as python/
    python = RESOURCES / "python" / ("python.exe" if WINDOWS else "bin/python3")
    # Without the parts of it a program with no window of Python's own never loads: Tk, IDLE, and Python's tests of itself.
    for unused in ("test", "idlelib", "tkinter", "turtledemo", "tcl", "tcl[0-9]*", "tk[0-9]*", "itcl[0-9]*", "thread[0-9]*"):
        for folder in list((RESOURCES / "python").rglob(unused)):
            if folder.is_dir():
                shutil.rmtree(folder)
    # ...and without _dbm, which is built with Berkeley DB: that is under the GNU Affero GPL, and nothing here opens such a file.
    for unused in ("libtcl*", "libtk*", "tcl*.dll", "tk*.dll", "_tkinter*", "_dbm.*"):
        for file in list((RESOURCES / "python").rglob(unused)):
            if file.is_file() or file.is_symlink():
                file.unlink()
    aside = ["-s", "-E"]  # only the packages carried with it, whatever the user's hold

    say("Installing jsonschema...")
    run([python, *aside, "-m", "pip", "install", "--quiet", "--no-cache-dir", "--no-warn-script-location", "--disable-pip-version-check", "jsonschema>=4.0"])
    # pip itself is kept: Install Grammar Checker runs it.

    say("Adding the backend...")
    backend = RESOURCES / "app" / "backend"
    backend.mkdir(parents=True)
    for file in sorted((ROOT / "app" / "backend").iterdir()):
        if file.suffix in (".py", ".svg"):
            shutil.copy(file, backend)
    shutil.copy(ROOT / "requirements-grammar.txt", RESOURCES)  # for Edit > Install Grammar Checker
    # What the editor knows about its packaging (app/backend/distribution.py).
    (backend / "VERSION").write_text(named + "\n", encoding="utf-8")
    (backend / "CHANNEL").write_text(target["channel"] + "\n", encoding="utf-8")
    # ...the files File > New Resume copies into a new resume folder...
    run([python, *aside, "-B", ROOT / "app" / "backend" / "project.py", "--template", RESOURCES])
    # ...the TeX engine it builds PDFs with, and the TeX packages the layout
    # loads: downloaded by Tectonic into build/, where the next build finds them.
    unpack(fetch(TECTONIC_RELEASE + target["tectonic"][0], target["tectonic"][1]), RESOURCES / "bin")
    tectonic = RESOURCES / "bin" / ("tectonic.exe" if WINDOWS else "tectonic")
    say("Collecting the TeX packages...")
    run([python, *aside, "-B", ROOT / "packaging" / "tex_packages.py", tectonic, BUILD / "tex"])
    shutil.copytree(BUILD / "tex", RESOURCES / "tex")
    # ...and the licenses of all of it, for Help > Third-Party Licenses.
    run([python, *aside, "-B", ROOT / "packaging" / "collect_licenses.py", RESOURCES / "THIRD-PARTY-LICENSES.txt",
         "--crates", ROOT / "app" / "src-tauri" / "Cargo.toml", "--tex", RESOURCES / "tex"])
    for cache in sorted(RESOURCES.rglob("__pycache__"), reverse=True):
        shutil.rmtree(cache, ignore_errors=True)


def main():
    target = TARGETS.get((platform.system(), platform.machine()))
    if target is None:
        sys.exit(f"There is no build for {platform.system()} on {platform.machine()}.")
    arguments = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    arguments.add_argument("--bundles", default=target["bundles"], help=f"what Tauri is to bundle (default: {target['bundles']})")
    bundles = arguments.parse_args().bundles
    named = version()
    stage(target, named)

    say(f"Building the app, version {named}...")
    npm = "npm.cmd" if WINDOWS else "npm"
    if not (ROOT / "app" / "node_modules").is_dir():
        run([npm, "install", "--no-audit", "--no-fund"], cwd=ROOT / "app")
    # The version has to be three numbers for some of the bundles; the
    # editor's own (the VERSION file) says the rest. The resources go in
    # beside the program.
    numbers = ".".join((named.split("-")[0].split(".") + ["0", "0", "0"])[:3]) if named[:1].isdigit() else "0.0.0"
    config = {"version": numbers, "bundle": {"resources": {RESOURCES.as_posix() + "/": "./"}}}
    # NO_STRIP: linuxdeploy's strip doesn't know the newer sections in a recent system's libraries.
    run([npm, "run", "tauri", "build", "--", "--bundles", bundles, "--config", json.dumps(config)], cwd=ROOT / "app",
        env={**os.environ, "NO_STRIP": "true"})

    DIST.mkdir(exist_ok=True)
    built = ROOT / "app" / "src-tauri" / "target" / "release" / "bundle"
    for kind in bundles.split(","):
        if kind not in BUNDLED:
            continue  # the macOS .app, which the .dmg holds
        pattern, ending = BUNDLED[kind]
        newest = max((built / kind).glob(pattern), key=lambda path: path.stat().st_mtime)
        output = DIST / (target["name"] + ending)
        shutil.copyfile(newest, output)
        output.chmod(0o755)
        say(f"Built {output} ({output.stat().st_size // 1_000_000} MB).")


if __name__ == "__main__":
    main()
