#!/usr/bin/env python3
"""Generate interim/resume_content.tex from the resume inputs.

input/resume.json is a JSON Resume document (see scripts/jsonresume.py for the
schema notes and extension fields); input/section_order.yaml picks which
resume sections appear, and in what order, and where a `pagebreak` line
starts the next section on a new page. A listed section with no entries in
resume.json (say, no volunteer[] yet) is left out of the resume, along with
its page break.
"""
import re
from pathlib import Path

from jsonresume import ISO8601, SRC, date_range, experience_groups, group_dates, load, tex, year_range

ORDER_SRC = Path("input/section_order.yaml")
DEST = Path("interim/resume_content.tex")
# Resume sections (section_order.yaml ids). Between them they print every
# top-level JSON Resume section except meta; see SECTION_RENDERERS.
SECTIONS = [
    "summary", "competencies", "experience", "early_career", "volunteer", "education", "certifications",
    "recognition", "publications", "projects", "languages", "interests", "references",
]
# A section_order.yaml line that starts the next section on a new page.
PAGEBREAK = "pagebreak"
# The JSON Resume array each list section prints.
SECTION_LISTS = {
    "competencies": "skills", "volunteer": "volunteer", "education": "education", "certifications": "certificates",
    "recognition": "awards", "publications": "publications", "projects": "projects", "languages": "languages",
    "interests": "interests", "references": "references",
}


def parse_section_order(path):
    sections = []
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"-\s+(\w+)", line)
            if not match:
                raise SystemExit(f"{path}: invalid line: {raw_line.rstrip()}")
            sections.append(match.group(1))

    unknown = [section for section in sections if section not in SECTIONS and section != PAGEBREAK]
    duplicates = sorted({section for section in sections if section != PAGEBREAK and sections.count(section) > 1})
    if unknown or duplicates:
        problems = []
        if unknown:
            problems.append(f"unknown section(s): {', '.join(unknown)}")
        if duplicates:
            problems.append(f"duplicate section(s): {', '.join(duplicates)}")
        raise SystemExit(f"{path}: {'; '.join(problems)}")
    return sections


def early_career(data):
    return [entry for entry in data.get("work", []) if entry.get("earlyCareer")]


def section_entries(data, section):
    """The entries `section` prints, in order."""
    if section == "experience":
        return [entry for roles in experience_groups(data.get("work", [])) for entry in roles]
    if section == "early_career":
        return early_career(data)
    return data.get(SECTION_LISTS.get(section), [])


def page_break(item, index):
    """\\newpage before an entry flagged pagebreakBefore. A section's first
    entry is left to render(), which breaks before the section heading
    instead, so the heading isn't stranded at the bottom of a page."""
    return ["\\newpage"] if index and item.get("pagebreakBefore") else []


def joined(texts, items):
    """LaTeX texts joined with middle dots, with a new page before any
    entry (but the first) flagged pagebreakBefore."""
    chunks = [[]]
    for index, (text, item) in enumerate(zip(texts, items)):
        if page_break(item, index):
            chunks.append([])
        chunks[-1].append(text)
    lines = [" $\\cdot$ ".join(chunks[0])]
    for chunk in chunks[1:]:
        lines += ["", "\\newpage", " $\\cdot$ ".join(chunk)]
    return lines


def render_summary(data):
    return ["\\section{Professional Summary}", "", tex(data["basics"]["summary"]), ""]


def dots(items):
    """Plain strings -> LaTeX, joined with middle dots."""
    return " $\\cdot$ ".join(tex(item) for item in items)


def entry(title, text):
    """A bold "Title: text" line; just the title when there's no text."""
    if text:
        return f"\\entry{{{title}}}{{{text}}}"
    return f"{{\\color{{accent}}\\textbf{{{title}}}}}\\par\\vspace{{2pt}}"


def role_body(role):
    """A work or volunteer entry's summary paragraph and highlight bullets."""
    lines = []
    if role.get("summary"):
        lines += [f"\\blurb{{{tex(role['summary'])}}}"]
    if role.get("highlights"):
        lines += ["\\begin{duties}"]
        lines += [f"  \\item {tex(highlight)}" for highlight in role["highlights"]]
        lines += ["\\end{duties}"]
    return lines


def render_competencies(data):
    lines = ["\\section{Core Competencies}", ""]
    for index, skill in enumerate(data["skills"]):
        lines += page_break(skill, index)
        name = skill["name"] + (f" ({skill['level']})" if skill.get("level") else "")
        lines += [f"\\entry{{{tex(name)}}}{{{dots(skill['keywords'])}}}", ""]
    return lines


def render_experience(data):
    lines = ["\\section{Professional Experience}", ""]
    for group_index, roles in enumerate(experience_groups(data.get("work", []))):
        first = roles[0]
        # The first role's pagebreakBefore breaks before the employer's name.
        lines += page_break(first, group_index)
        lines += [f"\\position{{{tex(first['name'])}}}{{{tex(first.get('location', ''))}}}{{{group_dates(roles)}}}"]
        for role_index, role in enumerate(roles):
            if len(roles) > 1:
                command, args = "subrole", f"{{{tex(role['position'])}}}{{{date_range(role.get('startDate'), role.get('endDate'))}}}"
            else:
                command, args = "role", f"{{{tex(role['position'])}}}"
            lines += page_break(role, role_index)
            lines += [f"\\{command}{args}"]
            lines += role_body(role)
            if role.get("stack"):
                lines += [f"\\stack{{{tex(role['stack'])}}}"]
            lines += [""]
        company_stack = next((role["companyStack"] for role in roles if role.get("companyStack")), "")
        if company_stack:
            lines += [f"\\stack{{{tex(company_stack)}}}", ""]
    return lines


def render_early_career(data):
    entries = early_career(data)
    items = []
    for entry in entries:
        item = f"{tex(entry['position'])}, {tex(entry['name'])}"
        years = year_range(entry.get("startDate"), entry.get("endDate"))
        if years:
            item += f" ({years})"
        if entry.get("summary"):
            item += f", {tex(entry['summary'])}"
        items.append(item)
    return ["\\section{Early Career}", "", "{\\small\\color{muted}", *joined(items, entries), "}", ""]


def render_volunteer(data):
    lines = ["\\section{Volunteer Experience}", ""]
    for index, role in enumerate(data["volunteer"]):
        lines += page_break(role, index)
        dates = date_range(role.get("startDate"), role.get("endDate"))
        lines += [f"\\position{{{tex(role['organization'])}}}{{}}{{{dates}}}", f"\\role{{{tex(role['position'])}}}"]
        lines += role_body(role) + [""]
    return lines


def render_education(data):
    table = "\\begin{tabularx}{\\textwidth}{@{}X r@{}}"
    lines = ["\\section{Education}", "", table]
    for index, education in enumerate(data["education"]):
        if page_break(education, index):
            # \\newpage can't go inside a table: end it and start another.
            lines += ["\\end{tabularx}", "\\newpage", table]
        degree = education.get("studyType", "")
        if education.get("area"):
            degree = f"{degree} in {education['area']}" if degree else education["area"]
        place = ", ".join(part for part in (education["institution"], education.get("score")) if part)
        start, end = education.get("startDate"), education.get("endDate")
        years = year_range(start, end) if start else (end or "")[:4]
        spacing = " \\\\[2pt]" if index == 0 else " \\\\"
        if education.get("courses"):
            lines.append(f"  \\textbf{{{tex(degree)}}}, {tex(place)} & {{\\small\\color{{muted}}{years}}} \\\\")
            # \textcolor, not \color: \color at the very start of a p-column cell adds a blank line above it.
            lines.append(f"  {{\\small\\textcolor{{muted}}{{Courses: {dots(education['courses'])}}}}} &{spacing}")
        else:
            lines.append(f"  \\textbf{{{tex(degree)}}}, {tex(place)} & {{\\small\\color{{muted}}{years}}}{spacing}")
    return lines + ["\\end{tabularx}", ""]


def render_certifications(data):
    certs = data["certificates"]
    items = [tex(cert["name"] + (f", {cert['issuer']}" if cert.get("issuer") else "")) for cert in certs]
    return ["\\section{Selected Certifications}", "", *joined(items, certs), ""]


def render_recognition(data):
    lines = ["\\section{Recognition \\& Speaking}", ""]
    for index, award in enumerate(data["awards"]):
        lines += page_break(award, index)
        lines += [entry(tex(award["title"]), tex(award.get("summary", ""))), ""]
    return lines


def render_publications(data):
    lines = ["\\section{Publications}", ""]
    for index, publication in enumerate(data["publications"]):
        lines += page_break(publication, index)
        source = publication.get("publisher", "")
        year = (publication.get("releaseDate") or "")[:4]
        if year:
            source = f"{source} ({year})" if source else year
        text = ". ".join(part for part in (source, publication.get("summary")) if part)
        lines += [entry(tex(publication["name"]), tex(text)), ""]
    return lines


def render_projects(data):
    lines = ["\\section{Selected Independent Projects}", ""]
    for index, project in enumerate(data["projects"]):
        lines += page_break(project, index)
        lines += [entry(tex(project["name"]), tex(project.get("description", "")))]
        lines += role_body({"highlights": project.get("highlights")})
        if project.get("keywords"):
            lines += [f"\\stack{{{dots(project['keywords'])}}}"]
        lines += [""]
    return lines


def render_languages(data):
    languages = data["languages"]
    items = [tex(language["language"] + (f" ({language['fluency']})" if language.get("fluency") else "")) for language in languages]
    return ["\\section{Languages}", "", *joined(items, languages), ""]


def render_interests(data):
    lines = ["\\section{Interests}", ""]
    for index, interest in enumerate(data["interests"]):
        lines += page_break(interest, index)
        lines += [entry(tex(interest["name"]), dots(interest.get("keywords", []))), ""]
    return lines


def render_references(data):
    lines = ["\\section{References}", ""]
    for index, reference in enumerate(data["references"]):
        lines += page_break(reference, index)
        lines += [f"\\entry{{{tex(reference['name'])}}}{{{tex(reference['reference'])}}}", ""]
    return lines


SECTION_RENDERERS = {
    "summary": render_summary,
    "competencies": render_competencies,
    "experience": render_experience,
    "early_career": render_early_career,
    "volunteer": render_volunteer,
    "education": render_education,
    "certifications": render_certifications,
    "recognition": render_recognition,
    "publications": render_publications,
    "projects": render_projects,
    "languages": render_languages,
    "interests": render_interests,
    "references": render_references,
}


def render(data, section_order):
    lines = ["% GENERATED FILE -- do not edit directly.", f"% Edit {SRC} and {ORDER_SRC} and run `make resume` (or `make build`) to regenerate."]
    break_next = False
    for section in section_order:
        if section == PAGEBREAK:
            break_next = True
            continue
        entries = section_entries(data, section)
        if section != "summary" and not entries:
            break_next = False  # nothing to print, so no page break for it either
            continue
        if break_next or (entries and entries[0].get("pagebreakBefore")):
            lines += ["\\newpage", ""]
        break_next = False
        lines.extend(SECTION_RENDERERS[section](data))
    return "\n".join(lines)


def section_problems(data, section):
    """What's missing for `section` to render, as a list of messages. A
    section with no entries isn't a problem: render() leaves it out."""
    def entries(key, *required):
        items = data.get(key)
        if items is None:
            return []
        if not isinstance(items, list):
            return [f"{key} must be a list"]
        return [f"{key}[{i}] needs {field}" for i, item in enumerate(items) for field in required if not item.get(field)]

    if section == "summary":
        return [] if data.get("basics", {}).get("summary") else ["basics.summary is required"]
    if section == "competencies":
        return entries("skills", "name", "keywords")
    if section == "experience":
        problems = entries("work", "name", "position")
        for i, entry in enumerate(data.get("work", [])):
            if not entry.get("earlyCareer") and not entry.get("highlights") and not entry.get("summary"):
                problems.append(f"work[{i}] needs highlights or a summary")
        return problems
    if section == "early_career":
        return []
    if section == "volunteer":
        return entries("volunteer", "organization", "position")
    if section == "education":
        return entries("education", "institution")
    if section == "certifications":
        return entries("certificates", "name")
    if section == "recognition":
        return entries("awards", "title")
    if section == "publications":
        return entries("publications", "name")
    if section == "projects":
        return entries("projects", "name")
    if section == "languages":
        return entries("languages", "language")
    if section == "interests":
        return entries("interests", "name")
    if section == "references":
        return entries("references", "name", "reference")
    return []


def date_problems(data):
    """ISO 8601 checks for every date field in the schema's sections."""
    problems = []
    for key in ("work", "volunteer", "education", "certificates", "awards", "publications", "projects"):
        for i, item in enumerate(data.get(key, []) if isinstance(data.get(key), list) else []):
            for field in ("startDate", "endDate", "date", "releaseDate"):
                value = item.get(field)
                if value not in (None, "") and not ISO8601.match(str(value)):
                    problems.append(f"{key}[{i}].{field} {value!r} is not YYYY, YYYY-MM, or YYYY-MM-DD")
    return problems


def validate(data, section_order):
    problems = [problem for section in section_order for problem in section_problems(data, section)]
    problems += date_problems(data)
    for key in ("stack", "companyStack"):
        for i, entry in enumerate(data.get("work", [])):
            if not isinstance(entry.get(key, ""), str):
                problems.append(f"work[{i}].{key} must be a string")
    for key in ("work", *SECTION_LISTS.values()):
        for i, item in enumerate(data.get(key, []) if isinstance(data.get(key), list) else []):
            if not isinstance(item.get("pagebreakBefore", False), bool):
                problems.append(f"{key}[{i}].pagebreakBefore must be true or false")
    if problems:
        raise SystemExit(f"{SRC}: " + "; ".join(problems))


def main():
    data = load()
    section_order = parse_section_order(ORDER_SRC)
    validate(data, section_order)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(render(data, section_order), encoding="utf-8")
    print(f"wrote {DEST} from {SRC} and {ORDER_SRC}")


if __name__ == "__main__":
    main()
