#!/usr/bin/env python3
"""Validate input/resume.json against the JSON Resume schema.

Checks the document against etc/resume-schema.json (the JSON Resume schema,
https://jsonresume.org/schema, vendored so this works offline), then against
the stricter rules generate_resume.py needs to render the sections listed in
input/section_order.yaml. Last, it checks what export_rxresume.py would write
against etc/rxresume-schema.json (the Reactive Resume schema,
https://rxresu.me/schema.json). Needs the `jsonschema` package
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
RXRESUME_SCHEMA = SCHEMA.with_name("rxresume-schema.json")


def schema_errors(data, schema_path=SCHEMA, validator_class=jsonschema.Draft7Validator):
    """Schema violations in `data` (JSON Resume by default), as "path: message" strings."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = validator_class(schema, format_checker=jsonschema.FormatChecker())
    return [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def main():
    from export_rxresume import export
    from generate_resume import ORDER_SRC, SRC, parse_section_order, validate
    from jsonresume import load

    data = load()
    errors = schema_errors(data)
    if errors:
        sys.exit(f"{SRC} does not match the JSON Resume schema:\n  " + "\n  ".join(errors))
    section_order = parse_section_order(ORDER_SRC)
    validate(data, section_order)
    errors = schema_errors(export(data, section_order), RXRESUME_SCHEMA, jsonschema.Draft202012Validator)
    if errors:
        sys.exit("The Reactive Resume export does not match its schema:\n  " + "\n  ".join(errors))
    print(f"{SRC} is valid JSON Resume, renders every section in {ORDER_SRC}, and exports as valid Reactive Resume.")


if __name__ == "__main__":
    main()
