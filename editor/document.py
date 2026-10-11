"""The resume as the block editor (blocks.py) edits it; no Qt in here.

A Document is input/resume.json (a JSON Resume document,
https://jsonresume.org/schema) and input/section_order.yaml, parsed. Edits
mutate the parsed objects in place, so unknown keys are preserved, and
commit() serializes them back to the two files' text.

JSON Resume stores one work[] entry per position. Like the generator
(scripts/jsonresume.py's experience_groups), the editor shows consecutive
entries with the same employer name and location as one employer card, and
writes the card's name/location back onto each of its roles. Entries flagged
earlyCareer get their own Early Career card instead.
"""
import json
import re
import sys

import project  # noqa: E402

# The section list and date format are the generators' own -- the editor's
# copy of scripts/, which it also builds with (build.py) -- so the editor
# offers exactly what it can render.
sys.path.insert(0, str(project.SOURCE / "scripts"))

from generate_resume import ORDER_LINE, PAGEBREAK, SECTION_LISTS, SECTIONS  # noqa: E402
from jsonresume import BOLD, ISO8601, plain  # noqa: E402, F401  (BOLD and plain are for the editor's other modules)

RESUME = "resume.json"
ORDER = "section_order.yaml"
# Headings as generate_resume.py prints them.
LABELS = {
    "summary": "Professional Summary",
    "competencies": "Core Competencies",
    "experience": "Professional Experience",
    "early_career": "Early Career",
    "volunteer": "Volunteer Experience",
    "education": "Education",
    "certifications": "Selected Certifications",
    "recognition": "Recognition & Speaking",
    "publications": "Publications",
    "projects": "Selected Independent Projects",
    "languages": "Languages",
    "interests": "Interests",
    "references": "References",
}
# Per-employer work[] fields the employer card edits for all of its roles.
EMPLOYER_KEYS = ["url", "description"]
DEFAULT_ORDER_HEADER = [
    "# Resume sections, in the order they appear. Omit one to leave it out.",
    "# A `- pagebreak` line starts the next section on a new page.",
]


def as_list(value):
    return value if isinstance(value, list) else []


def parse_order(text):
    """section_order.yaml -> (leading comment lines, sections, sections with
    a pagebreak line before them, {section: the heading its line gives it})."""
    header, sections, breaks, headings = [], [], set(), {}
    pending_break = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not sections and not pending_break:
                header.append(raw)
            continue
        match = ORDER_LINE.fullmatch(line)
        if not match:
            raise ValueError(f'{ORDER}: can\'t read line "{raw}"')
        if match.group(1) == PAGEBREAK:
            pending_break = True
            continue
        sections.append(match.group(1))
        heading = (match.group(2) or "").strip()
        if len(heading) > 1 and heading[0] == heading[-1] and heading[0] in "\"'":
            heading = heading[1:-1]
        if heading:
            headings[match.group(1)] = heading
        if pending_break:
            breaks.add(match.group(1))
        pending_break = False
    return header, sections, breaks, headings


def order_lines(sections, breaks, headings):
    """Page breaks and headings are only written for sections in the resume."""
    lines = []
    for section in sections:
        if section in breaks:
            lines.append(f"- {PAGEBREAK}")
        heading = headings.get(section, "").strip()
        # Quoted where a bare "#" would start a comment, should YAML tools read the file.
        lines.append(f"- {section}" + (f': "{heading}"' if "#" in heading else f": {heading}" if heading else ""))
    return lines


def group_work(work):
    """work[] -> (employer groups, earlyCareer entries). A group is
    {name, location, companyStack, roles: [work entries]}, plus any
    EMPLOYER_KEYS its roles have."""
    groups, early = [], []
    for entry in as_list(work):
        if entry.get("earlyCareer"):
            early.append(entry)
            continue
        name, location = entry.get("name") or "", entry.get("location") or ""
        if groups and groups[-1]["name"] == name and groups[-1]["location"] == location:
            groups[-1]["roles"].append(entry)
        else:
            groups.append({"name": name, "location": location, "companyStack": "", "roles": [entry]})
    for group in groups:
        group["companyStack"] = next((r["companyStack"] for r in group["roles"] if r.get("companyStack")), "")
        for key in EMPLOYER_KEYS:
            value = next((r[key] for r in group["roles"] if r.get(key)), None)
            if value:
                group[key] = value
    return groups, early


def flatten_work(groups, early):
    """Writes the employer cards back as flat work[] entries: each role gets
    its card's name/location, and companyStack lives on the first role only."""
    work = []
    for group in groups:
        for i, role in enumerate(group["roles"]):
            role["name"] = group.get("name", "")
            if group.get("location"):
                role["location"] = group["location"]
            else:
                role.pop("location", None)
            # Assign only on change, so existing keys keep their position in the file.
            company_stack = group.get("companyStack") if i == 0 else ""
            if not company_stack:
                role.pop("companyStack", None)
            elif role.get("companyStack") != company_stack:
                role["companyStack"] = company_stack
            role.pop("earlyCareer", None)
            work.append(role)
    for entry in early:
        entry["earlyCareer"] = True
        work.append(entry)
    return work


def competency_duplicates(skills):
    """For each Core Competencies entry (skills[]), what it repeats: a name
    another entry has, or a keyword listed in another entry or twice in this
    one. Compared without regard to case or spacing. Returns one list of
    messages per entry, empty where there is nothing repeated."""
    def key(text):
        return " ".join(str(text).casefold().split())

    names, keywords = {}, {}
    for i, skill in enumerate(skills):
        names.setdefault(key(skill.get("name") or ""), []).append(i)
        for keyword in as_list(skill.get("keywords")):
            keywords.setdefault(key(keyword), []).append(i)
    found = []
    for i, skill in enumerate(skills):
        messages = []
        name = key(skill.get("name") or "")
        if name and len(names[name]) > 1:
            messages.append("another competency has this name")
        # The first spelling of each keyword, so "Docker" and "docker " are reported once.
        for keyword in {key(keyword): str(keyword).strip() for keyword in reversed(as_list(skill.get("keywords")))}.values():
            places = keywords[key(keyword)]
            if not keyword or len(places) < 2:
                continue
            others = [skills[j].get("name") or f"competency #{j + 1}" for j in dict.fromkeys(places) if j != i]
            messages.append(f"“{keyword}” is also in {', '.join(others)}" if others else f"“{keyword}” is listed twice")
        found.append(messages)
    return found


def new_role(group=None):
    """A blank role; one added to `group` inherits the employer's website and
    description."""
    role = {"name": "", "position": "", "highlights": [""]}
    for key in EMPLOYER_KEYS:
        if group and group.get(key):
            role[key] = group[key]
    return role


class Document:
    def __init__(self, resume_text, order_text):
        """Raises ValueError if either file can't be read as blocks."""
        model = json.loads(resume_text)
        if not isinstance(model, dict):
            raise ValueError("expected a JSON object")
        header, self.order, self.breaks, self.headings = parse_order(order_text)
        self.order_header = header or list(DEFAULT_ORDER_HEADER)
        self.model = model
        if not isinstance(model.get("basics"), dict):
            model["basics"] = {}
        entry_lists = {"work": model.get("work"), "basics.profiles": model["basics"].get("profiles")}
        entry_lists.update((key, model.get(key)) for key in SECTION_LISTS.values())
        for name, entries in entry_lists.items():
            if not all(isinstance(entry, dict) for entry in as_list(entries)):
                raise ValueError(f"every {name} entry must be a JSON object")
        self.groups, self.early = group_work(model.get("work"))
        # Top-level arrays/objects shown before the document has them.
        self.detached = {}
        # The file text this document matches, as of the last parse or commit().
        self.parsed_resume, self.parsed_order = resume_text, order_text

    def top_level(self, key, kind=list):
        """model[key] as a list (or dict, for meta). A section the document
        doesn't have yet gets a stand-in that commit() adds to the model once
        it holds something, so just looking at an empty card doesn't write
        "volunteer": [] into resume.json."""
        value = self.model.get(key)
        if isinstance(value, kind):
            return value
        return self.detached.setdefault(key, kind())

    def list_for(self, section):
        return self.top_level(SECTION_LISTS[section])

    def included(self, section):
        return section in self.order

    def ensure_section_data(self, section):
        """Gives a section something to edit once it's added to the resume."""
        basics = self.model["basics"]
        if section == "summary" and not isinstance(basics.get("summary"), str):
            basics["summary"] = ""
        key = SECTION_LISTS.get(section)
        if key and not isinstance(self.model.get(key), list):
            self.model[key] = self.top_level(key)
            self.detached.pop(key, None)

    def has_data(self, section):
        if section == "summary":
            return bool(self.model["basics"].get("summary"))
        if section == "experience":
            return bool(self.groups)
        if section == "early_career":
            return bool(self.early)
        return bool(as_list(self.model.get(SECTION_LISTS.get(section))))

    def commit(self, order_text):
        """Serializes the document after an edit: (resume.json text,
        section_order.yaml text). `order_text` is the order file's current
        text, kept as it is (interleaved comments included) when only
        resume.json changed."""
        for key, value in list(self.detached.items()):
            if value:
                self.model[key] = value
                del self.detached[key]
        self.model["work"] = flatten_work(self.groups, self.early)
        resume_text = json.dumps(self.model, indent=2, ensure_ascii=False)
        if order_text != self.parsed_order or not self._same_order():
            order_text = "\n".join(self.order_header + order_lines(self.order, self.breaks, self.headings)) + "\n"
        self.parsed_resume, self.parsed_order = resume_text, order_text
        return resume_text, order_text

    def _same_order(self):
        try:
            _, sections, breaks, headings = parse_order(self.parsed_order)
        except ValueError:
            return False
        return order_lines(sections, breaks, headings) == order_lines(self.order, self.breaks, self.headings)

    def heading(self, section):
        """The heading `section` is printed under: its own, or the usual one."""
        return self.headings.get(section) or LABELS.get(section, section)

    def problems(self):
        """Mirrors generate_header.py and generate_resume.py's validate(), so
        a save from the block editor never produces a resume.json that
        `make build` would reject -- plus blank highlights, which it would
        happily print as empty bullets."""
        problems = []
        basics = self.model["basics"]
        for key, name in [("name", "name"), ("label", "title"), ("email", "email"), ("phone", "phone")]:
            if not basics.get(key):
                problems.append(f"Header: {name} is required.")
        location = basics.get("location")
        if not (isinstance(location, dict) and location.get("city")):
            problems.append("Header: city is required.")
        if not basics.get("url") and not any(p.get("url") for p in as_list(basics.get("profiles"))):
            problems.append("Header: add a website or at least one profile link.")
        for section in self.order:
            label = LABELS.get(section, section)
            if section == "summary" and not basics.get("summary"):
                problems.append(f"{label} is empty.")
            if section == "competencies":
                for i, skill in enumerate(as_list(self.model.get("skills")), 1):
                    if not skill.get("name") or not as_list(skill.get("keywords")):
                        problems.append(f"{label} #{i} needs a name and keywords.")
        for i, group in enumerate(self.groups, 1):
            where = group.get("name") or f"employer #{i}"
            if not group.get("name"):
                problems.append(f"Experience {where}: employer name is required.")
            for j, role in enumerate(group["roles"], 1):
                role_name = role.get("position") or f"role #{j}"
                highlights = as_list(role.get("highlights"))
                if not role.get("position"):
                    problems.append(f"Experience {where} › {role_name}: position is required.")
                if not highlights and not role.get("summary"):
                    problems.append(f"Experience {where} › {role_name}: add a highlight or a summary.")
                if any(not str(highlight).strip() for highlight in highlights):
                    problems.append(f"Experience {where} › {role_name}: fill in or delete the blank highlight.")
        return problems


def valid_date(value):
    """The JSON Resume iso8601 definition: YYYY, YYYY-MM, or YYYY-MM-DD."""
    return bool(ISO8601.match(value))
