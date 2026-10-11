"""Updating the editor from the project's GitHub releases (Help > Check for
Updates).

A release is a `v1.2.3` tag with the AppImage attached
(.github/workflows/release.yml). The AppImage knows its own version from the
VERSION file packaging/build-appimage.sh writes beside this one; a checkout
has none, and is updated with git instead. Updating downloads the newer
AppImage next to the running one and puts it in its place, which is safe
while it runs: the old file stays open until the editor exits.

The same releases carry a .zsync file, and the AppImage the update
information that points to it, so AppImageUpdate, Gear Lever and the like
can update it too.
"""
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

REPOSITORY = "forloop11/resume-workshop"
ASSET = "Resume_Workshop-x86_64.AppImage"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
TIMEOUT = 30  # seconds without an answer

# version: the tag without its v. url, size, sha256: the AppImage's (url None
# if the release has none; sha256 None if GitHub didn't say).
Release = namedtuple("Release", "version page notes url size sha256")


class Canceled(Exception):
    pass


def version():
    """This AppImage's version, or None in a checkout."""
    try:
        return Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def numbers(version):
    """A version's leading numbers, for comparing: "1.2.3" and "1.2.3-4-gabc"
    (a build a few commits on) are (1, 2, 3); a bare commit, as builds
    before the first tag have, is () and older than any release."""
    match = re.match(r"\d+(\.\d+)+", version or "")
    return tuple(int(part) for part in match.group().split(".")) if match else ()


def _open(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "resume-workshop"})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def latest():
    """The latest Release, or None if none has been published. Raises
    OSError if GitHub can't be reached, ValueError if its answer makes no
    sense."""
    try:
        with _open(LATEST) as response:
            release = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    try:
        asset = next((asset for asset in release["assets"] if asset["name"] == ASSET), None) or {}
        url, digest = asset.get("browser_download_url"), asset.get("digest") or ""
        return Release(
            version=release["tag_name"].removeprefix("v"),
            page=release["html_url"] if release["html_url"].startswith("https://") else RELEASES,
            notes=release.get("body") or "",
            url=url if url and url.startswith("https://") else None,
            size=asset.get("size"),
            sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"unexpected answer from GitHub ({error!r})") from error


def install(release, target, progress=lambda done, total: None, canceled=lambda: False):
    """Downloads `release`'s AppImage and puts it in place of `target`.
    Raises OSError, ValueError if what arrived isn't what the release
    lists, and Canceled once canceled() is true; `target` is untouched then."""
    target = Path(target)
    part = target.with_name(target.name + ".part")
    digest, done = hashlib.sha256(), 0
    try:
        with _open(release.url) as response, open(part, "wb") as file:
            total = release.size or int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(1 << 20):
                if canceled():
                    raise Canceled
                file.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
        if release.size and done != release.size:
            raise ValueError(f"the download is {done} bytes, not the release's {release.size}")
        if release.sha256 and digest.hexdigest() != release.sha256.lower():
            raise ValueError("the download doesn't match the release's SHA-256 sum")
        os.chmod(part, target.stat().st_mode | 0o111)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def _plain(error):
    """`error`, or the reason inside urllib's "<urlopen error ...>"."""
    reason = getattr(error, "reason", None)
    return reason if isinstance(reason, Exception) else error


class Updater(QObject):
    """Help > Check for Updates, for the main window `window`: its report()
    says how the check went, and its restart() starts the new version."""
    _checked = Signal(object)  # the latest Release, None, or the error
    _progressed = Signal(int, int)  # bytes downloaded, and in all
    _installed = Signal(object, object)  # the Release, and the error if it failed

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self._cancel = threading.Event()
        self._progress = None
        self._checked.connect(self._on_checked)
        self._progressed.connect(self._on_progress)
        self._installed.connect(self._on_installed)

    def _start(self, work):
        # A daemon thread: nothing here is worth holding up quitting for.
        self.busy = True
        threading.Thread(target=work, daemon=True).start()

    def check(self):
        if self.busy:
            return
        self.window.report("Checking for updates…")

        def work():
            try:
                self._checked.emit(latest())
            except (OSError, ValueError) as error:
                self._checked.emit(_plain(error))

        self._start(work)

    def _on_checked(self, release):
        self.busy = False
        current = version()
        if isinstance(release, Exception):
            self.window.report(f"Could not check for updates: {release}", "error")
        elif release is None:
            self.window.report("No version of Resume Workshop has been released yet.")
        elif current and numbers(release.version) <= numbers(current):
            self.window.report(f"Resume Workshop {current} is the latest version.", "ok")
        else:
            self.window.report("")
            self._offer(release, current)

    def _offer(self, release, current):
        appimage = os.environ.get("APPIMAGE")
        box = QMessageBox(QMessageBox.Icon.Information, "Resume Workshop", f"Resume Workshop {release.version} is available.", parent=self.window)
        update = None
        if not current:
            box.setInformativeText("This editor is running from a checkout of the project; update it with git pull.")
        elif not appimage or not release.url:
            box.setInformativeText(f"You have {current}. Download the new version from its release page.")
        elif not os.access(Path(appimage).parent, os.W_OK):
            box.setInformativeText(f"You have {current}. {appimage} is in a folder you can't write to, so download the new version from its release page.")
        else:
            box.setInformativeText(f"You have {current}. Updating replaces {appimage} and restarts the editor.")
            update = box.addButton("Update and Restart", QMessageBox.ButtonRole.AcceptRole)
        if release.notes:
            box.setDetailedText(release.notes)
        page = box.addButton("Release Page", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is page:
            QDesktopServices.openUrl(QUrl(release.page))
        elif update is not None and box.clickedButton() is update:
            self._install(release, Path(appimage))

    def _install(self, release, appimage):
        self._cancel.clear()
        self._progress = QProgressDialog(f"Downloading Resume Workshop {release.version}…", "Cancel", 0, 100, self.window)
        self._progress.setWindowTitle("Resume Workshop")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        # Closed in _on_installed instead, once the file is in place.
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.canceled.connect(self._cancel.set)
        self._progress.setValue(0)

        def work():
            try:
                install(release, appimage, self._progressed.emit, self._cancel.is_set)
            except (OSError, ValueError, Canceled) as error:
                self._installed.emit(release, _plain(error))
            else:
                self._installed.emit(release, None)

        self._start(work)

    def _on_progress(self, done, total):
        if self._progress is not None and total and not self._cancel.is_set():
            self._progress.setValue(min(99, done * 100 // total))

    def _on_installed(self, release, error):
        self.busy = False
        self._progress.canceled.disconnect(self._cancel.set)
        self._progress.close()
        self._progress.deleteLater()
        self._progress = None
        if isinstance(error, Canceled):
            self.window.report("Update canceled.")
        elif error is not None:
            self.window.report(f"Could not update: {error}", "error")
        elif not self.window.restart():
            self.window.report(f"Resume Workshop {release.version} is installed, and starts the next time you open the editor.", "ok")
