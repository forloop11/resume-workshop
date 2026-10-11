#!/usr/bin/env python3
"""Generate interim/header.tex from input/resume.json's `basics`.

Reads the resume's contact-header details (name, label, location, phone,
email, profiles) from the JSON Resume document and emits a LaTeX fragment
that input/format.tex pulls in with \\input{interim/header.tex}. The
fragment also sets the PDF's title, author, and subject from the name and
label, so the file's properties are the resume's own.

No third-party dependencies (this repo intentionally avoids anything beyond
standard TeX Live and the Python standard library for the build).
"""
import re
import sys
from pathlib import Path

from jsonresume import SRC, load, mentions, plain, tex as escape

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
    # "1 Main St, Springfield, IL 62701, US": whichever parts there are.
    street = ", ".join(line.strip() for line in (location.get("address") or "").splitlines() if line.strip())
    region = " ".join(part for part in (location.get("region"), location.get("postalCode")) if part)
    place = ", ".join(part for part in (street, location.get("city"), region, location.get("countryCode")) if part)
    fields = {
        "name": basics.get("name"),
        "title": basics.get("label"),
        "location": place,
        "phone": basics.get("phone"),
        "email": basics.get("email"),
        "image": image_file(basics.get("image")),
    }
    fields = {key: value for key, value in fields.items() if value}
    profiles = ([{"url": basics["url"]}] if basics.get("url") else []) + basics.get("profiles", [])
    return fields, [link for link in map(profile_link, profiles) if link]


def image_file(image):
    """basics.image as a file the PDF can include, or None: pdflatex reads
    files, relative to the resume folder, and can't fetch a web address."""
    image = re.sub(r"^file://", "", image or "")
    return None if not image or re.match(r"^[a-z][a-z0-9+.-]*://", image) else image


def profile_link(profile):
    """A header link ({"text", "url"}) for a profile or the website, or None
    if it has nothing to show. The text is the URL as link_text() trims it,
    after the network's name unless the URL says it already ("Mastodon:
    example.social/@me", but just "linkedin.com/in/me"). A profile with a
    username and no URL is plain text ("Signal: me")."""
    network, username, url = profile.get("network", ""), profile.get("username", ""), profile.get("url")
    if url:
        text = link_text(url, username)
        return {"text": text if not network or mentions(text, network) else f"{network}: {text}", "url": url}
    if username:
        return {"text": f"{network}: {username}" if network else username, "url": None}
    return None


# Characters tex() writes in math mode or as ligatures, which a PDF's
# properties can't hold, as the text commands hyperref can convert.
PDF_CHARS = {"·": r"\textperiodcentered{}", "–": r"\textendash{}", "—": r"\textemdash{}"}


def pdf_string(text):
    """Plain resume text -> LaTeX for a PDF property (\\hypersetup)."""
    return "".join(PDF_CHARS.get(ch) or escape(ch) for ch in plain(text))


def check(fields, links):
    """Exits, saying what is missing, unless the header has all it needs."""
    required = {"name": "name", "title": "label", "location": "location.city", "phone": "phone", "email": "email"}
    missing = [f"basics.{source}" for key, source in required.items() if key not in fields]
    if missing:
        sys.exit(f"{SRC}: missing required field(s): {', '.join(missing)}")
    if not links:
        sys.exit(f"{SRC}: basics needs a url or at least one entry under profiles")


def render(fields, links):
    check(fields, links)

    # Uppercase before escaping, so LaTeX commands from escape() (e.g.
    # $\cdot$ for "·") aren't uppercased into undefined ones.
    name = escape(fields["name"].upper())
    title = escape(fields["title"].upper()).replace(" | ", "~~$|$~~")
    location = escape(fields["location"])
    phone = escape(fields["phone"])
    email = fields["email"]  # used verbatim in mailto: and display

    link_parts = []
    for link in links:
        link_parts.append(r"\href{%s}{%s}" % (link["url"], escape(link["text"])) if link["url"] else escape(link["text"]))
    links_line = "~~$\\cdot$~~%\n    ".join(link_parts)
    # The photo, if the layout can include one (it loads graphicx) and the
    # file is there.
    photo = ""
    if fields.get("image"):
        path = "\\detokenize{%s}" % fields["image"]
        photo = f"  \\ifdefined\\includegraphics\\IfFileExists{{{path}}}{{\\includegraphics[height=0.9in]{{{path}}}\\\\[4pt]}}{{}}\\fi\n"

    return f"""%% GENERATED FILE -- do not edit directly.
%% Edit {SRC} and run `make header` (or `make build`) to regenerate.
\\hypersetup{{
  pdftitle={{{pdf_string(fields["name"])} Resume}},
  pdfauthor={{{pdf_string(fields["name"])}}},
  pdfsubject={{{pdf_string(fields["title"])}}}
}}
\\begin{{center}}
{photo}  {{\\Huge\\bfseries\\color{{accent}}{name}}}\\\\[3pt]
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
