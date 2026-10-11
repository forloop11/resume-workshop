"""The editor's color themes (View > Color Theme).

A theme gives a color to each role below. The stylesheet (style.qss) names
roles rather than colors, as @window or @accent, and the code asks for them
with color(); stylesheet() and palette() are the look as the current theme
has it. The choice is remembered in the editor's settings folder.
"""
import re
from pathlib import Path

from PySide6.QtGui import QColor, QPalette

import project

# deep, bar, window, card: the surfaces, from the one text is typed on to
# the one a card is made of. window-end is where the window's gradient ends.
# line: borders, and what a button is filled with; pressed, disabled-fill:
# that button in those states. selection: selected text's background.
# text, muted, faint, placeholder, disabled-text: text, from most to least
# prominent. accent: focus, and the main button; hover: what the pointer is
# over. on-accent: text on something filled with accent, hover, or warning.
# link, ok, error, warning: as named; invalid-fill: a field with an error.
ROLES = """deep bar window window-end card disabled-fill pressed line selection placeholder disabled-text faint muted
text accent hover link ok error warning invalid-fill on-accent""".split()
THEMES = {
    "Dracula": """#191a21 #21222c #282a36 #20212b #2d2f3d #343746 #383a4a #44475a #6272a4 #6f7493 #7b819d #8d92ab #a6acc5
                  #f8f8f2 #bd93f9 #ff79c6 #8be9fd #50fa7b #ff5555 #ffb86c #2a1a22 #282a36""",
    "Nord": """#242933 #2b303b #2e3440 #292e39 #343b49 #3b4252 #3f4758 #434c5e #5e81ac #6c7a96 #7b88a1 #8f9bb3 #a9b4c8
               #eceff4 #88c0d0 #b48ead #81a1c1 #a3be8c #bf616a #ebcb8b #3d2b33 #2e3440""",
    "Gruvbox Dark": """#1d2021 #232527 #282828 #242424 #32302f #3c3836 #45403d #504945 #665c54 #7c6f64 #928374 #a89984 #bdae93
                       #ebdbb2 #83a598 #d3869b #8ec07c #b8bb26 #fb4934 #fe8019 #3c1f1e #282828""",
    "Solarized Dark": """#00212b #01313d #002b36 #00252f #073642 #0a3b47 #0d4553 #1f4f5b #2a6373 #586e75 #657b83 #839496 #93a1a1
                         #eee8d5 #268bd2 #d33682 #2aa198 #859900 #dc322f #b58900 #3a2228 #002b36""",
    "Solarized Light": """#fdf6e3 #e6dfcb #eee8d5 #e9e3d0 #f5efdc #e0dac6 #d6d0bc #c9c2ad #b9d4e8 #93a1a1 #a0aaa8 #839496 #657b83
                          #073642 #268bd2 #d33682 #1a6fb0 #6c7c00 #dc322f #b06a00 #fbe3dc #fdf6e3""",
    "Light": """#ffffff #eaeef2 #f6f8fa #f0f3f6 #fbfcfd #e6eaef #d8dee4 #d0d7de #b6d7ff #8c959f #8c959f #6e7781 #57606a
                #1f2328 #0969da #8250df #0969da #1a7f37 #cf222e #9a6700 #ffebe9 #ffffff""",
}
THEMES = {name: dict(zip(ROLES, colors.split(), strict=True)) for name, colors in THEMES.items()}
DEFAULT = "Dracula"
current = DEFAULT


def color(role):
    """The current theme's color for `role`, as "#rrggbb"."""
    return THEMES[current][role]


def is_dark():
    return QColor(color("window")).lightness() < 128


def stylesheet():
    text = Path(__file__).with_name("style.qss").read_text(encoding="utf-8")
    return re.sub(r"@([a-z]+(?:-[a-z]+)*)", lambda match: color(match.group(1)), text)


def palette():
    """For what the stylesheet leaves to Qt's own drawing."""
    palette = QPalette()
    for role, name in {
        QPalette.ColorRole.Window: "window", QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "deep", QPalette.ColorRole.AlternateBase: "bar",
        QPalette.ColorRole.Text: "text", QPalette.ColorRole.PlaceholderText: "placeholder",
        QPalette.ColorRole.Button: "line", QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.Highlight: "selection", QPalette.ColorRole.HighlightedText: "text",
        QPalette.ColorRole.ToolTipBase: "deep", QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.Link: "link", QPalette.ColorRole.Dark: "selection",
    }.items():
        palette.setColor(role, QColor(color(name)))
    return palette


def apply(app, name):
    """Gives the application the theme `name`'s look. What has a color of
    its own besides -- the window does that part (main.py's set_theme)."""
    global current
    current = name if name in THEMES else DEFAULT
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())


def _file():
    return project.config_folder() / "theme"


def saved():
    """The theme chosen last, or the default."""
    try:
        name = _file().read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT
    return name if name in THEMES else DEFAULT


def save(name):
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(name + "\n", encoding="utf-8")
    except OSError:
        pass  # not worth failing over
