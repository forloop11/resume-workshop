"""Shared helpers for reading input/resume.json, a JSON Resume document.

input/resume.json follows the JSON Resume schema (https://jsonresume.org/schema,
vendored at etc/resume-schema.json), so its text is plain Unicode rather than
LaTeX: "&", "%", "·" (middle dot), and "–" (en dash) are written as-is, and
tex() escapes them when a generator writes LaTeX.

A few LaTeX-specific extras live in extension fields, which the schema allows
on every object:

- work[].stack           printed under that role
- work[].companyStack    printed once after all roles at that employer
- pagebreakBefore        on any section entry: start it on a new page (on a
                         section's first entry, the heading moves with it; on
                         an employer's first role, the employer's name does)
- work[].earlyCareer     list the entry in the compact Early Career section
                         instead of Professional Experience

scripts/generate_schema.py adds them to the schema as output/resume-workshop.json.

Standard library only, like the generators that use it.
"""
import json
import re
from pathlib import Path

SRC = Path("input/resume.json")

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
# The schema's iso8601 definition: YYYY, YYYY-MM, or YYYY-MM-DD.
ISO8601 = re.compile(r"^([1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9]|[1-2][0-9]{3}-[0-1][0-9]|[1-2][0-9]{3})$")

TEX_CHARS = {
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
    "·": r"$\cdot$",
    "–": "--",
    "—": "---",
}


def load(path=SRC):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tex(text):
    """Plain resume text -> LaTeX."""
    return "".join(TEX_CHARS.get(ch, ch) for ch in text)


def format_date(value):
    """An ISO 8601 date ("2012-01", "2012-01-15", "2012") -> "Jan 2012" / "2012"."""
    year, _, rest = value.partition("-")
    return f"{MONTHS[int(rest[:2]) - 1]} {year}" if rest else year


def date_range(start, end, sep=" -- "):
    """"Jan 2012 -- Feb 2022"; a missing end is "Present", and a range that
    starts and ends on the same date collapses to that one date."""
    if not start:
        return ""
    if start == end:
        return format_date(start)
    return f"{format_date(start)}{sep}{format_date(end) if end else 'Present'}"


def year_range(start, end):
    """Year-only form for compact lists: "2005", "1997--2002"."""
    start_year, end_year = (start or "")[:4], (end or "")[:4]
    if not end_year or start_year == end_year:
        return start_year
    return f"{start_year}--{end_year}"


def experience_groups(work):
    """Group work[] entries (excluding earlyCareer ones) by employer: consecutive
    entries with the same name and location are roles at one employer. The
    block editor in editor/blocks.js groups them the same way."""
    groups = []
    for entry in work:
        if entry.get("earlyCareer"):
            continue
        key = (entry.get("name", ""), entry.get("location", ""))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(entry)
        else:
            groups.append((key, [entry]))
    return [roles for _, roles in groups]


def group_span(roles):
    """(start, end) spanning all of a group's roles; end is None while any
    role is ongoing."""
    starts = [r["startDate"] for r in roles if r.get("startDate")]
    ends = [r.get("endDate") or None for r in roles]
    end = None if any(e is None for e in ends) else max(ends)
    return (min(starts) if starts else ""), end


def group_dates(roles, sep=" -- "):
    """The employer-level date range spanning all of a group's roles."""
    return date_range(*group_span(roles), sep=sep)
