#!/usr/bin/env python3
"""Generate interim/geometry.tex from input/geometry.yaml."""
import re
from pathlib import Path

SRC = Path("input/geometry.yaml")
DEST = Path("interim/geometry.tex")
REQUIRED = ["top", "bottom", "left", "right", "footskip"]


def parse_geometry(path):
    values = {}
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"(\w+):\s*(\S+)", line)
            if not match:
                raise SystemExit(f"{path}: invalid line: {raw_line.rstrip()}")
            key, value = match.groups()
            values[key] = value

    missing = [key for key in REQUIRED if key not in values]
    if missing:
        raise SystemExit(f"{path}: missing required field(s): {', '.join(missing)}")
    return values


def render(values):
    options = ", ".join(f"{key}={values[key]}" for key in REQUIRED)
    return f"%% GENERATED FILE -- do not edit directly.\n%% Edit {SRC} and run `make geometry` (or `make build`) to regenerate.\n\\usepackage[{options}]{{geometry}}\n"


def main():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(render(parse_geometry(SRC)), encoding="utf-8")
    print(f"wrote {DEST} from {SRC}")


if __name__ == "__main__":
    main()
