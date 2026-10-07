#!/usr/bin/env python3
"""Generate output/resume-workshop.json, the schema for input/resume.json.

input/resume.json is a JSON Resume document with a few extension fields
(see scripts/jsonresume.py). This writes the JSON Resume schema vendored at
etc/resume-schema.json with those fields added, typed, and described, so an
editor pointed at it can check and autocomplete them. It doesn't include the
stricter per-section rules in generate_resume.py; `make validate` checks
those.

Standard library only, like the other generators.
"""
import copy
import json
from pathlib import Path

from generate_resume import SECTION_LISTS

SRC = Path("etc/resume-schema.json")
DEST = Path("output/resume-workshop.json")
SCHEMA_ID = "https://raw.githubusercontent.com/forloop11/resume-workshop/main/output/resume-workshop.json"

PAGEBREAK_BEFORE = {
    "type": "boolean",
    "description": "Resume Workshop: start this entry on a new page. On a section's first entry the section "
                   "heading moves with it; on an employer's first role, the employer's name does.",
}
# Extension fields by JSON Resume array; pagebreakBefore goes on every one.
EXTENSIONS = {
    "work": {
        "stack": {"type": "string", "description": "Resume Workshop: a tools line printed under this role."},
        "companyStack": {
            "type": "string",
            "description": "Resume Workshop: a tools line printed once after all of this employer's roles. "
                           "Set it on the employer's first entry.",
        },
        "earlyCareer": {
            "type": "boolean",
            "description": "Resume Workshop: list this entry in the compact Early Career section instead of "
                           "Professional Experience.",
        },
    },
}


def build(schema):
    """The JSON Resume schema with Resume Workshop's extension fields."""
    schema = copy.deepcopy(schema)
    for key in ("work", *SECTION_LISTS.values()):
        properties = schema["properties"][key]["items"]["properties"]
        properties.update({**EXTENSIONS.get(key, {}), "pagebreakBefore": PAGEBREAK_BEFORE})
    rest = {key: value for key, value in schema.items() if key not in ("$schema", "$id", "title", "description")}
    return {
        "$schema": schema["$schema"],
        "$id": SCHEMA_ID,
        "title": "Resume Workshop resume",
        "description": "A JSON Resume (v1.2.1) document with the extension fields Resume Workshop "
                       "(https://github.com/forloop11/resume-workshop) prints. Generated from "
                       f"{SRC} by scripts/generate_schema.py.",
        **rest,
    }


def main():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    schema = build(json.loads(SRC.read_text(encoding="utf-8")))
    DEST.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {DEST} from {SRC}")


if __name__ == "__main__":
    main()
