"""Spelling and grammar checking for the editor's text fields.

Spelling is Enchant (pyenchant, with the system's en_US dictionary) plus the
resume folder's own words in etc/dictionary.txt, the same list cspell uses;
"Add to dictionary" appends to that file. Grammar is LanguageTool, run as a
local server by language_tool_python (which needs Java, and downloads
LanguageTool on first use), so no resume text leaves the machine. Either one
is simply off if its package isn't installed.

language_tool_python is an optional extra (requirements-grammar.txt): it is
GPL-licensed, so the packaged editor doesn't include it, and looks for it
in the user's own PACKAGES folder as well, where Edit > Install Grammar
Checker puts it (install_command()). An app store's build has no
grammar checking, since it may not fetch LanguageTool.

A Proofer underlines the problems in one text box -- spelling in red, grammar
in orange -- and adds the fixes to its right-click menu.
"""
import importlib
import importlib.util
import queue
import re
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor

import project
import themes
from distribution import STORE
from document import BOLD

WORDS = "etc/dictionary.txt"  # in a resume folder
# Where `pip install --target` puts the grammar checker for a packaged
# editor (the AppImage's --install-grammar does).
PACKAGES = project.data_folder() / "packages"
LANGUAGE = "en_US"
# Letters, with apostrophes inside ("don't", "Caterpillar's").
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# Links, email addresses, and file or domain names aren't prose.
NOT_PROSE = re.compile(r"://|@|\.\w{2,}(/|$)")
GRAMMAR_DELAY = 700  # ms after the last keystroke
MAX_SUGGESTIONS = 6


def utf16(text, index):
    """A Python string index -> the QTextDocument position within `text`
    (Qt counts UTF-16 units, Python counts code points)."""
    if text.isascii():
        return index
    return len(text[:index].encode("utf-16-le")) // 2


class Speller(QObject):
    changed = Signal()  # the word list changed; everything needs rechecking

    def __init__(self):
        super().__init__()
        self.error = None  # why spelling is off, if it is
        self.dictionary = None
        self.words = None  # the open resume folder's word list

    def open(self, root):
        """Starts afresh with the resume folder `root`'s word list."""
        self.words = root / WORDS
        self.error = self.dictionary = None
        try:
            import enchant

            # A broker of its own, so the last folder's words are forgotten.
            self._broker = enchant.Broker()
            self.dictionary = self._broker.request_dict(LANGUAGE)
        except ImportError:
            self.error = "pyenchant isn't installed (pip install -r requirements.txt)"
        except Exception as error:  # no Enchant library, or no en_US dictionary for it
            self.error = str(error)
        if self.dictionary and self.words.exists():
            for line in self.words.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    self.dictionary.add_to_session(line.strip())
        self.changed.emit()

    def misspelled(self, text):
        """(start, end) of each misspelled word in `text`. Acronyms, words
        joined to digits, and anything in a link are left alone."""
        if not self.dictionary:
            return []
        found = []
        for chunk in re.finditer(r"\S+", text):
            if NOT_PROSE.search(chunk.group()):
                continue
            for match in WORD.finditer(chunk.group()):
                word = match.group().replace("’", "'")
                start, end = chunk.start() + match.start(), chunk.start() + match.end()
                if len(word) < 2 or word.isupper() or text[start - 1:start].isdigit() or text[end:end + 1].isdigit():
                    continue
                if not self.dictionary.check(word) and not (word.endswith("'s") and self.dictionary.check(word[:-2])):
                    found.append((start, end))
        return found

    def suggest(self, word):
        return self.dictionary.suggest(word)[:MAX_SUGGESTIONS]

    def ignore(self, word):
        """Accepts `word` until the editor is closed."""
        self.dictionary.add_to_session(word)
        self.changed.emit()

    def add(self, word):
        """Adds `word` to etc/dictionary.txt."""
        text = self.words.read_text(encoding="utf-8") if self.words.exists() else ""
        self.words.write_text(text + ("" if not text or text.endswith("\n") else "\n") + word + "\n", encoding="utf-8")
        self.ignore(word)


# The grammar checker's packages, as pip is told them.
REQUIREMENTS = project.SOURCE / "requirements-grammar.txt"


def grammar_installed():
    """Whether language_tool_python is there to import, bundled or in PACKAGES."""
    if str(PACKAGES) not in sys.path:
        sys.path.append(str(PACKAGES))
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec("language_tool_python") is not None
    except (ImportError, ValueError):
        return False


def install_command():
    """The program and arguments that install the grammar checker in
    PACKAGES (Edit > Install Grammar Checker): this Python's own pip, as the
    AppImage's --install-grammar runs it. -s -E keep the user's other
    packages and settings out of it."""
    return sys.executable, ["-s", "-E", "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "--no-input",
                            "--target", str(PACKAGES), "-r", str(REQUIREMENTS)]


class Grammar(QObject):
    """Checks text with LanguageTool on a background thread, since starting
    its server takes several seconds and a check takes a moment."""

    checked = Signal(str)  # this text's problems() are ready
    failed = Signal(str)  # grammar checking is off, and why

    def __init__(self):
        super().__init__()
        self.results = {}  # text -> [(start, end, message, replacements, rule id)]
        self.ignored = set()  # (rule id, flagged text) the user dismissed
        self.off = STORE
        self.missing = False  # off because language_tool_python isn't installed
        self._requests = queue.Queue()
        self._thread = None

    def request(self, text):
        """Checks `text` unless it already has been; emits checked(text)."""
        if self.off or text in self.results or not text.strip():
            return
        self.results[text] = None  # in progress
        self._requests.put(text)
        if self._thread is None:
            # Not a daemon thread: Python then waits for it on the way out,
            # so the server it started is always stopped (see _run).
            self._thread = threading.Thread(target=self._run)
            self._thread.start()

    def problems(self, text):
        return [p for p in self.results.get(text) or [] if (p[4], text[p[0]:p[1]]) not in self.ignored]

    def ignore(self, text, problem):
        self.ignored.add((problem[4], text[problem[0]:problem[1]]))
        self.checked.emit(text)

    def _run(self):
        try:
            if str(PACKAGES) not in sys.path:
                sys.path.append(str(PACKAGES))
            import language_tool_python

            tool = language_tool_python.LanguageTool("en-US")
            tool.disabled_rules.add("MORFOLOGIK_RULE_EN_US")  # spelling is the Speller's job
        except ImportError:
            self.missing = True
            self._fail("its package, an optional extra, isn't installed" + ("." if STORE else ". Edit > Install Grammar Checker adds it."))
            return
        except Exception as error:  # no Java, or LanguageTool couldn't be downloaded or started
            self._fail(str(error))
            return
        try:
            # Until close(), or the editor exiting some other way.
            while not self.off:
                try:
                    text = self._requests.get(timeout=1)
                except queue.Empty:
                    if threading.main_thread().is_alive():
                        continue
                    break
                if text is None:
                    break
                try:
                    found = [(m.offset, m.offset + m.error_length, m.message, m.replacements[:MAX_SUGGESTIONS], m.rule_id) for m in tool.check(text)]
                except Exception as error:
                    self._fail(str(error))
                    break
                self.results[text] = found
                self.checked.emit(text)
        finally:
            tool.close()

    def _fail(self, reason):
        self.off = True
        self.failed.emit(reason)

    def running(self):
        """Whether the checker's thread is at work (or starting up)."""
        return self._thread is not None and self._thread.is_alive()

    def retry(self):
        """Starts afresh, once what kept it off has been put right (the
        package has been installed): the next request tries again."""
        if STORE or self.running():
            return
        importlib.invalidate_caches()  # the package may be minutes old
        self.off, self.missing = False, False
        self.results = {}
        self._requests = queue.Queue()
        self._thread = None

    def close(self):
        """Stops the LanguageTool server (once it has finished starting)."""
        self.off = True
        self._requests.put(None)


def _underline(color):
    text_format = QTextCharFormat()
    text_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
    text_format.setUnderlineColor(QColor(color))
    return text_format


class Proofer(QSyntaxHighlighter):
    """Underlines the spelling (and, given `grammar`, grammar) problems in a
    QTextEdit or QPlainTextEdit, and offers their fixes on right-click."""

    # In the current theme's colors, each time they are used.
    SPELLING = property(lambda self: _underline(themes.color("error")))
    GRAMMAR = property(lambda self: _underline(themes.color("warning")))

    def __init__(self, edit, speller=None, grammar=None):
        super().__init__(edit.document())
        self.edit, self.speller, self.grammar = edit, speller, grammar
        if speller and speller.dictionary:
            speller.changed.connect(self.rehighlight)
        else:
            self.speller = None
        if grammar:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(GRAMMAR_DELAY)
            self._timer.timeout.connect(lambda: grammar.request(edit.toPlainText()))
            edit.textChanged.connect(self._timer.start)
            grammar.checked.connect(self._checked)
            grammar.request(edit.toPlainText())
        if self.speller or grammar:
            edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            edit.customContextMenuRequested.connect(self._menu)

    def _checked(self, text):
        if text == self.edit.toPlainText():
            self.rehighlight()

    def prose(self, text):
        """The parts of a line to spell-check, as (offset, text)."""
        return [(0, text)]

    def problems(self, block):
        """A line's problems: (start, end, kind, detail), in positions within
        the line. For grammar, detail is (the whole text, its problem)."""
        text = block.text()
        found = []
        if self.speller:
            for offset, part in self.prose(text):
                found += [(utf16(text, offset + a), utf16(text, offset + b), "spelling", None) for a, b in self.speller.misspelled(part)]
        if self.grammar:
            whole = self.edit.toPlainText()
            start = sum(len(line) + 1 for line in whole.split("\n")[:block.blockNumber()])
            for problem in self.grammar.problems(whole):
                a, b = max(problem[0] - start, 0), min(problem[1] - start, len(text))
                if a < b:
                    found.append((utf16(text, a), utf16(text, b), "grammar", (whole, problem)))
        return found

    def highlightBlock(self, text):
        # **Words** marked bold look it, with their stars faint.
        bold, faint = QTextCharFormat(), QTextCharFormat()
        bold.setFontWeight(QFont.Weight.Bold)
        faint.setForeground(QColor(themes.color("placeholder")))
        for match in BOLD.finditer(text):
            start, inner, close, end = (utf16(text, at) for at in (match.start(), match.start(1), match.end(1), match.end()))
            self.setFormat(start, inner - start, faint)
            self.setFormat(inner, close - inner, bold)
            self.setFormat(close, end - close, faint)
        for start, end, kind, _ in self.problems(self.currentBlock()):
            underline = self.SPELLING if kind == "spelling" else self.GRAMMAR
            for at in range(start, end):  # added to what the character has, bold included
                merged = self.format(at)
                merged.merge(underline)
                self.setFormat(at, 1, merged)

    def _menu(self, point):
        edit = self.edit
        menu = edit.createStandardContextMenu()
        first = menu.actions()[0] if menu.actions() else None
        cursor = edit.cursorForPosition(point)
        block, at = cursor.block(), cursor.positionInBlock()

        def add(text, slot=None):
            action = QAction(text, menu)
            menu.insertAction(first, action)  # above the standard Undo/Copy/Paste items
            if slot:
                action.triggered.connect(lambda: slot())
            else:
                action.setEnabled(False)

        def replace(start, end, text):
            target = QTextCursor(block)
            target.setPosition(block.position() + start)
            target.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
            target.insertText(text)

        for start, end, kind, detail in self.problems(block):
            if not start <= at <= end:
                continue
            if kind == "spelling":
                word = block.text().encode("utf-16-le")[2 * start:2 * end].decode("utf-16-le").replace("’", "'")
                suggestions = self.speller.suggest(word)
                for suggestion in suggestions:
                    add(suggestion, lambda s=suggestion, a=start, b=end: replace(a, b, s))
                if not suggestions:
                    add("No spelling suggestions")
                add(f"Add “{word}” to dictionary", lambda w=word: self.speller.add(w))
                add("Ignore", lambda w=word: self.speller.ignore(w))
            else:
                whole, problem = detail
                add(problem[2])
                for suggestion in problem[3]:
                    add(f"→ {suggestion}", lambda s=suggestion, a=start, b=end: replace(a, b, s))
                add("Ignore", lambda w=whole, p=problem: self.grammar.ignore(w, p))
            if first is not None:
                menu.insertSeparator(first)
        menu.exec(edit.viewport().mapToGlobal(point))
        menu.deleteLater()
