#!/usr/bin/env python3
"""Export the resume as output/rxresume.json, a Reactive Resume document.

Reactive Resume (https://rxresu.me) has its own schema, vendored at
etc/rxresume-schema.json, so this converts rather than copies:

- Text becomes HTML: summaries are paragraphs, highlights are bullet lists,
  and stack/companyStack become a "Stack:" paragraph, as in the PDF.
- Consecutive work[] roles at one employer become a single experience item
  with roles[], grouped as in the PDF; earlyCareer entries go in a custom
  "Early Career" experience section.
- input/section_order.yaml sets metadata.layout: one full-width page per
  `pagebreak` (or pagebreakBefore on a section's first entry). Page breaks
  between the entries of one section have no Reactive Resume equivalent.
- The header's links: basics.url becomes basics.website, and each profile
  a basics.customFields link. The profiles are also exported as the profiles
  section, which is left out of the layout so they don't print twice.
- Margins come from input/geometry.yaml, and colors from input/format.tex.

Item ids are UUIDs derived from each item's section and position, so
rebuilding an unchanged resume writes the same file. Standard library only,
like the other generators; `make validate` checks the result against the
schema.
"""
import json
import re
import uuid
from html import escape
from pathlib import Path

from generate_geometry import SRC as GEOMETRY_SRC, parse_geometry
from generate_header import link_text
from generate_resume import ORDER_SRC, PAGEBREAK, early_career, parse_section_order, section_entries
from jsonresume import SRC, date_range, experience_groups, format_date, group_span, load

DEST = Path("output/rxresume.json")
FORMAT_SRC = Path("input/format.tex")
# The headings generate_resume.py prints, by section_order.yaml id.
TITLES = {
    "summary": "Professional Summary", "competencies": "Core Competencies", "experience": "Professional Experience",
    "early_career": "Early Career", "volunteer": "Volunteer Experience", "education": "Education",
    "certifications": "Selected Certifications", "recognition": "Recognition & Speaking",
    "publications": "Publications", "projects": "Selected Independent Projects", "languages": "Languages",
    "interests": "Interests", "references": "References",
}
# The Reactive Resume section each section_order.yaml id fills. early_career
# is a custom section, laid out by its id.
LAYOUT_IDS = {
    "summary": "summary", "competencies": "skills", "experience": "experience", "volunteer": "volunteer",
    "education": "education", "certifications": "certifications", "recognition": "awards",
    "publications": "publications", "projects": "projects", "languages": "languages", "interests": "interests",
    "references": "references",
}
# Phosphor icons for header links, by lowercased profile network.
NETWORK_ICONS = {"linkedin": "linkedin-logo", "github": "github-logo", "gitlab": "gitlab-logo", "x": "x-logo",
                 "twitter": "twitter-logo", "medium": "medium-logo", "stackoverflow": "stack-overflow-logo"}
POINTS = {"pt": 1, "in": 72, "cm": 72 / 2.54, "mm": 72 / 25.4}
SEP = " – "


def uid(*parts):
    """A stable UUID for the item at `parts` (section, index, ...)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "resume-workshop:" + "/".join(str(part) for part in parts)))


def paragraph(text):
    return f"<p>{escape(text, quote=False)}</p>" if text else ""


def bullets(items):
    return "<ul>" + "".join(f"<li>{escape(item, quote=False)}</li>" for item in items) + "</ul>" if items else ""


def stack(text):
    return f"<p><strong>Stack:</strong> {escape(text, quote=False)}</p>" if text else ""


def role_html(role):
    """A work, volunteer, or project entry's summary, highlights, and stack."""
    return paragraph(role.get("summary")) + bullets(role.get("highlights")) + stack(role.get("stack"))


def month(value):
    """Reactive Resume dates are YYYY or YYYY-MM."""
    return (value or "")[:7] or None


def span(start, end):
    """A date range as Reactive Resume's period text and dates object. A
    range with no start is the single date `end` (an education end year)."""
    if not start:
        return single(end)
    return date_range(month(start), month(end), sep=SEP), {"start": month(start), "end": month(end), "present": not end}


def single(date):
    """A single date (an award, certificate, or publication) as text and a dates object."""
    return (format_date(month(date)) if date else ""), {"start": month(date), "end": None, "present": False}


def network_icon(profile):
    return NETWORK_ICONS.get(profile.get("network", "").lower().replace(" ", ""), "globe")


def website(url, label=""):
    return {"url": url or "", "label": label, "inlineLink": False}


def section(title, items, **extra):
    return {"title": title, "icon": "", "columns": 1, "hidden": False, "keepTogether": False,
            "startOnNewPage": False, "items": items, **extra}


def experience_item(roles, *id_parts):
    """One employer's roles (consecutive work[] entries) as an experience item."""
    first = roles[0]
    period, dates = span(*group_span(roles))
    company_stack = stack(next((role["companyStack"] for role in roles if role.get("companyStack")), ""))
    if len(roles) == 1:
        position, description, items = first["position"], role_html(first) + company_stack, []
    else:
        position, description = "", company_stack
        items = []
        for index, role in enumerate(roles):
            role_period, role_dates = span(role.get("startDate"), role.get("endDate"))
            items.append({"id": uid(*id_parts, "role", index), "position": role["position"], "period": role_period,
                          "dates": role_dates, "description": role_html(role)})
    return {
        "id": uid(*id_parts), "hidden": False, "company": first["name"], "position": position,
        "location": first.get("location", ""), "period": period, "dates": dates,
        "website": website(next((role["url"] for role in roles if role.get("url")), "")),
        "description": description, "roles": items,
    }


def education_item(education, index):
    period, dates = span(education.get("startDate"), education.get("endDate"))
    courses = education.get("courses")
    return {
        "id": uid("education", index), "hidden": False, "school": education["institution"],
        "degree": education.get("studyType", ""), "area": education.get("area", ""),
        "grade": education.get("score", ""), "location": "", "period": period, "dates": dates,
        "website": website(education.get("url")),
        "description": paragraph("Courses: " + " · ".join(courses)) if courses else "",
    }


def dated_item(key, index, item, date, **fields):
    """An award, certificate, or publication: a title, a single date, and a link."""
    text, dates = single(item.get(date))
    return {"id": uid(key, index), "hidden": False, **fields, "date": text, "dates": dates,
            "website": website(item.get("url")), "description": paragraph(item.get("summary"))}


def header_fields(basics):
    """The header's profile links, as in generate_header.py, as basics.customFields."""
    return [
        {"id": uid("basics", "link", index), "icon": network_icon(profile),
         "text": link_text(profile["url"], profile.get("username", "")), "link": profile["url"]}
        for index, profile in enumerate(basics.get("profiles", [])) if profile.get("url")
    ]


def sections(data):
    lists = {key: data.get(key, []) for key in (
        "skills", "volunteer", "education", "certificates", "awards", "publications", "projects", "languages",
        "interests", "references")}
    profiles = data["basics"].get("profiles", [])
    return {
        "profiles": section("Profiles", [
            {"id": uid("profiles", index), "hidden": False, "icon": network_icon(profile),
             "iconColor": "", "network": profile.get("network", ""), "username": profile.get("username", ""),
             "website": website(profile.get("url"), link_text(profile.get("url", ""), profile.get("username", "")))}
            for index, profile in enumerate(profiles)]),
        "experience": section(TITLES["experience"], [
            experience_item(roles, "experience", index)
            for index, roles in enumerate(experience_groups(data.get("work", [])))]),
        "education": section(TITLES["education"], [
            education_item(education, index) for index, education in enumerate(lists["education"])]),
        "projects": section(TITLES["projects"], [
            {"id": uid("projects", index), "hidden": False, "name": project["name"],
             **dict(zip(("period", "dates"), span(project.get("startDate"), project.get("endDate")))),
             "website": website(project.get("url")),
             "description": paragraph(project.get("description")) + bullets(project.get("highlights"))
             + stack(" · ".join(project.get("keywords", [])))}
            for index, project in enumerate(lists["projects"])]),
        "skills": section(TITLES["competencies"], [
            {"id": uid("skills", index), "hidden": False, "icon": "", "iconColor": "", "name": skill["name"],
             "proficiency": skill.get("level", ""), "level": 0, "keywords": skill.get("keywords", [])}
            for index, skill in enumerate(lists["skills"])]),
        "languages": section(TITLES["languages"], [
            {"id": uid("languages", index), "hidden": False, "language": language["language"],
             "fluency": language.get("fluency", ""), "level": 0}
            for index, language in enumerate(lists["languages"])]),
        "interests": section(TITLES["interests"], [
            {"id": uid("interests", index), "hidden": False, "icon": "", "iconColor": "", "name": interest["name"],
             "keywords": interest.get("keywords", [])}
            for index, interest in enumerate(lists["interests"])]),
        "awards": section(TITLES["recognition"], [
            dated_item("awards", index, award, "date", title=award["title"], awarder=award.get("awarder", ""))
            for index, award in enumerate(lists["awards"])]),
        "certifications": section(TITLES["certifications"], [
            dated_item("certifications", index, cert, "date", title=cert["name"], issuer=cert.get("issuer", ""))
            for index, cert in enumerate(lists["certificates"])]),
        "publications": section(TITLES["publications"], [
            dated_item("publications", index, publication, "releaseDate", title=publication["name"],
                       publisher=publication.get("publisher", ""))
            for index, publication in enumerate(lists["publications"])]),
        # Reactive Resume volunteer items have no position, so it leads the description.
        "volunteer": section(TITLES["volunteer"], [
            {"id": uid("volunteer", index), "hidden": False, "organization": role["organization"], "location": "",
             **dict(zip(("period", "dates"), span(role.get("startDate"), role.get("endDate")))),
             "website": website(role.get("url")),
             "description": (f"<p><strong>{escape(role['position'], quote=False)}</strong></p>"
                             if role.get("position") else "") + role_html(role)}
            for index, role in enumerate(lists["volunteer"])]),
        "references": section(TITLES["references"], [
            {"id": uid("references", index), "hidden": False, "name": reference["name"], "position": "",
             "website": website(""), "phone": "", "description": paragraph(reference.get("reference"))}
            for index, reference in enumerate(lists["references"])]),
    }


def layout_pages(data, section_order):
    """section_order.yaml as Reactive Resume pages, breaking where
    generate_resume.py's render() starts a new page."""
    pages = [[]]
    break_next = False
    for name in section_order:
        if name == PAGEBREAK:
            break_next = True
            continue
        entries = section_entries(data, name)
        if name != "summary" and not entries:
            break_next = False
            continue
        if pages[-1] and (break_next or (entries and entries[0].get("pagebreakBefore"))):
            pages.append([])
        break_next = False
        pages[-1].append(LAYOUT_IDS.get(name) or uid("early_career"))
    return [{"fullWidth": True, "main": main, "sidebar": []} for main in pages if main]


def points(length):
    """A TeX length such as "0.58in" in points."""
    match = re.fullmatch(r"([\d.]+)(pt|in|cm|mm)", length)
    if not match:
        raise SystemExit(f"{GEOMETRY_SRC}: can't convert {length!r} to points")
    return float(match.group(1)) * POINTS[match.group(2)]


def color(name, fallback):
    """An HTML color defined in format.tex as rgba(r, g, b, 1)."""
    match = re.search(r"\\definecolor\{%s\}\{HTML\}\{([0-9A-Fa-f]{6})\}" % name, FORMAT_SRC.read_text(encoding="utf-8"))
    value = match.group(1) if match else fallback
    return "rgba({}, {}, {}, 1)".format(*(int(value[i:i + 2], 16) for i in (0, 2, 4)))


def metadata(data, section_order):
    geometry = parse_geometry(GEOMETRY_SRC)
    font = {"fontFamily": "IBM Plex Sans", "fontWeights": ["400", "700"], "fontSize": 10, "lineHeight": 1.4}
    return {
        "template": "onyx",
        "layout": {"sidebarWidth": 35, "pages": layout_pages(data, section_order)},
        "page": {
            "gapX": 4, "gapY": 6,
            "marginX": round((points(geometry["left"]) + points(geometry["right"])) / 2),
            "marginY": round((points(geometry["top"]) + points(geometry["bottom"])) / 2),
            "format": "letter", "locale": "en-US", "hideLinkUnderline": True, "hideIcons": False,
            "hideSectionIcons": True,
        },
        "design": {"level": {"icon": "", "type": "hidden"},
                   "colors": {"primary": color("accent", "1F3A5F"), "text": color("body", "222222"),
                              "background": "rgba(255, 255, 255, 1)"}},
        "typography": {"body": font, "heading": {**font, "fontSize": 12}},
        "notes": f"Exported from {SRC} by scripts/export_rxresume.py; edit it there and rebuild.",
        "styleRules": [],
    }


def export(data, section_order):
    """The resume as a Reactive Resume document."""
    basics = data["basics"]
    location = basics.get("location") or {}
    return {
        "picture": {"hidden": True, "url": "", "size": 64, "rotation": 0, "aspectRatio": 1, "borderRadius": 0,
                    "borderColor": "rgba(0, 0, 0, 0.5)", "borderWidth": 0, "shadowColor": "rgba(0, 0, 0, 0.5)",
                    "shadowWidth": 0},
        "basics": {
            "name": basics.get("name", ""), "headline": basics.get("label", ""), "email": basics.get("email", ""),
            "phone": basics.get("phone", ""),
            "location": ", ".join(part for part in (location.get("city"), location.get("region")) if part),
            "website": website(basics.get("url"), link_text(basics["url"]) if basics.get("url") else ""),
            "customFields": header_fields(basics),
        },
        "summary": {"title": TITLES["summary"], "icon": "", "columns": 1, "hidden": False, "keepTogether": False,
                    "startOnNewPage": False, "content": paragraph(basics.get("summary"))},
        "sections": sections(data),
        "customSections": [{
            **section(TITLES["early_career"], [
                experience_item([entry], "early_career", index) for index, entry in enumerate(early_career(data))]),
            "id": uid("early_career"), "type": "experience",
        }],
        "metadata": metadata(data, section_order),
    }


def main():
    document = export(load(), parse_section_order(ORDER_SRC))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {DEST} from {SRC}, {ORDER_SRC}, and {GEOMETRY_SRC}")


if __name__ == "__main__":
    main()
