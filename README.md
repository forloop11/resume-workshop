# LaTeX Resume

Created with LaTeX and makefile.

- `make build` compiles `output/resume.pdf` and `output/resume.txt`.
- `make header` regenerates `interim/header.tex` from [input/header.yaml](input/header.yaml) without a full build.
- `make geometry` regenerates `interim/geometry.tex` from [input/geometry.yaml](input/geometry.yaml) without a full build.
- `make resume` regenerates `interim/resume_content.tex` from [input/resume.json](input/resume.json) without a full build.
- `make user` creates `output/<name>_resume.pdf`, where `<name>` is the `name`
  field from [input/header.yaml](input/header.yaml), lowercased, with spaces
  replaced by underscores and everything else reduced to alphanumerics/underscores
  — currently `output/todd_takala_resume.pdf`.
- `make editor` starts a local browser editor for the files in `input/`, the `build`/`user` Makefile targets, and the generated PDF.
- `make clean` removes auxiliary pdflatex files and generated interim files.
- `make docker-build` builds a Docker image with pdflatex/pandoc/python3 and
  runs `make build` inside a container against this directory — use this if
  you don't have the LaTeX/pandoc toolchain installed locally. Output files
  land in the `output/` directory, owned by your user, same as a native build.
- `make docker-editor` runs the local browser editor inside that same Docker
  image (via `--network host`) — use this if you don't have Python installed
  locally either.

## Editing the header

Name, title, location, phone, email, and links live in [input/header.yaml](input/header.yaml)
instead of the `.tex` file. Edit that file and run `make build` (or `make header`)
to regenerate `interim/header.tex`, which [input/format.tex](input/format.tex) pulls in via `\input`.
`interim/header.tex` is generated (git-ignored) — don't edit it directly.

Page geometry lives in [input/geometry.yaml](input/geometry.yaml). Edit that
file and run `make build` (or `make geometry`) to regenerate
`interim/geometry.tex`.

The complete resume content is stored in [input/resume.json](input/resume.json) and
rendered into `interim/resume_content.tex`. The [input/format.tex](input/format.tex)
file contains the LaTeX layout, commands, and document configuration.

## Local editor

Run `make editor` or `python3 scripts/editor.py`, then open the displayed local URL.
The editor uses only Python's standard library and does not require Tkinter or third-party
packages.

The editor highlights LaTeX commands (`\command`) in every file, plus JSON object
keys when editing `input/resume.json`. A "Pretty-print JSON" button reformats
`resume.json` with indentation, a word-wrap toggle switches the editor between
wrapped and horizontally-scrolling lines, and saving `resume.json` validates it
as JSON first — an invalid save is rejected with an error instead of being written.

[etc/dictionary.txt](etc/dictionary.txt) contains project-specific spell-check terms,
configured via [etc/cspell.json](etc/cspell.json).
The local editor enables the browser's native spellcheck while editing.
[scripts/generate_header.py](scripts/generate_header.py) parses the YAML with no third-party dependencies (matching
this repo's goal of using only a standard TeX Live install), so it only supports
a narrow subset: flat `key: value` pairs plus one `links:` list of `text`/`url`
pairs, as shown in the existing file.
