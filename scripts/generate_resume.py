#!/usr/bin/env python3
"""Generate interim/resume_content.tex from the resume inputs."""
import json
import re
from pathlib import Path

SRC = Path("input/resume.json")
ORDER_SRC = Path("input/section_order.yaml")
DEST = Path("interim/resume_content.tex")
SECTIONS = ["summary", "competencies", "experience", "early_career", "education", "certifications", "recognition", "projects"]


def latex_text(value):
    return re.sub(r"(?<!\\)%", r"\\%", value)


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

    missing = [section for section in SECTIONS if section not in sections]
    unknown = [section for section in sections if section not in SECTIONS]
    duplicates = sorted({section for section in sections if sections.count(section) > 1})
    if missing or unknown or duplicates:
        problems = []
        if missing:
            problems.append(f"missing section(s): {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown section(s): {', '.join(unknown)}")
        if duplicates:
            problems.append(f"duplicate section(s): {', '.join(duplicates)}")
        raise SystemExit(f"{path}: {'; '.join(problems)}")
    return sections


def render_summary(data):
    return ["\\section{Professional Summary}", "", latex_text(data["summary"]), ""]


def render_competencies(data):
    lines = ["\\section{Core Competencies}", ""]
    for competency in data["competencies"]:
        lines += [f"\\entry{{{latex_text(competency['name'])}}}{{{latex_text(competency['description'])}}}", ""]
    return lines


def render_experience(data):
    lines = ["\\section{Professional Experience}", ""]
    for employer in data["experience"]:
        lines += [f"\\position{{{latex_text(employer['employer'])}}}{{{latex_text(employer['location'])}}}{{{latex_text(employer['dates'])}}}"]
        for role in employer["roles"]:
            command = "subrole" if len(employer["roles"]) > 1 else "role"
            args = f"{{{latex_text(role['title'])}}}{{{latex_text(role['dates'])}}}" if command == "subrole" else f"{{{latex_text(role['title'])}}}"
            lines += [f"\\{command}{args}", "\\begin{duties}"]
            lines += [f"  \\item {latex_text(duty)}" for duty in role["duties"]]
            lines += ["\\end{duties}", f"\\stack{{{latex_text(role['stack'])}}}", ""]
    return lines


def render_early_career(data):
    return ["\\section{Early Career}", "", "{\\small\\color{muted}", latex_text(data["early_career"]), "}", ""]


def render_education(data):
    lines = ["\\section{Education}", "", "\\begin{tabularx}{\\textwidth}{@{}X r@{}}"]
    for index, education in enumerate(data["education"]):
        spacing = " \\\\[2pt]" if index == 0 else " \\\\" 
        lines.append(f"  \\textbf{{{latex_text(education['degree'])}}}, {latex_text(education['institution'])} & {{\\small\\color{{muted}}{latex_text(education['year'])}}}{spacing}")
    return lines + ["\\end{tabularx}", ""]


def render_certifications(data):
    return ["\\section{Selected Certifications}", "", latex_text(data["certifications"]), ""]


def render_recognition(data):
    lines = ["\\section{Recognition \\& Speaking}", ""]
    for item in data["recognition"]:
        lines += [f"\\entry{{{latex_text(item['title'])}}}{{{latex_text(item['description'])}}}", ""]
    return lines


def render_projects(data):
    lines = ["\\section{Selected Independent Projects}", ""]
    for item in data["projects"]:
        lines += [f"\\entry{{{latex_text(item['title'])}}}{{{latex_text(item['description'])}}}", ""]
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


def validate(data):
    required = SECTIONS
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"{SRC}: missing required field(s): {', '.join(missing)}")
    if not isinstance(data["competencies"], list) or not all(item.get("name") and item.get("description") for item in data["competencies"]):
        raise SystemExit(f"{SRC}: competencies must contain name and description")
    for employer in data["experience"]:
        if not employer.get("employer") or not isinstance(employer.get("roles"), list):
            raise SystemExit(f"{SRC}: each experience entry needs employer and roles")
        for role in employer["roles"]:
            if not role.get("title") or not role.get("duties") or not role.get("stack"):
                raise SystemExit(f"{SRC}: each role needs title, duties, and stack")


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    section_order = parse_section_order(ORDER_SRC)
    validate(data)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(render(data, section_order), encoding="utf-8")
    print(f"wrote {DEST} from {SRC} and {ORDER_SRC}")


if __name__ == "__main__":
    main()
