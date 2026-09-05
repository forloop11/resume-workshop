#!/usr/bin/env python3
"""Generate interim/resume_content.tex from input/resume.json."""
import json
import re
from pathlib import Path

SRC = Path("input/resume.json")
DEST = Path("interim/resume_content.tex")


def latex_text(value):
    return re.sub(r"(?<!\\)%", r"\\%", value)


def render(data):
    lines = ["% GENERATED FILE -- do not edit directly.", f"% Edit {SRC} and run `make resume` (or `make build`) to regenerate."]
    lines += ["\\section{Professional Summary}", "", latex_text(data["summary"]), "", "\\section{Core Competencies}", ""]
    for competency in data["competencies"]:
        lines += [f"\\entry{{{latex_text(competency['name'])}}}{{{latex_text(competency['description'])}}}", ""]

    lines += ["\\section{Professional Experience}", ""]
    for employer in data["experience"]:
        lines += [f"\\position{{{latex_text(employer['employer'])}}}{{{latex_text(employer['location'])}}}{{{latex_text(employer['dates'])}}}"]
        for role in employer["roles"]:
            command = "subrole" if len(employer["roles"]) > 1 else "role"
            args = f"{{{latex_text(role['title'])}}}{{{latex_text(role['dates'])}}}" if command == "subrole" else f"{{{latex_text(role['title'])}}}"
            lines += [f"\\{command}{args}", "\\begin{duties}"]
            lines += [f"  \\item {latex_text(duty)}" for duty in role["duties"]]
            lines += ["\\end{duties}", f"\\stack{{{latex_text(role['stack'])}}}", ""]

    lines += ["\\section{Early Career}", "", "{\\small\\color{muted}", latex_text(data["early_career"]), "}", "", "\\section{Education}", "", "\\begin{tabularx}{\\textwidth}{@{}X r@{}}"]
    for index, education in enumerate(data["education"]):
        spacing = " \\\\[2pt]" if index == 0 else " \\\\" 
        lines.append(f"  \\textbf{{{latex_text(education['degree'])}}}, {latex_text(education['institution'])} & {{\\small\\color{{muted}}{latex_text(education['year'])}}}{spacing}")
    lines += ["\\end{tabularx}", "", "\\section{Selected Certifications}", "", latex_text(data["certifications"]), "", "\\section{Recognition \\& Speaking}", ""]
    for item in data["recognition"]:
        lines += [f"\\entry{{{latex_text(item['title'])}}}{{{latex_text(item['description'])}}}", ""]
    lines += ["\\section{Selected Independent Projects}", ""]
    for item in data["projects"]:
        lines += [f"\\entry{{{latex_text(item['title'])}}}{{{latex_text(item['description'])}}}", ""]
    return "\n".join(lines)


def validate(data):
    required = ["summary", "competencies", "experience", "early_career", "education", "certifications", "recognition", "projects"]
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
    validate(data)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(render(data), encoding="utf-8")
    print(f"wrote {DEST} from {SRC}")


if __name__ == "__main__":
    main()
