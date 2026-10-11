"""Drag-and-drop block editor for input/resume.json (a JSON Resume document,
https://jsonresume.org/schema) and input/section_order.yaml.

Works on the same in-memory file contents as the raw editor tabs (the
window's `files`, see main.py): every edit here re-serializes the document
(document.py) back into files["resume.json"], so switching to the raw tab
always shows the current blocks, and vice versa. Text is plain Unicode
(&, %, ·, –); scripts/generate_resume.py escapes it for LaTeX.

Every property in the schema (etc/resume-schema.json) has a field here.
The less usual ones sit under each card's "More fields"; all are printed.

Each section, employer, role, and entry card has a "New page" toggle: a
`pagebreak` line before the section in section_order.yaml, or
"pagebreakBefore": true on the entry (an employer's is its first role's).
"""
import copy
import re

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget
from shiboken6 import isValid

import links
import themes
from document import EMPLOYER_KEYS, LABELS, ORDER, RESUME, SECTIONS, Document, as_list, competency_duplicates, new_role, valid_date
from widgets import AutoTextEdit, Chip, Collapsible, DragSurface, Handle, LineEdit, SortableList, restyle

UNDO_LIMIT = 50
PREVIEW_PHRASE_MIN = 4  # shorter text matches all over the PDF
# Fields that hold a web address, which get Test and Open buttons.
LINKS = {"url", "canonical"}
# Fields that hold identifiers rather than words, so aren't spell-checked.
NOT_WORDS = {"email", "phone", "url", "image", "username", "postalCode", "countryCode", "canonical", "version", "lastModified"}


def on_edit(control, edited):
    """Calls edited() when the text in `control` changes. Its textChanged
    signal alone won't do: it also fires when the proofing underlines are
    redrawn (proofing.py), and an edit handler run then could drop an empty
    key the file had."""
    last = [control.toPlainText()]

    def changed():
        if control.toPlainText() != last[0]:
            last[0] = control.toPlainText()
            edited()

    control.textChanged.connect(changed)


def button(label, on_click, kind=None, tip=None):
    widget = QPushButton(label)
    widget.clicked.connect(lambda: on_click())
    if kind:
        widget.setProperty("kind", kind)
    if tip:
        widget.setToolTip(tip)
    return widget


def label(text, kind="label", hint=None):
    widget = QLabel(text + (f'<span style="color:{themes.color("muted")}"> — {hint}</span>' if hint else ""))
    widget.setProperty("kind", kind)
    return widget


def column(*widgets, spacing=8):
    """Widgets stacked in a column; an "add" button keeps its own width."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget.property("kind") == "add":
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            layout.addWidget(widget)
    return box


def row(*widgets, stretch=None):
    """Fields side by side, equally wide unless `stretch` says otherwise."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for i, widget in enumerate(widgets):
        layout.addWidget(widget, stretch[i] if stretch else 1, Qt.AlignmentFlag.AlignTop)
    return box


class BlocksEditor(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        self.doc = None  # the parsed resume, or None if it can't be shown as blocks
        self.undo_stack = []
        self.section_open = {}  # card key -> open, once the user toggles it
        self.open_employers = set()  # id() of each expanded employer group
        self.controls = []  # the fields on screen, for validate()
        self.cards = []  # the section and employer cards, for Expand/Collapse all
        self.last_field = None  # most recently focused field, for the · and – buttons
        self.duplicate_notes, self.duplicate_tag = [], None  # see update_duplicates()
        self.checker = links.Checker(self)  # tests the addresses in URL fields
        self.checker.checked.connect(self._link_tested)
        self.testing = {}  # address being tested -> its Test button
        self._scroll_to = None

        self.undo_button = button("Undo", self.undo)
        actions = QFrame()
        actions.setProperty("kind", "actions")
        bar = QHBoxLayout(actions)
        bar.addWidget(button("Save", self.save, "primary"))
        bar.addWidget(button("Save && build", window.save_and_build))
        bar.addWidget(self.undo_button)
        bar.addWidget(button("Expand all", lambda: self.set_all_open(True)))
        bar.addWidget(button("Collapse all", lambda: self.set_all_open(False)))
        bar.addWidget(button("Reload", window.reload))
        bar.addStretch(1)
        insert = label("Insert")
        insert.setToolTip("Insert at the cursor in the last field you clicked")
        bar.addWidget(insert)
        for char, tip in [("·", "Middle dot (printed as $\\cdot$)"), ("–", "En dash (printed as --)")]:
            insert_button = button(char, lambda char=char: self.insert_char(char), tip=tip)
            insert_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep the field's focus and selection
            bar.addWidget(insert_button)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._restore_scroll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(actions)
        layout.addWidget(self.scroll)
        QApplication.instance().focusChanged.connect(self._focus_changed)

    # --- document <-> files ------------------------------------------------------

    def open(self):
        """Shows the files' current content. They are re-parsed only if they
        changed since this editor last produced them (e.g. after editing the
        raw resume.json tab or a reload), so expanded/collapsed state and the
        undo history survive switching tabs."""
        files = self.win.files
        if self.doc and files[RESUME] == self.doc.parsed_resume and files[ORDER] == self.doc.parsed_order:
            return
        self._parse()
        self.undo_stack = []
        self.render()

    def _parse(self):
        self.open_employers.clear()
        try:
            self.doc = Document(self.win.files[RESUME], self.win.files[ORDER])
        except ValueError as error:
            self.doc = None
            self.controls, self.cards = [], []
            message = QLabel(f"The block editor can't open this resume: {error}")
            message.setWordWrap(True)
            box = QFrame()
            box.setProperty("kind", "blocks-error")
            layout = QVBoxLayout(box)
            layout.addWidget(message)
            layout.addWidget(button(f"Fix it in the raw {RESUME} tab first", lambda: self.win.select_file(RESUME), "link"), 0, Qt.AlignmentFlag.AlignLeft)
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(16, 16, 16, 16)
            page_layout.addWidget(box)
            page_layout.addStretch(1)
            self._show(page)

    def reset(self):
        """Forget the parsed document so the next open() re-reads the files."""
        self.doc = None

    def commit(self):
        """Writes the document back into the files after any edit."""
        files = self.win.files
        files[RESUME], files[ORDER] = self.doc.commit(files[ORDER])
        self.win.refresh_tabs()

    def change(self, mutate):
        """Structural edits (add/delete/move) are undoable and re-render the
        blocks; plain typing isn't (the field's own Ctrl+Z covers that)."""
        self.undo_stack.append((self.win.files[RESUME], self.win.files[ORDER]))
        del self.undo_stack[:-UNDO_LIMIT]
        mutate()
        self.commit()
        self.render()

    def undo(self):
        """Restoring a snapshot re-parses it into new objects, so which
        employers were expanded is carried over by position."""
        if not self.undo_stack or not self.doc:
            return
        open_indexes = [i for i, group in enumerate(self.doc.groups) if id(group) in self.open_employers]
        self.win.files[RESUME], self.win.files[ORDER] = self.undo_stack.pop()
        self._parse()
        if self.doc:
            self.open_employers = {id(self.doc.groups[i]) for i in open_indexes if i < len(self.doc.groups)}
            self.render()
        self.win.refresh_tabs()

    def move(self, src, old, dst, new):
        """Finishes a drag: the default SortableList on_move."""
        self.change(lambda: dst.insert(new, src.pop(old)))

    # --- fields ------------------------------------------------------------------

    def _field(self, control, text, required, hint, beside=()):
        """A labeled control, with the `beside` widgets to its right."""
        self.controls.append(control)
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(label(text + (f'<span style="color:{themes.color("hover")}"> *</span>' if required else ""), hint=hint))
        line = QHBoxLayout()
        line.setSpacing(4)
        line.addWidget(control, 1)
        for widget in beside:
            line.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(line)
        return box

    def link_buttons(self, control):
        """Test and Open buttons for a field holding a web address."""
        def address():
            url = links.address(control.toPlainText())
            if url is None:
                self.win.report("That isn't a web address to open or test." if control.toPlainText().strip() else "There's no address here yet.", "error")
            return url

        def test():
            url = address()
            if url:
                test_button.setText("…")
                self.testing[url] = test_button
                self.win.report(f"Testing {url}…")
                self.checker.start(url)

        def open_link():
            url = address()
            if url and not QDesktopServices.openUrl(QUrl(url)):
                self.win.report(f"Could not open {url}.", "error")

        test_button = button("Test", test, "tool", "Check that this address works")
        return [test_button, button("Open", open_link, "tool", "Open this address in your browser")]

    def _link_tested(self, url, result, message):
        self.win.report(message, result)
        tested = self.testing.pop(url, None)
        if tested is not None and isValid(tested):  # the card may have been redrawn since
            tested.setText({links.WORKS: "✓ Test", links.BROKEN: "✗ Test"}.get(result, "? Test"))

    def field(self, obj, key, text, *, multiline=False, required=False, date=False, placeholder="", hint=None, on_input=None):
        """A line edit (or auto-growing text box, with multiline) bound to
        obj[key]. An emptied field removes its key, as JSON Resume documents
        usually omit unused fields -- except required ones, which stay as "".
        date: validated as YYYY / YYYY-MM / YYYY-MM-DD."""
        value = obj.get(key)
        value = "" if value is None else str(value)
        control = AutoTextEdit(value) if multiline else LineEdit(value)
        if not date and key not in NOT_WORDS:
            self.win.proof(control, grammar=multiline)
        if placeholder or date:
            control.setPlaceholderText(placeholder or "YYYY-MM")
        control.required, control.date = required, date

        def changed():
            value = control.toPlainText()
            if value == "" and not required:
                obj.pop(key, None)
            else:
                obj[key] = value
            restyle(control, "invalid", False)
            self.commit()
            if on_input:
                on_input()

        on_edit(control, changed)
        return self._field(control, text, required, hint, self.link_buttons(control) if key in LINKS else ())

    def lines_field(self, obj, key, text, *, hint=None, required=False, on_input=None):
        """A text box editing obj[key], a list of strings, one item per line.
        Like field(), emptying an optional one removes its key."""
        control = AutoTextEdit("\n".join(str(item) for item in as_list(obj.get(key))), min_lines=2)
        self.win.proof(control)
        control.required, control.date = required, False

        def changed():
            items = [line.strip() for line in control.toPlainText().split("\n") if line.strip()]
            if not items and not required:
                obj.pop(key, None)
            else:
                obj[key] = items
            restyle(control, "invalid", False)
            self.commit()
            if on_input:
                on_input()

        on_edit(control, changed)
        return self._field(control, text, required, hint)

    def dates(self, obj, *, placeholder="", end_placeholder="", hint=None):
        return row(
            self.field(obj, "startDate", "Start", date=True, placeholder=placeholder, hint=hint),
            self.field(obj, "endDate", "End", date=True, placeholder=end_placeholder or placeholder, hint=hint))

    def more(self, *children):
        """The less usual fields, folded away; open if any is filled in."""
        box = column(*children)
        filled = any(control.toPlainText() for control in box.findChildren(QTextEdit))
        card = Collapsible("more", filled)
        card.head.addWidget(label("More fields"))
        card.head.addStretch(1)
        card.content.setContentsMargins(10, 4, 0, 4)
        card.content.addWidget(box)
        return card

    def page_toggle(self, on, set_on):
        """A "New page" toggle: on means a LaTeX \\newpage before this card's content."""
        toggle = button("New page", lambda: self.change(lambda: set_on(not on)), "page-toggle",
                        "Starts on a new page (click to undo)" if on else "Start on a new page")
        toggle.setProperty("on", on)
        return toggle

    def entry_page_toggle(self, entry):
        """The toggle for an entry's own "pagebreakBefore"."""
        def set_on(on):
            if on:
                entry["pagebreakBefore"] = True
            else:
                entry.pop("pagebreakBefore", None)
        return self.page_toggle(bool(entry.get("pagebreakBefore")), set_on)

    def item_tools(self, items, index, *, duplicate=True, pagebreak=None):
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if pagebreak:
            layout.addWidget(pagebreak)
        if duplicate:
            layout.addWidget(button("Duplicate", lambda: self.change(lambda: items.insert(index + 1, copy.deepcopy(items[index]))), "tool"))
        layout.addWidget(button("Delete", lambda: self.change(lambda: items.pop(index)), "danger"))
        return box

    def entry_list(self, items, group, render_fields, *, add_label, blank, pagebreak=True):
        """A card for each of a list's simple entries: a drag handle, the
        fields from render_fields(item), and Duplicate/Delete."""
        entries = SortableList(items, group, self.move)
        for i, item in enumerate(items):
            card = QFrame()
            card.setProperty("kind", "entry")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)
            grip = Handle(card)
            grip.setContentsMargins(0, 20, 0, 0)
            layout.addWidget(grip, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(column(*render_fields(item)), 1)
            layout.addWidget(self.item_tools(items, i, pagebreak=self.entry_page_toggle(item) if pagebreak else None), 0, Qt.AlignmentFlag.AlignTop)
            entries.add(card)
        return column(entries, button(add_label, lambda: self.change(lambda: items.append(blank())), "add"))

    # --- cards -------------------------------------------------------------------

    def card(self, key, title, tag, open_by_default, *children):
        """A collapsible top-level card, remembering whether the user left it open."""
        card = Collapsible("section", self.section_open.get(key, open_by_default))
        card.head.addWidget(label(title, "card-title"))
        if tag:
            card.head.addWidget(label(tag, "tag"))
        card.head.addStretch(1)
        card.content.setContentsMargins(14, 0, 14, 14)
        card.content.setSpacing(10)
        for child in children:
            if child.property("kind") == "add":
                card.content.addWidget(child, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                card.content.addWidget(child)
        card.toggled.connect(lambda is_open: self.section_open.__setitem__(key, is_open))
        self.cards.append(card)
        return card

    def render_basics(self):
        basics = self.doc.model["basics"]
        if not isinstance(basics.get("location"), dict):
            basics["location"] = {}
        if not isinstance(basics.get("profiles"), list):
            basics["profiles"] = []
        location = basics["location"]
        return self.card(
            "basics", "Header", "basics", True,
            row(self.field(basics, "name", "Name", required=True),
                self.field(basics, "label", "Title", required=True),
                self.field(basics, "email", "Email", required=True)),
            row(self.field(basics, "phone", "Phone", required=True),
                self.field(location, "city", "City", required=True),
                self.field(location, "region", "Region / state")),
            self.field(basics, "url", "Website", placeholder="https://", hint="printed before the profile links"),
            self.more(
                row(self.field(location, "address", "Street address"),
                    self.field(location, "postalCode", "Postal code")),
                row(self.field(location, "countryCode", "Country code", placeholder="US"),
                    self.field(basics, "image", "Photo", placeholder="input/photo.png", hint="an image file in the resume folder"))),
            label("Profile links", hint="printed in this order"),
            self.entry_list(basics["profiles"], "profiles", lambda p: [
                row(self.field(p, "network", "Network", placeholder="LinkedIn"),
                    self.field(p, "username", "Username", hint="link text ends here"),
                    self.field(p, "url", "URL", required=True, placeholder="https://"),
                    stretch=[2, 2, 5]),
            ], add_label="+ Add profile link", blank=lambda: {"network": "", "url": ""}, pagebreak=False))

    def render_meta(self):
        """meta: details about the document itself, for JSON Resume tools."""
        meta = self.doc.top_level("meta", dict)
        return self.card(
            "meta", "Document info", "meta · printed at the foot of the last page", False,
            row(self.field(meta, "canonical", "Canonical URL", placeholder="https://", hint="where this resume.json is published"),
                self.field(meta, "version", "Version", placeholder="v1.0.0"),
                self.field(meta, "lastModified", "Last modified", placeholder="2026-10-06T12:00:00")))

    def render_order_card(self):
        doc = self.doc
        excluded = [section for section in SECTIONS if section not in doc.order]

        def moved(src, old, dst, new):
            if src is excluded and dst is excluded:
                return  # the left-out sections have no order of their own

            def mutate():
                dst.insert(new, src.pop(old))
                for section in doc.order:
                    doc.ensure_section_data(section)
            self.change(mutate)

        rows = []
        for sections, kind in [(doc.order, "chips"), (excluded, "chips-excluded")]:
            chips = SortableList(sections, "section-order", moved, flow=True, spacing=6)
            chips.setProperty("kind", kind)
            chips.layout().setContentsMargins(6, 6, 6, 6)
            chips.setMinimumHeight(44)
            for section in sections:
                chip = Chip()
                layout = QHBoxLayout(chip)
                layout.setContentsMargins(10, 5, 10, 5)
                layout.setSpacing(6)
                layout.addWidget(label("⠿", "handle"))
                layout.addWidget(QLabel(LABELS.get(section, section)))
                if sections is doc.order and section in doc.breaks:
                    mark = label("new page", "break-mark")
                    mark.setToolTip("Starts on a new page")
                    layout.addWidget(mark)
                chips.add(chip)
            rows.append(chips)

        card = QFrame()
        card.setProperty("kind", "section")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(label("Sections", "card-title"))
        layout.addWidget(label("Drag to reorder. Drag a section to the second row to leave it out of the resume (its content is kept)."))
        for chips in rows:
            layout.addWidget(chips)
        return card

    def render_section(self, key):
        """Every section gets a card, so any part of the schema can be filled
        in; ones left out of the resume start collapsed unless they hold
        something. The generator skips a section with no entries, so those
        are tagged too."""
        doc = self.doc
        included, has_data = doc.included(key), doc.has_data(key)
        tag = "not in resume" if not included else "empty · not printed" if key != "summary" and not has_data else None
        card = self.card(key, LABELS.get(key, key), tag, included or has_data, self.render_section_body(key))
        if key == "competencies":
            self.duplicate_tag = label("", "warning-tag")
            card.head.insertWidget(card.head.count() - 1, self.duplicate_tag)  # before the stretch
        if included:
            def set_break(on):
                (doc.breaks.add if on else doc.breaks.discard)(key)
            card.head.addWidget(self.page_toggle(key in doc.breaks, set_break))
        else:
            card.setProperty("excluded", True)
        return card

    def render_section_body(self, key):
        doc, field, lines_field, dates, more = self.doc, self.field, self.lines_field, self.dates, self.more
        if key == "summary":
            return field(doc.model["basics"], "summary", "basics.summary", multiline=True, required=doc.included(key))
        if key == "experience":
            return self.render_experience()
        if key == "early_career":
            return self.entry_list(doc.early, "early", lambda e: [
                row(field(e, "position", "Position", required=True),
                    field(e, "name", "Employer(s)", required=True)),
                dates(e, placeholder="YYYY", hint="printed as years"),
                field(e, "summary", "Summary", multiline=True, hint="printed after the dates"),
                more(
                    row(field(e, "location", "Location"),
                        field(e, "url", "Employer website", placeholder="https://", hint="makes the name a link")),
                    field(e, "description", "Employer description"),
                    lines_field(e, "highlights", "Highlights", hint="one per line, printed after the summary")),
            ], add_label="+ Add early career entry", blank=lambda: {"name": "", "position": "", "earlyCareer": True})
        if key == "volunteer":
            return self.entry_list(doc.list_for(key), "volunteer", lambda v: [
                row(field(v, "organization", "Organization", required=True),
                    field(v, "position", "Position", required=True)),
                dates(v, end_placeholder="Present"),
                field(v, "summary", "Summary", multiline=True, hint="printed above the highlights"),
                lines_field(v, "highlights", "Highlights", hint="one per line, printed as bullets"),
                more(field(v, "url", "Website", placeholder="https://", hint="makes the organization a link")),
            ], add_label="+ Add volunteer role", blank=lambda: {"organization": "", "position": ""})
        if key == "competencies":
            return self.entry_list(doc.list_for(key), "skills", lambda s: [
                row(field(s, "name", "Name", required=True, on_input=self.update_duplicates),
                    field(s, "level", "Level", placeholder="Advanced", hint="printed after the name")),
                lines_field(s, "keywords", "Keywords", hint="one per line, printed separated by ·", required=True, on_input=self.update_duplicates),
                self.duplicate_note(),
            ], add_label="+ Add competency", blank=lambda: {"name": "", "keywords": []})
        if key == "education":
            return self.entry_list(doc.list_for(key), "education", lambda e: [
                row(field(e, "studyType", "Degree type", placeholder="Bachelor of Science"),
                    field(e, "area", "Area", hint="printed as “type in area”")),
                row(field(e, "institution", "Institution", required=True),
                    field(e, "score", "Score", placeholder="3.8 GPA", hint="printed after the institution")),
                dates(e, placeholder="YYYY", hint="printed as years"),
                lines_field(e, "courses", "Courses", hint="one per line, printed under the entry"),
                more(field(e, "url", "Institution website", placeholder="https://", hint="makes the institution a link")),
            ], add_label="+ Add education", blank=lambda: {"institution": "", "studyType": ""})
        if key == "certifications":
            return self.entry_list(doc.list_for(key), "certificates", lambda c: [
                row(field(c, "name", "Name", required=True),
                    field(c, "issuer", "Issuer", hint="printed after the name")),
                more(
                    row(field(c, "date", "Date", date=True, hint="printed as the year"),
                        field(c, "url", "URL", placeholder="https://", hint="makes the name a link"))),
            ], add_label="+ Add certification", blank=lambda: {"name": ""})
        if key == "recognition":
            return self.entry_list(doc.list_for(key), "awards", lambda a: [
                field(a, "title", "Title", required=True),
                field(a, "summary", "Summary", multiline=True),
                more(
                    row(field(a, "date", "Date", date=True, placeholder="YYYY", hint="printed unless the title has the year"),
                        field(a, "awarder", "Awarder", hint="printed unless the title names it"))),
            ], add_label="+ Add entry", blank=lambda: {"title": ""})
        if key == "publications":
            return self.entry_list(doc.list_for(key), "publications", lambda pub: [
                row(field(pub, "name", "Title", required=True),
                    field(pub, "publisher", "Publisher", hint="printed after the title")),
                field(pub, "releaseDate", "Release date", date=True, hint="printed as the year"),
                field(pub, "summary", "Summary", multiline=True),
                more(field(pub, "url", "URL", placeholder="https://", hint="makes the title a link")),
            ], add_label="+ Add publication", blank=lambda: {"name": ""})
        if key == "projects":
            return self.entry_list(doc.list_for(key), "projects", lambda p: [
                field(p, "name", "Name", required=True),
                field(p, "description", "Description", multiline=True),
                lines_field(p, "highlights", "Highlights", hint="one per line, printed as bullets"),
                lines_field(p, "keywords", "Keywords", hint="one per line, printed as a Stack line"),
                more(
                    dates(p, end_placeholder="Present"),
                    row(field(p, "url", "URL", placeholder="https://", hint="makes the name a link"),
                        field(p, "entity", "Entity", placeholder="Company or organization"),
                        field(p, "type", "Type", placeholder="application")),
                    lines_field(p, "roles", "Your roles", hint="one per line, printed after the name")),
            ], add_label="+ Add project", blank=lambda: {"name": ""})
        if key == "languages":
            return self.entry_list(doc.list_for(key), "languages", lambda entry: [
                row(field(entry, "language", "Language", required=True),
                    field(entry, "fluency", "Fluency", placeholder="Native speaker", hint="printed after the language")),
            ], add_label="+ Add language", blank=lambda: {"language": ""})
        if key == "interests":
            return self.entry_list(doc.list_for(key), "interests", lambda i: [
                field(i, "name", "Name", required=True),
                lines_field(i, "keywords", "Keywords", hint="one per line, printed separated by ·"),
            ], add_label="+ Add interest", blank=lambda: {"name": ""})
        if key == "references":
            return self.entry_list(doc.list_for(key), "references", lambda r: [
                field(r, "name", "Name", required=True),
                field(r, "reference", "Reference", multiline=True, required=True),
            ], add_label="+ Add reference", blank=lambda: {"name": "", "reference": ""})
        return label(f'Edit "{key}" in the raw {RESUME} tab.')

    def duplicate_note(self):
        """A competency card's line saying what it repeats (see update_duplicates)."""
        note = label("", "warning")
        note.setWordWrap(True)
        self.duplicate_notes.append(note)
        return note

    def update_duplicates(self):
        """Flags Core Competencies names and keywords that are repeated,
        within a card or across them: under each card that has one, and as a
        count on the section's title. Returns the count."""
        found = competency_duplicates(self.doc.list_for("competencies"))
        for note, messages in zip(self.duplicate_notes, found):
            note.setText("Duplicate: " + "; ".join(messages) + ".")
            note.setVisible(bool(messages))
        count = sum(len(messages) for messages in found)
        if self.duplicate_tag is not None:
            self.duplicate_tag.setText(f"{count} duplicate{'' if count == 1 else 's'}")
            self.duplicate_tag.setVisible(bool(count))
        return count

    # --- experience ----------------------------------------------------------------

    def render_experience(self):
        groups = self.doc.groups
        employers = SortableList(groups, "employers", self.move)
        for i, group in enumerate(groups):
            employers.add(self.render_employer(group, i))

        def add_employer():
            group = {"name": "", "location": "", "companyStack": "", "roles": [new_role()]}
            groups.insert(0, group)
            self.open_employers.add(id(group))
        return column(employers, button("+ Add employer", lambda: self.change(add_employer), "add"))

    def render_employer(self, group, index):
        groups, roles = self.doc.groups, group["roles"]
        card = Collapsible("employer", id(group) in self.open_employers)
        title = label("", "employer-title")
        title.setMinimumWidth(40)

        def update_title():
            count = f"{len(roles)} role{'' if len(roles) == 1 else 's'}"
            title.setText(" · ".join(filter(None, [group.get("name") or "(new employer)", group.get("location"), count])))

        def copy_to_roles(key):
            # JSON Resume keeps employer fields on each work[] entry; set them on all of the employer's roles.
            for role in roles:
                if group.get(key):
                    role[key] = group[key]
                else:
                    role.pop(key, None)
            self.commit()

        update_title()
        card.head.insertWidget(0, Handle(card))
        card.head.addWidget(title, 1)
        card.head.addWidget(self.item_tools(groups, index, pagebreak=self.entry_page_toggle(roles[0]) if roles else None))

        role_list = SortableList(roles, "roles", self.move, spacing=10)
        for i, role in enumerate(roles):
            role_list.add(self.render_role(role, i, group))
        card.content.setContentsMargins(12, 0, 12, 12)
        card.content.setSpacing(10)
        for child in [
            row(self.field(group, "name", "Employer", required=True, on_input=update_title),
                self.field(group, "location", "Location", on_input=update_title)),
            self.field(group, "companyStack", "Company stack", hint="printed once, after all roles"),
            self.more(
                self.field(group, "url", "Employer website", placeholder="https://", hint="makes the name a link", on_input=lambda: copy_to_roles("url")),
                self.field(group, "description", "Employer description", placeholder="Construction equipment manufacturer", hint="printed under the name",
                           on_input=lambda: copy_to_roles("description"))),
            role_list,
        ]:
            card.content.addWidget(child)
        card.content.addWidget(button("+ Add role", lambda: self.change(lambda: roles.append(new_role(group))), "add"), 0, Qt.AlignmentFlag.AlignLeft)

        def toggled(is_open):
            (self.open_employers.add if is_open else self.open_employers.discard)(id(group))
        card.toggled.connect(toggled)
        self.cards.append(card)
        return card

    def render_role(self, role, index, group):
        if not isinstance(role.get("highlights"), list):
            role["highlights"] = []
        highlights = role["highlights"]
        card = QFrame()
        card.setProperty("kind", "role")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(Handle(card))
        head.addWidget(label("Role", "role-title"))
        head.addStretch(1)
        # The first role's page break is the employer card's toggle.
        head.addWidget(self.item_tools(group["roles"], index, pagebreak=self.entry_page_toggle(role) if index else None))
        layout.addLayout(head)
        layout.addWidget(row(
            self.field(role, "position", "Position", required=True),
            self.field(role, "startDate", "Start", date=True),
            self.field(role, "endDate", "End", date=True, placeholder="Present")))
        layout.addWidget(self.field(role, "summary", "Summary", multiline=True, hint="printed above the highlights"))
        layout.addWidget(label("Highlights", hint="the role's bullet points; a role needs highlights or a summary"))

        duties = SortableList(highlights, "highlights", self.move, spacing=4)
        for i, text in enumerate(highlights):
            duties.add(self.render_highlight(highlights, i, text))
        layout.addWidget(duties)
        layout.addWidget(button("+ Add highlight", lambda: self.change(lambda: highlights.append("")), "add"), 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.field(role, "stack", "Stack", hint="printed under this role"))
        return card

    def render_highlight(self, highlights, index, text):
        duty = QWidget()
        layout = QHBoxLayout(duty)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        area = AutoTextEdit(str(text))
        self.win.proof(area, grammar=True)
        area.required, area.date = True, False

        def changed():
            highlights[index] = area.toPlainText()
            restyle(area, "invalid", False)
            self.commit()

        on_edit(area, changed)
        self.controls.append(area)
        grip = Handle(duty)
        grip.setContentsMargins(0, 7, 0, 0)
        layout.addWidget(grip, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(area, 1)
        layout.addWidget(button("✕", lambda: self.change(lambda: highlights.pop(index)), "danger", "Delete highlight"), 0, Qt.AlignmentFlag.AlignTop)
        return duty

    # --- render / validate / save -----------------------------------------------------

    def render(self):
        doc = self.doc
        if not doc:
            return
        self.controls, self.cards = [], []
        self.duplicate_notes, self.duplicate_tag = [], None
        self.last_field = None
        page = DragSurface()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(self.render_basics())
        layout.addWidget(self.render_order_card())
        for section in doc.order + [section for section in SECTIONS if section not in doc.order]:
            layout.addWidget(self.render_section(section))
        layout.addWidget(self.render_meta())
        layout.addStretch(1)
        self._show(page)
        self.update_duplicates()
        self.undo_button.setEnabled(bool(self.undo_stack))

    def _show(self, page):
        """Swaps in a newly built page, keeping the scroll position."""
        position = self.scroll.verticalScrollBar().value()
        old = self.scroll.takeWidget()
        if old is not None:
            # Not deleted on the spot: a button on the old page may be what
            # asked for the new one, and is still handling its click.
            old.hide()
            old.deleteLater()
        self.scroll.setWidget(page)
        # The new page gets its height over the next few layout passes, as
        # its text boxes wrap; scroll back as soon as it is tall enough.
        self._scroll_to = position
        QTimer.singleShot(300, lambda: setattr(self, "_scroll_to", None))

    def _restore_scroll(self, _minimum, maximum):
        if self._scroll_to is not None:
            self.scroll.verticalScrollBar().setValue(min(self._scroll_to, maximum))

    def validate(self):
        """The document's own problems (document.py), plus empty required
        fields and malformed dates, which are highlighted and have anything
        collapsed around them opened."""
        problems = self.doc.problems()
        bad_dates, any_invalid = 0, False
        for control in self.controls:
            value = control.toPlainText().strip()
            bad_date = bool(control.date and value and not valid_date(value))
            bad = bad_date or (control.required and not value)
            bad_dates += bad_date
            any_invalid = any_invalid or bad
            restyle(control, "invalid", bad)
            parent = control.parentWidget() if bad else None
            while parent is not None and parent is not self.scroll:
                if isinstance(parent, Collapsible):
                    parent.set_open(True)
                parent = parent.parentWidget()
        if bad_dates:
            problems.append(f"{bad_dates} date{' is' if bad_dates == 1 else 's are'} not YYYY, YYYY-MM, or YYYY-MM-DD.")
        if not problems and any_invalid:
            problems.append("Fill in the highlighted required fields.")
        return problems

    def save(self):
        """Saves resume.json and section_order.yaml; False if it couldn't."""
        if not self.doc:
            return False
        problems = self.validate()
        if problems:
            self.win.report(f"Not saved — {len(problems)} problem{'' if len(problems) == 1 else 's'}: {' '.join(problems)}", "error")
            return False
        changed = [name for name in (RESUME, ORDER) if self.win.is_dirty(name)]
        if not changed:
            self.win.report("No changes to save.")
            return True
        try:
            for name in changed:
                self.win.save_file(name)
        except (OSError, ValueError) as error:
            self.win.report(str(error), "error")
            return False
        duplicates = self.update_duplicates()
        warning = f" Core Competencies has {duplicates} duplicate{'' if duplicates == 1 else 's'}." if duplicates else ""
        self.win.report(f"Saved {' and '.join(f'input/{name}' for name in changed)}.{warning}", "ok")
        return True

    def set_all_open(self, is_open):
        for card in self.cards:
            card.set_open(is_open)

    def _focus_changed(self, _old, new):
        if isinstance(new, QTextEdit) and self.scroll.isAncestorOf(new):
            self.last_field = new

    def preview_phrases(self):
        """What to highlight in the PDF preview for the field being edited:
        the line the cursor is on, then shorter stretches of it, as the PDF
        may not print the line exactly as typed (a middle dot is set as a
        math symbol, a list is joined with dots, and so on)."""
        field = QApplication.focusWidget()
        if field not in self.controls or field.date:
            return []
        cursor = field.textCursor()
        line = cursor.block().text()
        before = len(line[:cursor.positionInBlock()].split())
        words = line.split()
        phrases = [line.strip(), max(re.split(r"[·\"'“”‘’]", line), key=len).strip()]
        for reach in (4, 2):
            phrases.append(" ".join(words[max(before - reach, 0):before + reach]))
        return list(dict.fromkeys(phrase for phrase in phrases if len(phrase) >= PREVIEW_PHRASE_MIN))

    def insert_char(self, char):
        """The · and – buttons insert at the cursor of the last focused field,
        since neither character is on most keyboards."""
        field = self.last_field
        if field is None or not isValid(field) or not self.scroll.isAncestorOf(field):
            self.win.report("Click into a field first, then insert.")
            return
        field.insertPlainText(char)
        field.setFocus()
