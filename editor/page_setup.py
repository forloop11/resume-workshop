"""File > Page Setup: a dialog for the page margins in input/geometry.yaml.

The file holds one LaTeX length per line ("top: 0.50in"), which
scripts/generate_geometry.py hands to the geometry package. The dialog edits
those lengths and leaves the file's comments, and any lines it doesn't know,
as they are.
"""
import re

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout

# The lengths generate_geometry.py requires, with the dialog's name for each.
FIELDS = [
    ("top", "Top margin"),
    ("bottom", "Bottom margin"),
    ("left", "Left margin"),
    ("right", "Right margin"),
    ("footskip", "Footer distance"),
]
# TeX units: how many make an inch, and the decimal places worth showing.
UNITS = {"in": (1, 2), "cm": (2.54, 2), "mm": (25.4, 1), "pt": (72.27, 1)}
LINE = re.compile(r"^(\s*)(\w+)(:\s*)(\S+)(.*)$")
LENGTH = re.compile(r"(\d*\.?\d+)([a-z]+)")
MAXIMUM = 4  # inches; more than that leaves no page


def parse(text):
    """geometry.yaml -> {name: (number, unit)}. Raises ValueError for a
    required length that is missing or isn't a plain number and unit."""
    found = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            found[match.group(2)] = match.group(4)
    lengths = {}
    for name, _ in FIELDS:
        match = LENGTH.fullmatch(found.get(name, ""))
        if not match or match.group(2) not in UNITS:
            raise ValueError(f"{name}: {found[name]}" if name in found else f"{name} is missing")
        lengths[name] = (float(match.group(1)), match.group(2))
    return lengths


def update(text, lengths):
    """geometry.yaml with `lengths` ({name: (number, unit)}) written in."""
    values = {name: f"{number:.{UNITS[unit][1]}f}{unit}" for name, (number, unit) in lengths.items()}
    lines = []
    for line in text.splitlines():
        match = LINE.match(line)
        if match and not line.lstrip().startswith("#") and match.group(2) in values:
            line = match.group(1) + match.group(2) + match.group(3) + values.pop(match.group(2)) + match.group(5)
        lines.append(line)
    lines += [f"{name}: {value}" for name, value in values.items()]
    return "\n".join(lines) + "\n"


class PageSetup(QDialog):
    def __init__(self, parent, text, changed):
        """`text` is geometry.yaml; changed(text) is called with the edited
        file each time a value changes, so the preview can follow."""
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        self.original, self.changed = text, changed
        self.rows = {}

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.initial = parse(text)
        for name, (number, unit) in self.initial.items():
            spin = QDoubleSpinBox()
            units = QComboBox()
            units.addItems(UNITS)
            units.setCurrentText(unit)
            self.rows[name] = (spin, units)
            self._set_unit(spin, unit, number)
            spin.valueChanged.connect(self._edited)
            units.currentTextChanged.connect(lambda new, spin=spin: self._convert(spin, new))
            row = QHBoxLayout()
            row.addWidget(spin, 1)
            row.addWidget(units)
            form.addRow(dict(FIELDS)[name], row)

        note = QLabel("Footer distance is from the bottom of the text to the footer's baseline. "
                      "The paper is US Letter, which is set in input/format.tex.")
        note.setProperty("kind", "label")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setMinimumWidth(360)

    def _set_unit(self, spin, unit, value):
        per_inch, decimals = UNITS[unit]
        spin.blockSignals(True)
        spin.setProperty("unit", unit)
        spin.setDecimals(decimals)
        spin.setSingleStep(10 ** -decimals * (5 if decimals == 2 else 10))
        spin.setRange(0, MAXIMUM * per_inch)
        spin.setValue(value)
        spin.blockSignals(False)

    def _convert(self, spin, unit):
        """A row's unit changed: keep the same length, in the new unit."""
        inches = spin.value() / UNITS[spin.property("unit")][0]
        self._set_unit(spin, unit, inches * UNITS[unit][0])
        self._edited()

    def _edited(self):
        self.changed(self.text())

    def text(self):
        """geometry.yaml with the dialog's values; a length that hasn't
        changed keeps the way the file wrote it."""
        lengths = {name: (spin.value(), units.currentText()) for name, (spin, units) in self.rows.items()}
        return update(self.original, {name: length for name, length in lengths.items() if length != self.initial[name]})
