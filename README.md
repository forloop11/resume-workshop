# Resume Workshop

Resume Workshop is a source-driven LaTeX resume builder. The resume's content
lives in a single [JSON Resume](https://jsonresume.org/schema) document, with
page geometry and section order in small YAML files and the layout in a TeX
file. Standard-library Python generators turn those inputs into interim LaTeX,
and Make targets build the final PDF and plain-text resume. The project also
includes an optional local browser editor with a drag-and-drop block view of
the resume, and a Docker-based build path for a reproducible toolchain.

![Block editor: header and section order](docs/screenshots/editor-blocks.png)

## Contents

- [Resume Workshop](#resume-workshop)
  - [Contents](#contents)
  - [Requirements](#requirements)
  - [Quick start](#quick-start)
  - [Project layout](#project-layout)
  - [Make targets](#make-targets)
  - [Editing the resume](#editing-the-resume)
  - [Local editor](#local-editor)
  - [Generated files](#generated-files)
  - [Docker workflow](#docker-workflow)
  - [Spell checking](#spell-checking)
  - [Credits](#credits)

## Requirements

For a native build, install Python 3.13 or newer, GNU Make, a TeX Live
installation with the packages used by [input/format.tex](input/format.tex),
and Pandoc. The resume generators use only the Python standard library, so
`make build` needs no pip packages. The optional local editor and
`make validate` need Flask and jsonschema: run
`pip install -r requirements.txt` first.

If the LaTeX or Pandoc toolchain is not installed locally, use the Docker
workflow instead.

## Quick start

1. Edit [input/resume.json](input/resume.json), either by hand or in the
   browser editor (`make editor`).
2. Run `make build`.
3. Open `output/resume.pdf` or `output/resume.txt`.

To create a filename based on the name in the header, run `make user`. The
current generated copy is `output/todd_takala_resume.pdf`.

Example output: [resume.pdf](output/resume.pdf) and
[resume.txt](output/resume.txt).

## Project layout

- [input/](input/) contains the resume content (`resume.json`), section order, page geometry, and LaTeX layout.
- [scripts/](scripts/) contains the standard-library Python generators, the schema validator, and the Flask browser editor.
- [interim/](interim/) contains generated LaTeX fragments used during a build.
- [output/](output/) contains generated PDF and plain-text resume files.
- [docker/](docker/) contains the reproducible build image definition.
- [docs/screenshots/](docs/screenshots/) contains the editor screenshots used in this README.
- [etc/](etc/) contains the vendored JSON Resume schema, cspell configuration, and project-specific words.

## Make targets

- `make build` regenerates all interim files, then creates `output/resume.pdf` and `output/resume.txt`.
- `make header` regenerates `interim/header.tex` from the `basics` in [input/resume.json](input/resume.json) without a full build.
- `make geometry` regenerates `interim/geometry.tex` from [input/geometry.yaml](input/geometry.yaml) without a full build.
- `make resume` regenerates `interim/resume_content.tex` from [input/resume.json](input/resume.json) and [input/section_order.yaml](input/section_order.yaml) without a full build.
- `make validate` checks [input/resume.json](input/resume.json) against the JSON Resume schema and the generator's rules.
- `make user` creates `output/<name>_resume.pdf`, where `<name>` is the `basics.name`
  field from [input/resume.json](input/resume.json), lowercased, with spaces
  replaced by underscores and everything else reduced to alphanumerics/underscores
  — currently `output/todd_takala_resume.pdf`.
- `make editor` starts the local browser editor: a drag-and-drop block view of
  the resume, raw tabs for the input files, the `build`/`user` Makefile
  targets, and the generated PDF.
- `make clean` removes auxiliary pdflatex files and generated interim files.
- `make docker-image` builds the local `resume-builder` Docker image.
- `make docker-build` builds a Docker image with pdflatex/pandoc/python3 and
  runs `make build` inside a container against this directory — use this if
  you don't have the LaTeX/pandoc toolchain installed locally. Output files
  land in the `output/` directory, owned by your user, same as a native build.
- `make docker-editor` runs the local browser editor inside that same Docker
  image (via `--network host`) — use this if you don't have Python installed
  locally either.

## Editing the resume

All resume content, including the contact header, lives in
[input/resume.json](input/resume.json), a [JSON Resume](https://jsonresume.org/schema)
document. Because it follows that community schema, the same file also works
with JSON Resume themes, the registry, and other tools. `make build` (or
`make header` / `make resume`) renders it into `interim/header.tex` and
`interim/resume_content.tex`, which [input/format.tex](input/format.tex)
pulls in via `\input`. Both are generated (git-ignored), so don't edit them directly.

Write the text as plain text, not LaTeX: use `&`, `%`, `·` (middle dot), and
`–` (en dash) directly, and the generators escape them for LaTeX (`·` prints
as `$\cdot$`, `–` as `--`). Dates are ISO 8601 (`2012-01`, or just `2005`) and
print as `Jan 2012` / `2005`. A role with no `endDate` prints as `Present`.

Every section of the JSON Resume schema has a resume section. This is how
the fields map onto the printed resume (the section id is what
`section_order.yaml` uses):

| Printed (section id) | JSON Resume |
| --- | --- |
| Header | `basics`: `name`, `label` (title), `location.city`/`region`, `phone`, `email`, then `url` and `profiles[].url` as links. A link's text is its URL without the scheme or `www.`, cut off after the profile's `username` |
| Professional Summary (`summary`) | `basics.summary` |
| Professional Experience (`experience`) | `work[]`, one entry per position. Consecutive entries with the same `name` and `location` print as one employer with several roles. A role prints its `summary` (if any) above its `highlights` bullets |
| Early Career (`early_career`) | `work[]` entries with `"earlyCareer": true`, printed as `position, name (years), summary` |
| Volunteer Experience (`volunteer`) | `volunteer[]`: `organization`, dates, `position`, `summary`, and `highlights` bullets, laid out like a job |
| Education (`education`) | `education[]`: `studyType in area, institution, score`, the `startDate`–`endDate` years, and `courses` joined with `·` on a line below |
| Selected Certifications (`certifications`) | `certificates[]`: `name, issuer` |
| Recognition & Speaking (`recognition`) | `awards[]`: `title` and `summary` |
| Publications (`publications`) | `publications[]`: `name`, then `publisher (year). summary` |
| Selected Independent Projects (`projects`) | `projects[]`: `name` and `description`, `highlights` bullets, and `keywords` as a Stack line |
| Languages (`languages`) | `languages[]`: `language (fluency)`, joined with `·` |
| Interests (`interests`) | `interests[]`: `name`, then `keywords` joined with `·` |
| References (`references`) | `references[]`: `name` and `reference` |
| Core Competencies (`competencies`) | `skills[]`: `name (level)`, then `keywords` joined with `·` |

Fields not listed above (`basics.image`, `location.address`/`postalCode`/`countryCode`,
the `url` fields, `work[].description`, award and certificate dates, project
`roles`/`entity`/`type`/dates, and `meta`) are kept in the file and editable in the
block editor, but aren't printed.

[input/section_order.yaml](input/section_order.yaml) sets the order of these
sections; omit a section to leave it out of the resume. All of them are listed
by default, and a section with no entries in `resume.json` (no `volunteer[]`,
say) is skipped, along with any page break before it, so it starts printing
once you add an entry. A `- pagebreak` line starts the section after it on a
new page. The block editor's Sections card
and **New page** toggles edit this file for you.

The schema allows extra fields on any entry, and a few LaTeX-specific ones
are used:

- `pagebreakBefore`: `true` on any section entry (a role, skill, education,
  certificate, award, project, and so on) starts that entry on a new page. On
  the first entry of a section, the section heading moves to the new page
  too; on an employer's first role, the employer's name does.
- `stack` (`work[]`): a tools line printed under that role.
- `companyStack` (`work[]`): a tools line printed once after all of that
  employer's roles, for when several roles share the same tools. Set it on the
  employer's first entry.
- `earlyCareer` (`work[]`): `true` moves the entry to the Early Career section.

```json
{
  "name": "Empire Cat",
  "location": "Mesa, AZ",
  "position": "Technical Communications Manager (Engineering Manager)",
  "startDate": "2012-12",
  "endDate": "2016-06",
  "highlights": ["..."],
  "pagebreakBefore": true
}
```

Run `make validate` to check `input/resume.json` against the schema (the
[JSON Resume](https://jsonresume.org/) project's v1.2.1 schema, vendored at
[etc/resume-schema.json](etc/resume-schema.json); see [Credits](#credits)) and
against the fields each section in `section_order.yaml` needs. This needs
`jsonschema` from `requirements.txt`; `make build` itself doesn't.

Page geometry lives in [input/geometry.yaml](input/geometry.yaml). Edit that
file and run `make build` (or `make geometry`) to regenerate
`interim/geometry.tex`. The [input/format.tex](input/format.tex) file contains
the LaTeX layout, commands, and document configuration.

## Local editor

Run `make editor` or `python3 scripts/editor.py`, then open the displayed local
URL (`http://127.0.0.1:8765/` by default; set `RESUME_EDITOR_PORT` to change
it). The editor is a small [Flask](https://flask.palletsprojects.com/) app —
install its dependencies first with `pip install -r requirements.txt`. Its page
lives in [scripts/templates/editor.html](scripts/templates/editor.html), and the
block editor in [scripts/static/](scripts/static/).

The editor has four tabs — **Resume (blocks)**, `format.tex`, `geometry.yaml`,
and `resume.json` — plus a side panel with the `make build` / `make user`
buttons, the output of the last make run, and a preview of the generated PDF.
Messages about saves and builds appear under the page title, and a dot on a
tab marks unsaved changes; the browser asks before leaving the page with any.

### Block editor

The editor opens on the **Resume (blocks)** tab, a drag-and-drop editor for
`input/resume.json` and `input/section_order.yaml`. Its first two cards are the
contact header and the section order, as in the screenshot at the top of this
README:

- The **Header** card edits `basics`: name, title, contact details, and the
  profile links, which print in the order shown.
- The **Sections** card sets the section order. Drag a section into the second
  row to leave it out of the resume; its content is kept in `resume.json`.

Below those, every JSON Resume section has a collapsible card, including the
ones left out of the resume (marked "not in resume", and collapsed while
empty), and a final **Document info** card edits `meta`. Every field in the
schema has a place in these cards; fields that aren't printed are tucked
under each entry's **More fields**, which opens by itself when one of them is
filled in. Opening an empty section doesn't add anything to `resume.json`
until you add an entry.

![Block editor: experience with a multi-role employer](docs/screenshots/editor-blocks-experience.png)

- Employers, roles, highlights, profile links, and the entries in every other
  section each have a drag handle (⠿) for reordering, plus Duplicate/Delete
  buttons. Roles and highlights can also be dragged from one employer or role
  to another.
- Experience shows one card per employer, even though JSON Resume stores one
  `work[]` entry per position. Editing the employer's name, location, website,
  or description updates all of its roles.
- Fields are plain text. The **Insert · / –** buttons in the toolbar add a
  middle dot or en dash at the cursor. Dates are `YYYY-MM` (or `YYYY`), and a
  role's blank End means Present. List fields (keywords, courses, project
  highlights and roles) take one item per line.
- Emptied optional fields are removed from `resume.json`.
- Every section, employer, role, and entry card has a **New page** toggle that
  starts it on a new page in the PDF (highlighted when on). A section's toggle
  adds a `pagebreak` line to `section_order.yaml`, and the Sections card marks
  that section "new page"; the others set `pagebreakBefore` on the entry. An
  employer's toggle is its first role's, so the first role has none of its own.
- **Undo** reverses the last add, delete, or move (typing uses each field's own
  undo). **Save** checks the same rules as the generators (header fields,
  employer names, positions, a highlight or summary for each role, no blank
  highlights, required fields in each section, valid dates) and highlights
  anything missing. **Save & build** saves, then
  runs `make build`.

Drag-and-drop uses [SortableJS](https://github.com/SortableJS/Sortable),
vendored in [scripts/static/](scripts/static/) so the editor works offline.

### Raw file tabs

The `resume.json` tab shows the same document as raw JSON, and stays in sync
with the blocks tab. It's the fallback for fixing invalid JSON and for any
custom fields of your own beyond the schema.
`section_order.yaml` has no raw tab of its own, since the Sections card covers
it.

![Raw resume.json in JSON Resume format](docs/screenshots/editor-resume-json.png)

The raw tabs highlight LaTeX commands (`\command`) in every file, plus JSON
object keys in `resume.json`. A "Pretty-print JSON" button reformats
`resume.json` with indentation, and a word-wrap toggle switches between
wrapped and horizontally scrolling lines. Saving `resume.json`, from either
tab, is rejected with an error if it isn't valid JSON or doesn't match the
JSON Resume schema, instead of being written.

The `format.tex` and `geometry.yaml` tabs edit the LaTeX layout and the page
geometry:

![LaTeX layout editor](docs/screenshots/editor-format.png)

## Generated files

Files under `interim/` are generated and should not be edited directly. Update
the corresponding file under [input/](input/) and run the matching generator or
`make build`. Auxiliary LaTeX files and generated interim files can be removed
with `make clean`.

## Docker workflow

The Docker image installs Python 3 (with Flask and jsonschema, for the editor
and `make validate`), GNU Make, Pandoc, and the TeX Live packages needed by the
resume. Run `make docker-build` from the repository root to build without
installing those tools locally. Run `make docker-editor` to launch the browser
editor in the container; its default address is `http://127.0.0.1:8765/`. Set
`RESUME_EDITOR_PORT` to use another port.

## Spell checking

[etc/dictionary.txt](etc/dictionary.txt) contains project-specific spell-check
terms, configured via [etc/cspell.json](etc/cspell.json). The local editor also
enables the browser's native spellcheck while editing.

## Credits

- The `resume.json` format and schema come from [JSON Resume](https://jsonresume.org/),
  a community-driven open standard for resumes. The schema in
  [etc/resume-schema.json](etc/resume-schema.json) is an unmodified copy of
  [resume-schema v1.2.1](https://github.com/jsonresume/resume-schema/tree/v1.2.1),
  © 2024 JSON Resume, used under the MIT License
  ([etc/resume-schema.LICENSE.md](etc/resume-schema.LICENSE.md)).
- The block editor's drag-and-drop uses [SortableJS](https://github.com/SortableJS/Sortable)
  (MIT License), vendored in [scripts/static/Sortable.min.js](scripts/static/Sortable.min.js).
