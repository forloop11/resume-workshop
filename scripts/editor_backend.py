#!/usr/bin/env python3
"""Python side of the desktop editor (editor/, an Electron app).

The editor calls this so it shares the generators' section list and the
validator's schema check instead of keeping copies in JavaScript:

    editor_backend.py sections   prints SECTIONS as a JSON array
    editor_backend.py check      reads a resume.json document on stdin and
                                 prints its JSON Resume schema errors as a
                                 JSON array of strings (empty if valid)

`check` needs jsonschema (`pip install -r requirements.txt`); `sections`
uses only the standard library.
"""
import json
import sys


def main():
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command == "sections":
        # SECTIONS is every section generate_resume.py knows how to render, so
        # the block editor offers exactly those in its section-order list.
        from generate_resume import SECTIONS

        print(json.dumps(SECTIONS))
    elif command == "check":
        from validate_resume import schema_errors

        try:
            data = json.loads(sys.stdin.read())
        except json.JSONDecodeError as error:
            sys.exit(f"resume.json is not valid JSON: {error}")
        print(json.dumps(schema_errors(data)))
    else:
        sys.exit("usage: editor_backend.py sections | check < resume.json")


if __name__ == "__main__":
    main()
