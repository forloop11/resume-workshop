"""Checking that a web address in the resume works (the Test button beside
each URL field in the block editor, app/src/components/blocks.tsx).

A check asks the address's own server for the page, once, when the button
is clicked; nothing is looked up otherwise.
"""
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit


TIMEOUT = 15  # seconds without an answer
# Some sites turn away anything that doesn't look like a browser.
AGENT = "Mozilla/5.0 (X11; Linux x86_64) Resume-Workshop link check"
# Answers that mean "not for a program": the page may well be fine in a
# browser. LinkedIn's 999 is one.
REFUSALS = {401, 403, 405, 429, 999}
WORKS, BROKEN, UNSURE = "ok", "error", ""  # how the window's message is styled


def address(text):
    """What was typed, as a web address to open or test ("example.com" is
    "https://example.com"), or None if it isn't one."""
    text = text.strip()
    if "://" not in text:
        if re.match(r"[a-z][a-z0-9+.-]*:(?!\d)", text, re.IGNORECASE):
            return None  # another kind of address, such as mailto:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        parts.port  # raises for "mailto:me@example.com", whose "port" isn't a number
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or "." not in parts.netloc or " " in text:
        return None
    return text


def check(url):
    """Asks for the page at `url`. Returns (WORKS, BROKEN or UNSURE, what
    to tell the user)."""
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            moved = urlsplit(response.url).netloc.removeprefix("www.") != urlsplit(url).netloc.removeprefix("www.")
            return WORKS, f"{url} works" + (f" (it leads to {urlsplit(response.url).netloc})." if moved else ".")
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in REFUSALS:
            return UNSURE, f"{url} answered, but turns away automated checks ({error.code}). Open it to be sure."
        if error.code in (404, 410):
            return BROKEN, f"{url} doesn't exist: the site says there is no such page ({error.code})."
        return BROKEN, f"{url} isn't working: the site answered with an error ({error.code})."
    except urllib.error.URLError as error:
        return BROKEN, f"{url} couldn't be reached: {error.reason}."
    except (OSError, ValueError) as error:
        return BROKEN, f"{url} couldn't be reached: {error}."
