#!/usr/bin/env python3
"""Generate interim/header.tex from input/header.yaml.

Reads the resume's contact-header details (name, title, location, phone,
email, links) from a simple YAML file and emits a LaTeX fragment that
input/format.tex pulls in with \\input{interim/header.tex}.

No third-party dependencies (PyYAML isn't installed on this system, and
this repo intentionally avoids anything beyond standard TeX Live). The
YAML supported here is intentionally a narrow, known subset:

    key: value
    ...
    links:
      - text: some label
        url: https://example.com
      ...
"""
import re
import sys
from pathlib import Path

SRC = "input/header.yaml"
DEST = Path("interim/header.tex")

SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape(text):
    return "".join(SPECIAL_CHARS.get(ch, ch) for ch in text)


def strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_header_yaml(path):
    fields = {}
    links = []
    current_link = None

    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue

            list_item = re.match(r"^\s*-\s*(\w+):\s*(.*)$", line)
            nested = re.match(r"^\s{2,}(\w+):\s*(.*)$", line)
            top_level = re.match(r"^(\w+):\s*(.*)$", line)

            if list_item:
                key, value = list_item.groups()
                current_link = {key: strip_quotes(value.strip())}
                links.append(current_link)
            elif nested and current_link is not None:
                key, value = nested.groups()
                current_link[key] = strip_quotes(value.strip())
            elif top_level:
                key, value = top_level.groups()
                current_link = None
                value = strip_quotes(value.strip())
                if value:
                    fields[key] = value

    return fields, links


def render(fields, links):
    required = ["name", "title", "location", "phone", "email"]
    missing = [key for key in required if key not in fields]
    if missing:
        sys.exit(f"{SRC}: missing required field(s): {', '.join(missing)}")
    if not links:
        sys.exit(f"{SRC}: at least one entry under 'links' is required")

    name = escape(fields["name"]).upper()
    title = escape(fields["title"]).upper().replace(" | ", "~~$|$~~")
    location = escape(fields["location"])
    phone = escape(fields["phone"])
    email = fields["email"]  # used verbatim in mailto: and display

    link_parts = []
    for link in links:
        if "text" not in link or "url" not in link:
            sys.exit(f"{SRC}: each link needs both 'text' and 'url'")
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
    fields, links = parse_header_yaml(SRC)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with open(DEST, "w", encoding="utf-8") as fh:
        fh.write(render(fields, links))
    print(f"wrote {DEST} from {SRC}")


if __name__ == "__main__":
    main()
