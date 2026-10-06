#!/usr/bin/env python3
"""Generate interim/resume_content.tex from the resume inputs.

input/resume.json is a JSON Resume document (see scripts/jsonresume.py for the
schema notes and extension fields); input/section_order.yaml picks which
resume sections appear, and in what order.
"""
import re
from pathlib import Path

from jsonresume import ISO8601, SRC, date_range, experience_groups, group_dates, load, tex, year_range

ORDER_SRC = Path("input/section_order.yaml")
DEST = Path("interim/resume_content.tex")
# Resume sections (section_order.yaml ids), and the JSON Resume data each one prints.
SECTIONS = ["summary", "competencies", "experience", "early_career", "education", "certifications", "recognition", "projects"]


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

    unknown = [section for section in sections if section not in SECTIONS]
    duplicates = sorted({section for section in sections if sections.count(section) > 1})
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


def render_summary(data):
    return ["\\section{Professional Summary}", "", tex(data["basics"]["summary"]), ""]


def render_competencies(data):
    lines = ["\\section{Core Competencies}", ""]
    for skill in data["skills"]:
        keywords = " $\\cdot$ ".join(tex(keyword) for keyword in skill["keywords"])
        lines += [f"\\entry{{{tex(skill['name'])}}}{{{keywords}}}", ""]
    return lines


def render_experience(data):
    lines = ["\\section{Professional Experience}", ""]
    for roles in experience_groups(data.get("work", [])):
        first = roles[0]
        lines += [f"\\position{{{tex(first['name'])}}}{{{tex(first.get('location', ''))}}}{{{group_dates(roles)}}}"]
        for role in roles:
            if len(roles) > 1:
                command, args = "subrole", f"{{{tex(role['position'])}}}{{{date_range(role.get('startDate'), role.get('endDate'))}}}"
            else:
                command, args = "role", f"{{{tex(role['position'])}}}"
            if role.get("pagebreakBefore"):
                lines += ["\\newpage"]
            lines += [f"\\{command}{args}", "\\begin{duties}"]
            lines += [f"  \\item {tex(highlight)}" for highlight in role["highlights"]]
            lines += ["\\end{duties}"]
            if role.get("stack"):
                lines += [f"\\stack{{{tex(role['stack'])}}}"]
            lines += [""]
        company_stack = next((role["companyStack"] for role in roles if role.get("companyStack")), "")
        if company_stack:
            lines += [f"\\stack{{{tex(company_stack)}}}", ""]
    return lines


def render_early_career(data):
    items = []
    for entry in early_career(data):
        item = f"{tex(entry['position'])}, {tex(entry['name'])} ({year_range(entry.get('startDate'), entry.get('endDate'))})"
        if entry.get("summary"):
            item += f", {tex(entry['summary'])}"
        items.append(item)
    return ["\\section{Early Career}", "", "{\\small\\color{muted}", " $\\cdot$ ".join(items), "}", ""]


def render_education(data):
    lines = ["\\section{Education}", "", "\\begin{tabularx}{\\textwidth}{@{}X r@{}}"]
    for index, education in enumerate(data["education"]):
        degree = education.get("studyType", "")
        if education.get("area"):
            degree = f"{degree} in {education['area']}" if degree else education["area"]
        year = (education.get("endDate") or education.get("startDate") or "")[:4]
        spacing = " \\\\[2pt]" if index == 0 else " \\\\"
        lines.append(f"  \\textbf{{{tex(degree)}}}, {tex(education['institution'])} & {{\\small\\color{{muted}}{year}}}{spacing}")
    return lines + ["\\end{tabularx}", ""]


def render_certifications(data):
    items = [cert["name"] + (f", {cert['issuer']}" if cert.get("issuer") else "") for cert in data["certificates"]]
    return ["\\section{Selected Certifications}", "", " $\\cdot$ ".join(tex(item) for item in items), ""]


def render_recognition(data):
    lines = ["\\section{Recognition \\& Speaking}", ""]
    for award in data["awards"]:
        lines += [f"\\entry{{{tex(award['title'])}}}{{{tex(award.get('summary', ''))}}}", ""]
    return lines


def render_projects(data):
    lines = ["\\section{Selected Independent Projects}", ""]
    for project in data["projects"]:
        lines += [f"\\entry{{{tex(project['name'])}}}{{{tex(project.get('description', ''))}}}", ""]
    return lines


SECTION_RENDERERS = {
    "summary": render_summary,
    "competencies": render_competencies,
    "experience": render_experience,
    "early_career": render_early_career,
    "education": render_education,
    "certifications": render_certifications,
    "recognition": render_recognition,
    "projects": render_projects,
}


def render(data, section_order):
    lines = ["% GENERATED FILE -- do not edit directly.", f"% Edit {SRC} and {ORDER_SRC} and run `make resume` (or `make build`) to regenerate."]
    for section in section_order:
        lines.extend(SECTION_RENDERERS[section](data))
    return "\n".join(lines)


def section_problems(data, section):
    """What's missing for `section` to render, as a list of messages."""
    def entries(key, *required):
        items = data.get(key)
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
            if not entry.get("earlyCareer") and not entry.get("highlights"):
                problems.append(f"work[{i}] needs highlights")
        return problems
    if section == "early_career":
        return [] if early_career(data) else ["no work[] entries have earlyCareer: true"]
    if section == "education":
        return entries("education", "institution")
    if section == "certifications":
        return entries("certificates", "name")
    if section == "recognition":
        return entries("awards", "title")
    if section == "projects":
        return entries("projects", "name")
    return []


def date_problems(data):
    """ISO 8601 checks for every startDate/endDate/date the generator formats."""
    problems = []
    for key in ("work", "education", "certificates", "awards", "projects"):
        for i, item in enumerate(data.get(key, []) if isinstance(data.get(key), list) else []):
            for field in ("startDate", "endDate", "date"):
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
