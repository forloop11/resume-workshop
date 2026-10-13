"""How this copy of the editor was packaged, which decides what it may do.

The packaging writes two files beside this one (packaging/build_app.py
does for the AppImage); a checkout has neither.

VERSION is the release, such as "1.2.3". CHANNEL is how it reached the user:

- "source": a checkout, run with `make editor` and updated with git.
- "appimage": the Linux AppImage, which updates itself from the project's
  GitHub releases (update.py).
- "appstore": an app store's build. The store updates it, and its rules
  keep it from fetching or loading code that didn't come with it.

Standard library only.
"""
from pathlib import Path


def _read(name):
    try:
        return Path(__file__).with_name(name).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


VERSION = _read("VERSION")
CHANNEL = _read("CHANNEL") or "source"
PACKAGED = CHANNEL != "source"  # the files beside the editor are its read-only template, not a resume
SELF_UPDATING = CHANNEL == "appimage"
STORE = CHANNEL == "appstore"
