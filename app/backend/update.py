"""Updating the editor from the project's GitHub releases (Help > Check for
Updates).

A release is a `v1.2.3` tag with the AppImage attached
(.github/workflows/release.yml), and the editor knows its own version and
how it was packaged from distribution.py. Only the AppImage updates itself:
it downloads the newer AppImage next to the running one and puts it in its
place, which is safe while it runs, as the old file stays open until the
editor exits. A checkout is updated with git, and an app store's build by
the store, which doesn't get this command at all.

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

from distribution import CHANNEL, SELF_UPDATING, VERSION

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
            error.close()
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
