#!/bin/sh
# Starts an AppImage with private folders, waits until its sidecar publishes server.json, then
# checks GET /api/system: desktop mode and FFmpeg bundled from inside the AppImage. Stops the app
# and checks that none of its processes is left.
# Usage: appimage-check.sh APPIMAGE WORK_DIR [SCREENSHOT] [-- APPIMAGE_ARGS…]
# The caller provides the display (appimage-test.sh: a virtual KWin session, or Xvfb in a
# container).
set -eu

appimage=$1
work=$2
screenshot=${3:-}
if [ $# -ge 3 ]; then shift 3; else shift $#; fi
[ "${1:-}" = "--" ] && shift
fail() {
    echo "FAIL: $*" >&2
    exit 1
}
ok() { echo "ok: $*"; }

mkdir -p "$work"
export XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/share" XDG_CACHE_HOME="$work/cache"
export XDG_STATE_HOME="$work/state" REFRAME_CONFIG_DIR="$work/reframe-config"
export REFRAME_DATA_DIR="$work/reframe-data" REFRAME_CACHE_DIR="$work/reframe-cache"
export REFRAME_POWER_DRY_RUN=1

"$appimage" "$@" > "$work/app.log" 2>&1 &
started=$!

descendants() {
    for child in $(pgrep -P "$1"); do
        echo "$child"
        descendants "$child"
    done
}
# SIGTERM to reframe-desktop only: the runtime, the webview and the sidecar must end with it.
stop() {
    pids="$started $(descendants "$started")"
    app=$(for pid in $pids; do [ "$(cat "/proc/$pid/comm" 2> /dev/null)" = reframe-desktop ] && echo "$pid"; done; true)
    kill ${app:-$started} 2> /dev/null || true
    i=0
    for pid in $pids; do
        while kill -0 "$pid" 2> /dev/null; do
            i=$((i + 1))
            if [ $i -gt 100 ]; then
                left=$(tr '\0' ' ' < "/proc/$pid/cmdline")
                kill -9 $pids 2> /dev/null || true
                fail "process $pid ($left) outlived the app by 10 s"
            fi
            sleep 0.1
        done
    done
}

i=0
until [ -s "$REFRAME_DATA_DIR/server.json" ]; do
    i=$((i + 1))
    if [ $i -gt 300 ] || ! kill -0 "$started" 2> /dev/null; then
        cat "$work/app.log"
        cat "$REFRAME_DATA_DIR/logs/sidecar.log" 2> /dev/null || true
        stop
        fail "no server.json after 60 s"
    fi
    sleep 0.2
done
port=$(jq -r .port "$REFRAME_DATA_DIR/server.json")
token=$(jq -r .token "$REFRAME_DATA_DIR/server.json")
server=$(readlink "/proc/$(jq -r .pid "$REFRAME_DATA_DIR/server.json")/exe")
curl -fsS -H "Authorization: Bearer $token" "http://127.0.0.1:$port/api/system" > "$work/system.json" \
    || { stop; fail "GET /api/system"; }
mount=${server%/usr/lib/Reframe/sidecar/reframe-server}
[ "$mount" != "$server" ] || { stop; fail "the sidecar $server is not inside the AppImage"; }
jq -e ".mode == \"desktop\" and .tools.ffmpeg.origin == \"bundled\" and .tools.ffprobe.origin == \"bundled\"
    and .tools.ffmpeg.path == \"$mount/usr/lib/Reframe/tools/ffmpeg/bin/ffmpeg\"" "$work/system.json" > /dev/null \
    || { stop; fail "GET /api/system: $(jq -c '{mode, ffmpeg: .tools.ffmpeg}' "$work/system.json")"; }
ok "the sidecar $server answers on port $port: mode desktop, ffmpeg bundled at $(jq -r .tools.ffmpeg.path "$work/system.json") ($(jq -r .tools.ffmpeg.version "$work/system.json"))"
tr '\0' '\n' < "/proc/$(jq -r .pid "$REFRAME_DATA_DIR/server.json")/environ" | grep -E '^(LD_|APPDIR|APPIMAGE|PATH=)' | sed 's/^/-- sidecar env: /'
if [ -n "$screenshot" ]; then
    sleep 3
    spectacle -b -n -f -o "$screenshot" > /dev/null 2>&1 && ok "screenshot $screenshot" || echo "-- no screenshot"
fi
stop
ok "the app and every process it started ended"
