#!/usr/bin/env python3
"""Generate interim/header.tex from input/resume.json's `basics`.

Reads the resume's contact-header details (name, label, location, phone,
email, profiles) from the JSON Resume document and emits a LaTeX fragment
that input/format.tex pulls in with \\input{interim/header.tex}.

No third-party dependencies (this repo intentionally avoids anything beyond
standard TeX Live and the Python standard library for the build).
"""
import re
import sys
from pathlib import Path

from jsonresume import SRC, load, tex as escape

DEST = Path("interim/header.tex")


def link_text(url, username=""):
    """The display text for a profile link: its URL without the scheme,
    a leading "www.", or a trailing slash, and cut off after the profile's
    username if it appears in the path (so ".../users/someone/badges" shows
    as "credly.com/users/someone")."""
    text = re.sub(r"^www\.", "", re.sub(r"^[a-z]+://", "", url)).rstrip("/")
    if username and f"/{username}/" in f"{text}/":
        text = text[: text.index(f"/{username}") + len(username) + 1]
    return text


def header_fields(basics):
    """The header's fields from JSON Resume `basics`, in the shape render() takes."""
    location = basics.get("location") or {}
    place = ", ".join(part for part in (location.get("city"), location.get("region")) if part)
    fields = {
        "name": basics.get("name"),
        "title": basics.get("label"),
        "location": place,
        "phone": basics.get("phone"),
        "email": basics.get("email"),
    }
    fields = {key: value for key, value in fields.items() if value}
    profiles = ([{"url": basics["url"]}] if basics.get("url") else []) + basics.get("profiles", [])
    links = [{"text": link_text(p["url"], p.get("username", "")), "url": p["url"]} for p in profiles if p.get("url")]
    return fields, links


def render(fields, links):
    required = {"name": "name", "title": "label", "location": "location.city", "phone": "phone", "email": "email"}
    missing = [f"basics.{source}" for key, source in required.items() if key not in fields]
    if missing:
        sys.exit(f"{SRC}: missing required field(s): {', '.join(missing)}")
    if not links:
        sys.exit(f"{SRC}: basics needs a url or at least one entry under profiles")

    # Uppercase before escaping, so LaTeX commands from escape() (e.g.
    # $\cdot$ for "·") aren't uppercased into undefined ones.
    name = escape(fields["name"].upper())
    title = escape(fields["title"].upper()).replace(" | ", "~~$|$~~")
    location = escape(fields["location"])
    phone = escape(fields["phone"])
    email = fields["email"]  # used verbatim in mailto: and display

    link_parts = []
    for link in links:
        link_parts.append(r"\href{%s}{%s}" % (link["url"], escape(link["text"])))
    links_line = "~~$\\cdot$~~%\n    ".join(link_parts)

    return f"""%% GENERATED FILE -- do not edit directly.
%% Edit {SRC} and run `make header` (or `make build`) to regenerate.
\\begin{{center}}
  {{\\Huge\\bfseries\\color{{accent}}{name}}}\\\\[3pt]
  {{\\small\\color{{accent}}{title}}}\\\\[4pt]
  {{\\small\\color{{muted}}
    {location}~~$\\cdot$~~{phone}~~$\\cdot$~~%
    \\href{{mailto:{email}}}{{{email}}}
  }}\\\\[1pt]
  {{\\small\\color{{muted}}
    {links_line}
  }}
\\end{{center}}
"""


def main():
    fields, links = header_fields(load()["basics"])
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with open(DEST, "w", encoding="utf-8") as fh:
        fh.write(render(fields, links))
    print(f"wrote {DEST} from {SRC}")


if __name__ == "__main__":
    main()
