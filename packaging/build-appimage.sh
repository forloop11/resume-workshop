#!/usr/bin/env bash
# Builds dist/Resume_Workshop-x86_64.AppImage (`make appimage`): the desktop
# editor (editor/) with its own Python and the packages in requirements.txt,
# so it runs without a pip install.
#
# The AppImage holds the editor, and a template of the makefile and scripts
# that it copies into each new resume folder (File > New Resume) and builds
# resumes with itself. A resume lives in its own folder, outside the
# AppImage; building its PDF still uses that machine's pdflatex.
#
# The grammar checker (requirements-grammar.txt) is GPL-licensed, so it is
# left out, and the AppImage's --install-grammar adds it for one user (see
# packaging/AppRun). GRAMMAR=1 builds it in instead, which makes that
# AppImage as a whole a GPL work: not one to publish as this project's.
#
# Needs curl and an internet connection: it downloads a relocatable Python
# (github.com/niess/python-appimage), appimagetool, and the pip packages.
set -euo pipefail

PYTHON_VERSION=3.14
PYTHON_URL=https://github.com/niess/python-appimage/releases/download/python3.14/python3.14.8-cp314-cp314-manylinux_2_28_x86_64.AppImage
PYTHON_SHA256=0eb04163804dfbb47be7fefde4123713fe61e8679cee91193f1e8cca5781183a
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$ROOT/build/appimage
APPDIR=$BUILD/AppDir
NAME=Resume_Workshop-x86_64.AppImage
OUTPUT=$ROOT/dist/$NAME
# The version the editor says it is and compares with the latest release
# (editor/update.py): $VERSION if set, as the release workflow does from the
# tag, or else what git calls this commit (the last tag, plus how far past
# it). A leading v is dropped: the tag v1.2.3 is version 1.2.3.
VERSION=${VERSION:-$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || echo unknown)}
export VERSION=${VERSION#v}  # appimagetool notes it in the launcher too
# Where AppImage updaters look for a newer one: the .zsync file attached to
# this repository's latest GitHub release (.github/workflows/release.yml).
UPDATE_INFORMATION="gh-releases-zsync|forloop11|resume-workshop|latest|$NAME.zsync"
# Run the downloaded AppImages by unpacking them, so the build needs no FUSE.
export APPIMAGE_EXTRACT_AND_RUN=1

# Downloads $1 to $2 unless it's there already, and checks it against $3.
fetch() {
    [ -f "$2" ] || curl --fail --location --silent --show-error --output "$2" "$1"
    if ! echo "$3  $2" | sha256sum --check --quiet; then
        echo "Delete $2 and run this again to download it afresh." >&2
        exit 1
    fi
    chmod +x "$2"
}

mkdir -p "$BUILD" "$ROOT/dist"
fetch "$PYTHON_URL" "$BUILD/python.AppImage" "$PYTHON_SHA256"
fetch "$APPIMAGETOOL_URL" "$BUILD/appimagetool" "$APPIMAGETOOL_SHA256"

echo "Unpacking Python $PYTHON_VERSION..."
rm -rf "${BUILD:?}/AppDir" "${BUILD:?}/squashfs-root"
(cd "$BUILD" && ./python.AppImage --appimage-extract >/dev/null)
mv "$BUILD/squashfs-root" "$APPDIR"
# Drop the base image's own launcher; ours replaces it below.
find "$APPDIR" -maxdepth 1 \( -name AppRun -o -name .DirIcon -o -name '*.desktop' -o -name '*.png' \) -delete
find "$APPDIR/usr/share" -mindepth 1 -maxdepth 1 \( -name applications -o -name icons -o -name metainfo \) -exec rm -r {} +
mv "$APPDIR/opt/python$PYTHON_VERSION" "$APPDIR/opt/python"
PYTHON=$APPDIR/opt/python/bin/python$PYTHON_VERSION
ln -sf "python$PYTHON_VERSION" "$APPDIR/opt/python/bin/python3"

echo "Installing the packages in requirements.txt..."
REQUIREMENTS=(-r "$ROOT/requirements.txt")
if [ "${GRAMMAR:-}" = 1 ]; then
    REQUIREMENTS+=(-r "$ROOT/requirements-grammar.txt")
fi
"$PYTHON" -s -E -m pip install --quiet --no-cache-dir --no-warn-script-location --disable-pip-version-check "${REQUIREMENTS[@]}"

# PySide6 ships all of Qt; leave out the parts a widgets app with a web view
# never loads (developer tools, QML modules, 3D, multimedia, and so on).
SITE=$("$PYTHON" -s -E -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
"$PYTHON" -s -E "$ROOT/packaging/trim_qt.py" "$SITE/PySide6"

echo "Adding the editor..."
mkdir -p "$APPDIR/opt/resume-workshop"
cp -r "$ROOT/editor" "$APPDIR/opt/resume-workshop/editor"
cp "$ROOT/requirements-grammar.txt" "$APPDIR/opt/resume-workshop/"  # for --install-grammar
# What the editor knows about its packaging (editor/distribution.py).
echo "$VERSION" >"$APPDIR/opt/resume-workshop/editor/VERSION"
echo appimage >"$APPDIR/opt/resume-workshop/editor/CHANNEL"
# ...and the files File > New Resume copies into a new resume folder.
"$PYTHON" -s -E -B "$ROOT/editor/project.py" --template "$APPDIR/opt/resume-workshop"
find "$APPDIR/opt/resume-workshop" -depth -name __pycache__ -exec rm -r {} +
# The licenses of everything bundled, for Help > Third-Party Licenses.
"$PYTHON" -s -E -B "$ROOT/packaging/collect_licenses.py" "$ROOT/editor" "$APPDIR/opt/resume-workshop/THIRD-PARTY-LICENSES.txt"
# The image is read-only, so compile the editor now rather than at each start.
"$PYTHON" -s -E -m compileall -q "$APPDIR/opt/resume-workshop"
install -m 755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
install -m 644 "$ROOT/packaging/resume-workshop.desktop" "$APPDIR/resume-workshop.desktop"
install -m 644 "$ROOT/editor/icon.svg" "$APPDIR/resume-workshop.svg"
ln -s resume-workshop.svg "$APPDIR/.DirIcon"

echo "Packing version $VERSION..."
# Packed in a folder of its own, under its final name: appimagetool (with
# the zsyncmake it carries) writes the .zsync file a release has for those
# updaters to the current folder, with the AppImage's name inside it.
PACK=$BUILD/pack
rm -rf "${PACK:?}"
mkdir -p "$PACK"
if ! (cd "$PACK" && ARCH=x86_64 "$BUILD/appimagetool" --no-appstream --updateinformation "$UPDATE_INFORMATION" "$APPDIR" "$NAME") >"$BUILD/appimagetool.log" 2>&1; then
    cat "$BUILD/appimagetool.log" >&2
    exit 1
fi
mv "$PACK/$NAME" "$OUTPUT"
mv "$PACK/$NAME.zsync" "$OUTPUT.zsync"
echo "Built $OUTPUT ($(du -h "$OUTPUT" | cut -f1)) and $NAME.zsync."
