"""Putting the AppImage in the applications menu (Help > Add to Applications
Menu), for someone who downloaded it rather than built it:

  ~/.local/share/applications/resume-workshop.desktop
  ~/.local/share/icons/hicolor/scalable/apps/resume-workshop.svg

The same two files `make install-appimage` writes
(packaging/install-appimage.sh), pointing at the AppImage where it is now.
"""
import os
import shutil
import subprocess
from pathlib import Path

from distribution import SELF_UPDATING

ICON = Path(__file__).with_name("icon.svg")
ENTRY = """[Desktop Entry]
Type=Application
Name=Resume Workshop
Comment=Edit a JSON Resume and build it into a LaTeX PDF
Exec={exec}
Icon=resume-workshop
Categories=Office;
Terminal=false
StartupWMClass=resume-workshop
"""


def _data():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _entry():
    return _data() / "applications" / "resume-workshop.desktop"


def _icon():
    return _data() / "icons" / "hicolor" / "scalable" / "apps" / "resume-workshop.svg"


def appimage():
    """The AppImage this editor is running from, or None if it isn't one."""
    path = os.environ.get("APPIMAGE") if SELF_UPDATING else None
    return Path(path) if path else None


def _exec(path):
    """A path as a launcher's Exec line takes it: quoted, with the
    characters special inside quotes escaped, and % doubled."""
    quoted = "".join("\\" + ch if ch in '"`$\\' else ch for ch in str(path))
    return f'"{quoted}"'.replace("%", "%%")


def installed():
    """Whether the applications menu has a launcher for this AppImage."""
    try:
        return f"Exec={_exec(appimage())}\n" in _entry().read_text(encoding="utf-8")
    except OSError:
        return False


def _refresh():
    # Best effort: desktops also notice new launchers by themselves, later.
    for command in (["update-desktop-database", str(_entry().parent)],
                    ["gtk-update-icon-cache", "--force", "--ignore-theme-index", "--quiet", str(_data() / "icons" / "hicolor")]):
        if shutil.which(command[0]):
            subprocess.run(command, check=False, capture_output=True, timeout=30)


def install():
    """Writes the launcher and its icon; OSError if they can't be written."""
    for path in (_entry(), _icon()):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON, _icon())
    _entry().write_text(ENTRY.format(exec=_exec(appimage())), encoding="utf-8")
    _refresh()


def remove():
    for path in (_entry(), _icon()):
        path.unlink(missing_ok=True)
    _refresh()
