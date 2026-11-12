#!/bin/sh
# Checks an AppImage on this machine without a window on its displays: in a private virtual KWin
# session (with FUSE: the AppImage mounts itself), then in a Debian 12 container without FUSE
# (--appimage-extract-and-run) under Xvfb.
# Usage: desktop/packaging/linux/appimage-test.sh FILE.AppImage [SOCKET]
set -eu

here=$(cd "$(dirname "$0")" && pwd)
appimage=$(realpath "${1:?usage: appimage-test.sh FILE.AppImage [SOCKET]}")
socket=${2:-reframe-appimage}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "== $(basename "$appimage") in a virtual KWin session ($socket)"
cat > "$work/session.sh" << EOF
#!/bin/sh
sh "$here/appimage-check.sh" "$appimage" "$work/kwin" "$work/screenshot.png" > "$work/kwin.log" 2>&1
echo \$? > "$work/kwin.status"
EOF
chmod +x "$work/session.sh"
env -u DISPLAY -u WAYLAND_DISPLAY dbus-run-session -- kwin_wayland --virtual --no-lockscreen \
    --socket "$socket" --width 1600 --height 1000 --exit-with-session "$work/session.sh" \
    > "$work/kwin-compositor.log" 2>&1 || true
cat "$work/kwin.log"
[ "$(cat "$work/kwin.status" 2> /dev/null)" = 0 ] || { echo "FAIL: the virtual session check" >&2; exit 1; }
if [ -s "$work/screenshot.png" ] && [ -n "${SCREENSHOT_OUT:-}" ]; then
    cp "$work/screenshot.png" "$SCREENSHOT_OUT"
fi

echo "== $(basename "$appimage") in debian:12 without FUSE"
docker run --rm \
    -v "$appimage:/app/Reframe.AppImage:ro" \
    -v "$here:/tests:ro" \
    debian:12 sh -c '
        set -e
        apt-get update -qq
        # The libraries that an AppImage leaves to the host system (the AppImage exclude list):
        # every desktop has them, a bare container does not.
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            xvfb dbus jq curl procps ca-certificates \
            libdrm2 libegl1 libexpat1 libfontconfig1 libfreetype6 libfribidi0 libgbm1 libgl1 \
            libharfbuzz0b libwayland-client0 libx11-6 libx11-xcb1 libxcb1 > /dev/null 2>&1
        [ ! -e /dev/fuse ] && echo "-- /dev/fuse: none"
        Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp > /dev/null 2>&1 &
        DISPLAY=:99 dbus-run-session -- sh /tests/appimage-check.sh /app/Reframe.AppImage /tmp/check "" \
            -- --appimage-extract-and-run'
