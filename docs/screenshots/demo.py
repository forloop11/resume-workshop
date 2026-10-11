#!/usr/bin/env python3
"""Records docs/screenshots/demo.gif, the animated tour of the editor at the
top of the README, without a display:

    python3 docs/screenshots/demo.py

It drives the real editor through its main features -- typing with the live
preview, bold, testing a link, the ATS check, the color themes, the section
cards, and a build -- taking a picture of the window at each step, with a
caption under it.

Run it from a checkout with the editor's packages (requirements.txt),
pdflatex, and Pillow (`pip install pillow`), which only this script needs.
It works on a copy of this checkout's resume in a temporary folder, so it
changes no files but the GIF. The link test asks the resume's own portfolio
site for a page; offline, that step just shows the buttons.
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "demo.gif"
WIDTH, HEIGHT = 1500, 1000  # the window
SCALE = 0.64  # the GIF is the window at this size, to keep the file small
CAPTION_HEIGHT = 46
JOB = """Senior Machine Learning Engineer

Build and deploy machine learning models for predictive maintenance and anomaly detection on IoT telemetry.
- Python, PyTorch and SQL; AWS (SageMaker) and Snowflake
- MLOps: CI/CD, model governance and drift detection
- Kubernetes and Terraform are a plus
"""

scratch = tempfile.TemporaryDirectory(prefix="resume-workshop-demo-")
os.environ.update(QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=f"{scratch.name}/config", XDG_DATA_HOME=f"{scratch.name}/data")
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "editor"))
sys.argv = [sys.argv[0]]

import project  # noqa: E402

FOLDER = Path(scratch.name) / "resume"
project.create(FOLDER)
for name in ("resume.json", "section_order.yaml", "geometry.yaml", "format.tex"):
    shutil.copy(ROOT / "input" / name, FOLDER / "input" / name)
shutil.copy(ROOT / "etc" / "dictionary.txt", FOLDER / "etc" / "dictionary.txt")
os.environ["RESUME_WORKSHOP_ROOT"] = str(FOLDER)

import main  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PySide6.QtCore import QBuffer, QEventLoop, QPoint, QTimer  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

frames = []  # (picture, how long it shows, in ms)


def pause(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(until, seconds=20):
    """Lets the editor run until until() is true, or the time is up."""
    for _ in range(seconds * 20):
        if until():
            return True
        pause(50)
    return False


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def frame(window, caption, ms):
    """Takes a picture of the window, captioned, to show for `ms`."""
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.ReadWrite)
    window.grab().save(buffer, "PNG")
    shot = Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGB")
    shot = shot.resize((round(WIDTH * SCALE), round(HEIGHT * SCALE)), Image.LANCZOS)
    picture = Image.new("RGB", (shot.width, shot.height + CAPTION_HEIGHT), "#191a21")
    picture.paste(shot, (0, 0))
    draw = ImageDraw.Draw(picture)
    letters = font(19)
    draw.text(((shot.width - draw.textlength(caption, font=letters)) / 2, shot.height + 11), caption, font=letters, fill="#f8f8f2")
    frames.append((picture, ms))


def field(window, starts_with):
    return next(control for control in window.blocks.controls if control.toPlainText().startswith(starts_with))


def show(window, control):
    """Scrolls a field into view, and puts the cursor in it."""
    window.blocks.scroll.ensureWidgetVisible(control, 0, 180)
    control.setFocus()
    window.blocks.last_field = control
    pause(350)


def record():
    main.application()
    window = main.Workshop(main.startup_resume())
    window.resize(WIDTH, HEIGHT)
    window.show()
    blocks, live = window.blocks, window.live
    wait(lambda: live.shown is not None)
    pause(500)
    frame(window, "Resume Workshop: edit a JSON Resume in cards, with the PDF beside it", 2800)

    # Typing, with the live preview following.
    caption = "Live preview: the PDF rebuilds as you type, and marks the field you're in"
    title = field(window, "Senior Data Scientist")
    show(window, title)
    frame(window, caption, 1200)
    builds = live.builds
    for letter in " · AI":
        cursor = title.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(letter)
        pause(60)
        frame(window, caption, 170)
    wait(lambda: live.builds > builds)
    pause(500)
    frame(window, caption, 2600)

    # Bold.
    caption = "Bold the words that matter: select them and press B"
    summary = field(window, "Built the labor time model")
    show(window, summary)
    start = summary.toPlainText().index("$4M annually")
    cursor = summary.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + len("$4M annually"), QTextCursor.MoveMode.KeepAnchor)
    summary.setTextCursor(cursor)
    pause(200)
    frame(window, caption, 1500)
    builds = live.builds
    blocks.toggle_bold()
    cursor.clearSelection()
    summary.setTextCursor(cursor)
    wait(lambda: live.builds > builds)
    pause(500)
    frame(window, caption, 2600)

    # Links.
    caption = "Test and open the resume's links from the editor"
    portfolio = field(window, "https://portfolio")
    show(window, portfolio)
    frame(window, caption, 1500)
    test = [button for button in portfolio.parent().findChildren(QPushButton) if button.text() == "Test"][0]
    test.click()
    wait(lambda: test.text() != "…" and test.text() != "Test", 20)
    pause(200)
    frame(window, caption, 2600)

    # The ATS check.
    window.report("")
    window.ats_button.click()
    wait(lambda: window.ats.width() == window.ats.WIDTH)
    pause(300)
    frame(window, "ATS check: how an applicant tracking system is likely to read the resume", 3000)
    window.ats.job.setPlainText(JOB)
    pause(300)
    frame(window, "Paste a job description to see which of its terms the resume has", 3200)
    window.ats_button.click()
    wait(lambda: not window.ats.isVisible())
    pause(300)

    # The section cards.
    sections = next(label for label in blocks.findChildren(main.QLabel) if label.text() == "Sections")
    blocks.scroll.verticalScrollBar().setValue(sections.mapTo(blocks.scroll.widget(), QPoint(0, 0)).y() - 30)
    pause(400)
    frame(window, "Drag sections to reorder them; each has its own card, heading, and page break", 3000)

    # The color themes.
    for name in ("Nord", "Gruvbox Dark", "Solarized Dark", "Solarized Light", "Light", "Dracula"):
        window.set_theme(name)
        pause(500)
        frame(window, f"Six color themes: {name}", 1100)

    # A build.
    blocks.scroll.verticalScrollBar().setValue(0)
    window.save_and_build()
    built = wait(lambda: window.process is None and window.status.text().startswith(("Built", "The build failed")), 60)
    pause(500)
    if built and window.status.text().startswith("Built"):
        frame(window, "Build: the PDF, a plain-text resume, and a Reactive Resume export", 3200)

    # A GIF has 256 colors a picture; this choice of them keeps the themes' accents true.
    pictures = [picture.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) for picture, _ in frames]
    pictures[0].save(OUTPUT, save_all=True, append_images=pictures[1:], duration=[ms for _, ms in frames], loop=0, optimize=True)
    print(f"Recorded {OUTPUT.name}: {len(frames)} pictures, {sum(ms for _, ms in frames) / 1000:.0f} s, {OUTPUT.stat().st_size / 1e6:.1f} MB.", flush=True)


if __name__ == "__main__":
    record()
    os._exit(0)
