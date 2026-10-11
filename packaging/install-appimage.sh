#!/usr/bin/env bash
# Installs the AppImage for the current user (`make install-appimage`), or
# removes it again with --uninstall (`make uninstall-appimage`):
#
#   ~/Applications/Resume_Workshop-x86_64.AppImage     (or under $APPIMAGE_DIR)
#   ~/.local/share/applications/resume-workshop.desktop
#   ~/.local/share/icons/hicolor/scalable/apps/resume-workshop.svg
#
# The launcher opens the resume folder the editor had open last, and this
# checkout the first time.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE=$ROOT/dist/Resume_Workshop-x86_64.AppImage
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
TARGET=${APPIMAGE_DIR:-$HOME/Applications}/Resume_Workshop-x86_64.AppImage
LAUNCHER=$DATA/applications/resume-workshop.desktop
ICON=$DATA/icons/hicolor/scalable/apps/resume-workshop.svg

refresh() {
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database "$DATA/applications" || true
    fi
    # If this icon folder has a cache (icon-theme.cache), the desktop looks
    # icons up there and doesn't see one added since: bring it up to date,
    # or failing that mark it stale so it is ignored.
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache --force --ignore-theme-index --quiet "$DATA/icons/hicolor" || true
    else
        touch "$DATA/icons/hicolor"
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f -- "$TARGET" "$LAUNCHER" "$ICON"
    refresh
    echo "Removed $TARGET and its launcher."
    exit 0
fi

if [ ! -f "$SOURCE" ]; then
    echo "$SOURCE is missing: run \`make appimage\` first." >&2
    exit 1
fi
case "$TARGET$ROOT" in
    *'"'* | *'`'* | *'$'* | *'\'*)
        echo "Can't write a launcher for a path containing \" \` \$ or \\." >&2
        exit 1
        ;;
esac

mkdir -p "$(dirname "$TARGET")" "$(dirname "$LAUNCHER")" "$(dirname "$ICON")"
install -m 755 "$SOURCE" "$TARGET"
install -m 644 "$ROOT/editor/icon.svg" "$ICON"
# The packaged launcher, with Exec pointing at the installed AppImage, and
# this checkout as the resume to open until another has been (quoted, as
# either path may contain spaces; a literal % in a launcher is written %%).
EXEC="env \"RESUME_WORKSHOP_DEFAULT=$ROOT\" \"$TARGET\""
while IFS= read -r line; do
    case "$line" in
        Exec=*) printf 'Exec=%s\n' "${EXEC//%/%%}" ;;
        *) printf '%s\n' "$line" ;;
    esac
done <"$ROOT/packaging/resume-workshop.desktop" >"$LAUNCHER"
refresh

echo "Installed $TARGET"
echo "Resume Workshop is in your applications menu; it opens the resume in $ROOT until you open another."
