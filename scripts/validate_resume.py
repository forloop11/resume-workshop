#!/usr/bin/env python3
"""Validate input/resume.json against the JSON Resume schema.

Checks the document against etc/resume-schema.json (the JSON Resume schema,
https://jsonresume.org/schema, vendored so this works offline), then against
the stricter rules generate_resume.py needs to render the sections listed in
input/section_order.yaml. Needs the `jsonschema` package
(`pip install -r requirements.txt`); `make build` itself does not.
"""
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    sys.exit("validate_resume.py needs jsonschema: pip install -r requirements.txt")

SCHEMA = Path(__file__).resolve().parent.parent / "etc" / "resume-schema.json"


def schema_errors(data):
    """JSON Resume schema violations in `data`, as "path: message" strings."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
    return [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def main():
    from generate_resume import ORDER_SRC, SRC, parse_section_order, validate
    from jsonresume import load

    data = load()
    errors = schema_errors(data)
    if errors:
        sys.exit(f"{SRC} does not match the JSON Resume schema:\n  " + "\n  ".join(errors))
    validate(data, parse_section_order(ORDER_SRC))
    print(f"{SRC} is valid JSON Resume and renders every section in {ORDER_SRC}.")


if __name__ == "__main__":
    main()
