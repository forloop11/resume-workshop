#!/usr/bin/env python3
"""Collects the TeX packages and fonts a resume's layout loads into a folder
the AppImage carries (packaging/build_app.py), so that the editor's
Tectonic builds PDFs without downloading anything (PACKAGES in
app/backend/build.py).

The folder is a Tectonic cache: this builds a sample resume with it as the
cache, twice -- with input/format.tex as it is, and with the fonts a layout
from before Tectonic uses -- so Tectonic downloads into it what those load,
and then builds both again offline to be sure it is all there. Needs an
internet connection the first time; a folder filled before is reused.

    tex_packages.py <tectonic> <cache folder>
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "backend"))

import project  # noqa: E402

# A resume with something of each kind the layout sets differently, and the
# characters resumes use beyond plain letters.
SAMPLE = {
    **project.STARTER,
    "basics": {**project.STARTER["basics"], "image": "input/photo.png",
               "summary": "A **bold** claim: R² of 0.9, 20 °C, 5 µm, naïve café – “quoted” · €5 • ™ © ½ × ≥ 3."},
    "work": [
        {"name": "Employer", "location": "City, ST", "url": "https://example.com", "description": "What it makes.", "position": "Second",
         "startDate": "2024-01", "summary": "A summary.", "highlights": ["A first point, with **bold** in it."], "stack": "Python · SQL",
         "companyStack": "Linux"},
        {"name": "Employer", "location": "City, ST", "position": "First", "startDate": "2020-01", "endDate": "2023-12",
         "highlights": ["Another."]},
    ],
    "projects": [{"name": "Project", "description": "What it is.", "highlights": ["A point."], "keywords": ["one", "two"]}],
    "meta": {"version": "v1.0.0", "lastModified": "2026-01-01T00:00:00", "canonical": "https://example.com/resume.json"},
}


def png():
    """A small one-color PNG image, as bytes."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\x1f\x3a\x5f" * 32 for _ in range(32))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: tex_packages.py <tectonic> <cache folder>")
    tectonic, cache = sys.argv[1], Path(sys.argv[2]).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    import build  # the editor's own, which needs its pip packages

    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch) / "resume"
        project.create(folder)
        (folder / "input/resume.json").write_text(json.dumps(SAMPLE), encoding="utf-8")
        (folder / "input/photo.png").write_bytes(png())
        build.write_tex(folder)
        layout = (folder / build.TEX).read_text(encoding="utf-8")
        if "\\ifPDFTeX" not in layout:
            sys.exit(f"{build.TEX} no longer chooses its fonts with \\ifPDFTeX; see {Path(__file__).name}")
        (folder / "input/before.tex").write_text(layout.replace("\\ifPDFTeX", "\\iftrue"), encoding="utf-8")
        for offline in ([], ["--only-cached"]):
            for name in (build.TEX.name, "before.tex"):
                run = subprocess.run([tectonic, *offline, "-Z", "search-path=.", "--outdir", "output", f"input/{name}"], cwd=folder,
                                     env={**os.environ, "TECTONIC_CACHE_DIR": str(cache)}, capture_output=True, text=True)
                if run.returncode:
                    sys.exit(f"Tectonic could not build input/{name}{' offline' if offline else ''}:\n{(run.stdout + run.stderr)[-3000:]}")


if __name__ == "__main__":
    main()
