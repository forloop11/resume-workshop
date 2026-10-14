"""The resume themes (Theme > Resume Theme): the layouts in themes/, any of
which can be a resume folder's input/format.tex.

A theme is a whole layout: its fonts, colors, headings, and the commands
the generated interim/*.tex files call. Choosing one copies it over the
folder's input/format.tex, as `make theme THEME=...` does there. All of
them are written for applicant tracking systems to read: one column, a
standard face, and nothing but text and rules.
"""
import shutil
from pathlib import Path

import project

FOLDER = project.SOURCE / "themes"
LAYOUT = Path("input/format.tex")
# Each theme's file in FOLDER (without .tex), its name, and what it looks like.
THEMES = [
    ("classic", "Classic", "Helvetica, with navy headings over a rule"),
    ("modern", "Modern", "Helvetica, with teal headings and a rule beside each"),
    ("minimal", "Minimal", "Helvetica, in black, with no rules or color"),
    ("traditional", "Traditional", "Times, in black, with ruled headings"),
    ("executive", "Executive", "Palatino, with burgundy headings over a heavier rule"),
    ("slate", "Slate", "Helvetica, with slate-blue headings on a pale band"),
    ("compact", "Compact", "Helvetica, smaller and tighter, with the header at the left"),
    ("geometric", "Geometric", "Avant Garde, with indigo headings and the header at the left"),
    ("century", "Century", "Century Schoolbook, with forest-green headings"),
    ("academic", "Academic", "Latin Modern, in black, with centered headings"),
]


def available():
    """The themes the editor has, as the window lists them."""
    return [{"id": theme, "name": name, "about": about} for theme, name, about in THEMES if (FOLDER / f"{theme}.tex").is_file()]


def current(folder):
    """The theme `folder`'s layout is, or None if it is none of them as
    they are now: one edited by hand, or from another version of the editor."""
    try:
        layout = (Path(folder) / LAYOUT).read_bytes()
    except OSError:
        return None
    return next((theme["id"] for theme in available() if (FOLDER / f"{theme['id']}.tex").read_bytes() == layout), None)


def apply(folder, theme):
    """Makes `theme` the folder's layout. ValueError if there is no such
    theme, and OSError if the layout can't be written."""
    if theme not in [known["id"] for known in available()]:
        raise ValueError(f"There is no resume theme called {theme}.")
    shutil.copyfile(FOLDER / f"{theme}.tex", Path(folder) / LAYOUT)
