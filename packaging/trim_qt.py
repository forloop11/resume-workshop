#!/usr/bin/env python3
"""Removes the parts of a pip-installed PySide6 the editor never loads, to
shrink the AppImage (packaging/build-appimage.sh): the developer tools, Qt
Quick and QML, Qt WebEngine (a whole Chromium), and the Qt libraries for 3D,
charts, multimedia, and the like. What stays is what a widgets app that
shows a PDF needs.

    trim_qt.py <site-packages>/PySide6
"""
import shutil
import sys
from pathlib import Path

# Whole directories and tools, relative to PySide6/.
PATHS = """
examples glue include doc scripts support typesystems
assistant designer linguist lrelease lupdate qmlformat qmllint qmlls balsam balsamui qsb svgtoqml
Qt/qml Qt/metatypes Qt/modules
Qt/plugins/designer Qt/plugins/qmltooling Qt/plugins/qmllint Qt/plugins/qmlls Qt/plugins/sceneparsers
Qt/plugins/assetimporters Qt/plugins/renderers Qt/plugins/geometryloaders Qt/plugins/renderplugins
Qt/plugins/sqldrivers Qt/plugins/scxmldatamodel Qt/plugins/multimedia Qt/plugins/texttospeech
Qt/plugins/geoservices Qt/plugins/position Qt/plugins/sensors Qt/plugins/canbus Qt/plugins/webview
Qt/plugins/vectorimageformats Qt/plugins/wayland-graphics-integration-server
Qt/resources Qt/libexec Qt/translations/qtwebengine_locales
Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
""".split()
# Qt modules: their Python bindings (PySide6/Qt<name>.*) and libraries (Qt/lib/libQt6<name>.so*).
MODULES = """
3D Quick3D Charts Graphs DataVisualization Designer Help UiTools Bluetooth Nfc Sensors Serial Sql Test Scxml
StateMachine RemoteObjects SpatialAudio TextToSpeech Multimedia Location HttpServer WebSockets WebView
CanvasPainter ShaderTools Bodymovin Lottie VirtualKeyboard
WebEngine WebChannel Positioning Quick Qml Labs PdfQuick NetworkAuth WaylandCompositor WaylandEglCompositor FFmpegStub
""".split()
# Bundled FFmpeg, used only by QtMultimedia.
LIBRARIES = ["libavcodec", "libavformat", "libavutil", "libswresample", "libswscale"]


def main():
    pyside = Path(sys.argv[1])
    if not (pyside / "QtCore.abi3.so").exists():
        sys.exit(f"{pyside} is not a PySide6 package directory")
    doomed = [pyside / path for path in PATHS]
    for module in MODULES:
        doomed += pyside.glob(f"Qt{module}*")
        doomed += (pyside / "Qt" / "lib").glob(f"libQt6{module}*")
    doomed += pyside.glob("libpyside6qml*")  # PySide6's own helper for the QML bindings
    for library in LIBRARIES:
        doomed += (pyside / "Qt" / "lib").glob(f"{library}*")
    for path in doomed:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


if __name__ == "__main__":
    main()
