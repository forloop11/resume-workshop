#!/usr/bin/env python3
"""Generate output/resume.txt, the resume as plain text.

Written straight from input/resume.json and input/section_order.yaml, with
the same sections, order, headings, and wording as the PDF (bar the links an
entry's url makes of its name there)
(generate_header.py and generate_resume.py), for pasting into forms and for
resume parsers. Each paragraph and bullet is one unwrapped line. Page breaks
don't apply.

Standard library only, like the other generators.
"""
from pathlib import Path

from generate_header import check, header_fields
from generate_resume import (ORDER_SRC, PAGEBREAK, award_title, certificate_text, early_career, early_career_text, first, meta_parts,
                             parse_section_order, project_details, section_entries, validate)
from jsonresume import SRC, date_range, experience_groups, group_dates, load, year_range

DEST = Path("output/resume.txt")
DOT = " · "
DASH = " – "


def dots(items):
    return DOT.join(items)


def dated(text, dates):
    """ "Text (dates)"; just the text when there are no dates."""
    return f"{text} ({dates})" if dates else text


def entry(title, text):
    """ "Title: text"; just the title when there's no text."""
    return f"{title}: {text}" if text else title


def years(start, end):
    return year_range(start, end).replace("--", "–")


def role_body(role):
    """A work or volunteer entry's summary paragraph and highlight bullets."""
    lines = [role["summary"]] if role.get("summary") else []
    return lines + [f"- {highlight}" for highlight in role.get("highlights") or []]


def text_header(basics):
    fields, links = header_fields(basics)
    check(fields, links)  # the PDF's header needs the same
    contact = [fields[key] for key in ("location", "phone", "email")]
    return [fields["name"].upper(), fields["title"].upper(), dots(contact), dots(link["text"] for link in links)]


def text_summary(data):
    return [[data["basics"]["summary"]]]


def text_competencies(data):
    return [[entry(skill["name"] + (f" ({skill['level']})" if skill.get("level") else ""), dots(skill["keywords"]))] for skill in data["skills"]]


def text_experience(data):
    blocks = []
    for roles in experience_groups(data.get("work", [])):
        head = roles[0]
        employer = ", ".join(part for part in (head["name"], head.get("location")) if part)
        block = [dated(employer, group_dates(roles, sep=DASH))]
        if first(roles, "description"):
            block.append(first(roles, "description"))
        for role in roles:
            if len(roles) > 1:
                blocks.append(block)
                block = [dated(role["position"], date_range(role.get("startDate"), role.get("endDate"), sep=DASH))]
            else:
                block.append(role["position"])
            block += role_body(role)
            if role.get("stack"):
                block.append(f"Stack: {role['stack']}")
        blocks.append(block)
        company_stack = first(roles, "companyStack")
        if company_stack:
            blocks.append([f"Stack: {company_stack}"])
    return blocks


def text_early_career(data):
    return [[dots(early_career_text(item).replace("--", "–") for item in early_career(data))]]


def text_volunteer(data):
    return [
        [dated(role["organization"], date_range(role.get("startDate"), role.get("endDate"), sep=DASH)), role["position"], *role_body(role)]
        for role in data["volunteer"]
    ]


def text_education(data):
    blocks = []
    for education in data["education"]:
        degree = education.get("studyType", "")
        if education.get("area"):
            degree = f"{degree} in {education['area']}" if degree else education["area"]
        start, end = education.get("startDate"), education.get("endDate")
        line = ", ".join(part for part in (degree, education["institution"], education.get("score")) if part)
        block = [dated(line, years(start, end) if start else (end or "")[:4])]
        if education.get("courses"):
            block.append(f"Courses: {dots(education['courses'])}")
        blocks.append(block)
    return blocks


def text_certifications(data):
    return [[dots(certificate_text(cert) for cert in data["certificates"])]]


def text_recognition(data):
    return [[entry(award_title(award), award.get("summary", ""))] for award in data["awards"]]


def text_publications(data):
    blocks = []
    for publication in data["publications"]:
        source = publication.get("publisher", "")
        year = (publication.get("releaseDate") or "")[:4]
        if year:
            source = f"{source} ({year})" if source else year
        blocks.append([entry(publication["name"], ". ".join(part for part in (source, publication.get("summary")) if part))])
    return blocks


def text_projects(data):
    blocks = []
    for project in data["projects"]:
        details = project_details(project, sep=DASH)
        title = f"{project['name']} ({details})" if details else project["name"]
        block = [entry(title, project.get("description", "")), *role_body({"highlights": project.get("highlights")})]
        if project.get("keywords"):
            block.append(f"Stack: {dots(project['keywords'])}")
        blocks.append(block)
    return blocks


def text_languages(data):
    return [[dots(language["language"] + (f" ({language['fluency']})" if language.get("fluency") else "") for language in data["languages"])]]


def text_interests(data):
    return [[entry(interest["name"], dots(interest.get("keywords", [])))] for interest in data["interests"]]


def text_references(data):
    return [[entry(reference["name"], reference["reference"])] for reference in data["references"]]


# Each section's heading, as generate_resume.py prints it, and its blocks:
# lists of lines, printed with a blank line between them.
SECTION_TEXT = {
    "summary": ("Professional Summary", text_summary),
    "competencies": ("Core Competencies", text_competencies),
    "experience": ("Professional Experience", text_experience),
    "early_career": ("Early Career", text_early_career),
    "volunteer": ("Volunteer Experience", text_volunteer),
    "education": ("Education", text_education),
    "certifications": ("Selected Certifications", text_certifications),
    "recognition": ("Recognition & Speaking", text_recognition),
    "publications": ("Publications", text_publications),
    "projects": ("Selected Independent Projects", text_projects),
    "languages": ("Languages", text_languages),
    "interests": ("Interests", text_interests),
    "references": ("References", text_references),
}


def render(data, section_order):
    blocks = [text_header(data["basics"])]
    for section in section_order:
        if section == PAGEBREAK or (section != "summary" and not section_entries(data, section)):
            continue
        heading, text = SECTION_TEXT[section]
        blocks += [[heading.upper()], *text(data)]
    meta = data.get("meta") or {}
    if meta_parts(meta) or meta.get("canonical"):
        blocks.append([dots([*meta_parts(meta), *([meta["canonical"]] if meta.get("canonical") else [])])])
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def main():
    data = load()
    section_order = parse_section_order(ORDER_SRC)
    validate(data, section_order)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(render(data, section_order), encoding="utf-8")
    print(f"wrote {DEST} from {SRC} and {ORDER_SRC}")


if __name__ == "__main__":
    main()
