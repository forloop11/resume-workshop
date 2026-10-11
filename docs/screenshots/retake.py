#!/usr/bin/env python3
"""Retakes the screenshots that come straight from the editor's widgets,
without a display:

    python3 docs/screenshots/retake.py

- editor-file-menu.png: the File menu.
- editor-themes.png: the window in each color theme.

The others show a window as arranged by hand, and are taken by hand. Run
this from a checkout with the editor's packages installed
(requirements.txt); it opens this checkout's resume and changes no files.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
settings = tempfile.TemporaryDirectory()  # so the theme chosen here isn't remembered
os.environ.update(QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
                  XDG_CONFIG_HOME=settings.name, RESUME_WORKSHOP_ROOT=str(ROOT))
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "editor"))
sys.argv = [sys.argv[0]]

import main  # noqa: E402
import themes  # noqa: E402
from PySide6.QtCore import QEventLoop, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402

COLUMNS, WIDTH, HEIGHT = 3, 750, 500  # the themes picture: each window at half size


def pause(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shots():
    main.application()
    window = main.Workshop(main.startup_resume())
    window.resize(1500, 1000)
    window.show()
    pause(4000)  # the PDF viewer loads, and the live preview builds

    menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "&File")
    menu.popup(window.mapToGlobal(window.rect().topLeft()))
    pause(300)
    # Drawn at twice its size, as on a high-resolution screen.
    shot = QPixmap(menu.size() * 2)
    shot.setDevicePixelRatio(2)
    menu.render(shot)
    shot.save(str(HERE / "editor-file-menu.png"))
    menu.hide()

    names = list(themes.THEMES)
    rows = -(-len(names) // COLUMNS)
    sheet = QPixmap(COLUMNS * WIDTH, rows * HEIGHT)
    sheet.fill(QColor("#000000"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for index, name in enumerate(names):
        window.set_theme(name)
        pause(2500)
        shot = window.grab().scaled(WIDTH, HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(QRect(index % COLUMNS * WIDTH, index // COLUMNS * HEIGHT, WIDTH, HEIGHT), shot)
    painter.end()
    sheet.save(str(HERE / "editor-themes.png"))
    print("Retook editor-file-menu.png and editor-themes.png.", flush=True)


if __name__ == "__main__":
    shots()
    os._exit(0)  # past Qt WebEngine's shutdown, which needs a display to go cleanly
