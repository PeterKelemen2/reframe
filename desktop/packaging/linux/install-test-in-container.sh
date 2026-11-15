#!/bin/sh
# Installs the .deb or .rpm from /pkgs with the distro's package manager, checks the installed
# app, then removes it. Runs as root in a container of the distro, started by install-test.sh,
# with the test media at /media. Every check prints "ok: …"; the first failure ends the run.
# Usage: install-test-in-container.sh deb|rpm
set -eu

kind=$1
fail() {
    echo "FAIL: $*" >&2
    exit 1
}
ok() { echo "ok: $*"; }

. /etc/os-release
echo "== $PRETTY_NAME, $kind"

case $kind in
    deb)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq /pkgs/*.deb > /tmp/install.log 2>&1 || { cat /tmp/install.log; fail "apt-get install"; }
        ok "apt-get install $(basename /pkgs/*.deb)"
        apt-get install -y -qq --no-install-recommends desktop-file-utils jq xvfb dbus curl procps > /dev/null
        dpkg-query -W -f '${Package} ${Version}: Depends ${Depends}; Recommends ${Recommends}\n' reframe
        ;;
    rpm)
        dnf install -y -q /pkgs/*.rpm > /tmp/install.log 2>&1 || { cat /tmp/install.log; fail "dnf install"; }
        ok "dnf install $(basename /pkgs/*.rpm)"
        dnf install -y -q desktop-file-utils jq xorg-x11-server-Xvfb dbus-daemon curl procps-ng > /dev/null
        rpm -q --qf '%{NAME} %{VERSION}-%{RELEASE}\n' reframe
        rpm -q --requires reframe | sed 's/^/  requires: /'
        rpm -q --recommends reframe | sed 's/^/  recommends: /'
        ;;
    *) fail "usage: $0 deb|rpm" ;;
esac

# Other packages may bring the distro's libav* (WebKitGTK's GStreamer plugins): only the ffmpeg
# program itself must not come with Reframe.
for package in ffmpeg ffmpeg-free; do
    case $kind in
        deb) [ "$(dpkg-query -W -f '${Status}' "$package" 2> /dev/null)" = "install ok installed" ] \
            && fail "the distro's $package came with it" ;;
        rpm) rpm -q "$package" > /dev/null 2>&1 && fail "the distro's $package came with it" ;;
    esac
done
case $kind in
    deb) dpkg-query -W -f '${Depends}\n' reframe | grep -q 'ffmpeg\|libav' && fail "Depends names FFmpeg" ;;
    rpm) rpm -q --requires reframe | grep -q 'ffmpeg\|libav' && fail "Requires names FFmpeg" ;;
esac
ok "no ffmpeg package installed, no FFmpeg in the dependencies"
case $kind in
    deb) dpkg-query -W -f '${Depends} ${Recommends}\n' reframe | grep -q 'mkvtoolnix\|mediainfo' \
        && fail "the package still asks for MKVToolNix or MediaInfo" ;;
    rpm) { rpm -q --requires reframe; rpm -q --recommends reframe; } | grep -q 'mkvtoolnix\|mediainfo' \
        && fail "the package still asks for MKVToolNix or MediaInfo" ;;
esac
ok "no MKVToolNix or MediaInfo in the dependencies"

app=/usr/lib/Reframe
[ "$(readlink /usr/bin/reframe)" = "$app/sidecar/reframe" ] || fail "/usr/bin/reframe is not the link to $app/sidecar/reframe"
ok "/usr/bin/reframe -> $(readlink /usr/bin/reframe)"
[ -s "$app/notices/THIRD_PARTY_NOTICES" ] || fail "no $app/notices/THIRD_PARTY_NOTICES"
grep -q 'source_commit: ' "$app/notices/THIRD_PARTY_NOTICES" || fail "no FFmpeg source link in the notices"
ok "$app/notices/THIRD_PARTY_NOTICES ($(wc -c < "$app/notices/THIRD_PARTY_NOTICES") bytes)"

entry=/usr/share/applications/Reframe.desktop
desktop-file-validate "$entry" || fail "desktop-file-validate $entry"
grep -qx 'Exec=reframe-desktop %F' "$entry" || fail "Exec without %F"
grep -qx 'StartupWMClass=reframe-desktop' "$entry" || fail "StartupWMClass"
grep -q '^MimeType=video/x-matroska;' "$entry" || fail "MimeType"
ok "$entry valid: $(grep -E '^(Exec|MimeType)=' "$entry" | tr '\n' ' ')"

work=$(mktemp -d)
export HOME="$work/home" XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/share"
export XDG_CACHE_HOME="$work/cache" XDG_RUNTIME_DIR="$work/run"
export REFRAME_CONFIG_DIR="$work/reframe-config" REFRAME_DATA_DIR="$work/reframe-data"
export REFRAME_CACHE_DIR="$work/reframe-cache" REFRAME_POWER_DRY_RUN=1
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

echo "-- reframe version: $(reframe version)"
reframe tools status --json > "$work/tools.json" || fail "reframe tools status"
for tool in ffmpeg ffprobe; do
    origin=$(jq -r ".$tool.origin" "$work/tools.json")
    path=$(jq -r ".$tool.path" "$work/tools.json")
    [ "$origin" = bundled ] && [ "$path" = "$app/tools/ffmpeg/bin/$tool" ] \
        || fail "$tool is $origin at $path"
    ok "$tool: bundled at $path ($(jq -r ".$tool.version" "$work/tools.json"))"
done
[ "$(jq -c keys "$work/tools.json")" = '["ffmpeg","ffprobe"]' ] \
    || fail "reframe tools status lists $(jq -c keys "$work/tools.json")"

mkdir "$work/out"
reframe encode -p very-fast-1080p30 -o "$work/out/multitrack.mkv" /media/multitrack.mkv > "$work/encode.log" 2>&1 \
    || { tail -20 "$work/encode.log"; fail "reframe encode"; }
[ -s "$work/out/multitrack.mkv" ] || fail "no encoded file"
"$app/tools/ffmpeg/bin/ffprobe" -v error -show_entries format=format_name:stream=codec_name -of csv=p=0 "$work/out/multitrack.mkv" \
    | tr '\n' ' ' > "$work/streams"
ok "reframe encode: $(wc -c < "$work/out/multitrack.mkv") bytes, streams $(cat "$work/streams")"
# The CLI's server stays up until it is idle; the app below must start its own.
pid=$(jq -r .pid "$REFRAME_DATA_DIR/server.json" 2> /dev/null || true)
if [ -n "$pid" ]; then
    kill "$pid"
    while kill -0 "$pid" 2> /dev/null; do sleep 0.2; done
fi
rm -f "$REFRAME_DATA_DIR/server.json"

Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp > "$work/xvfb.log" 2>&1 &
xvfb=$!
DISPLAY=:99 dbus-run-session -- reframe-desktop > "$work/app.log" 2>&1 &
i=0
until [ -s "$REFRAME_DATA_DIR/server.json" ]; do
    i=$((i + 1))
    [ $i -le 300 ] || { cat "$work/app.log"; cat "$REFRAME_DATA_DIR"/logs/sidecar.log 2> /dev/null; fail "no server.json after 60 s"; }
    sleep 0.2
done
port=$(jq -r .port "$REFRAME_DATA_DIR/server.json")
token=$(jq -r .token "$REFRAME_DATA_DIR/server.json")
curl -fsS -H "Authorization: Bearer $token" "http://127.0.0.1:$port/api/system" > "$work/system.json" \
    || fail "GET /api/system"
mode=$(jq -r .mode "$work/system.json")
exe=$(readlink "/proc/$(jq -r .pid "$REFRAME_DATA_DIR/server.json")/exe")
[ "$mode" = desktop ] && [ "$exe" = "$app/sidecar/reframe-server" ] || fail "the server is $exe in mode $mode"
jq -e ".tools.ffmpeg.origin == \"bundled\" and .tools.ffmpeg.path == \"$app/tools/ffmpeg/bin/ffmpeg\"" \
    "$work/system.json" > /dev/null || fail "the app's ffmpeg: $(jq -c .tools.ffmpeg "$work/system.json")"
ok "reframe-desktop under Xvfb: its sidecar $exe answers on port $port in mode $mode, ffmpeg bundled"
kill "$(pgrep -x reframe-desktop)"
i=0
while pgrep -x reframe-desktop > /dev/null || pgrep -f "$app/sidecar/reframe-server" > /dev/null; do
    i=$((i + 1))
    [ $i -le 100 ] || fail "the app or its sidecar outlived SIGTERM: $(pgrep -a -f reframe)"
    sleep 0.2
done
kill "$xvfb"
ok "SIGTERM to the app: the app and its sidecar ended"

case $kind in
    deb) apt-get remove -y -qq reframe > /dev/null ;;
    rpm) dnf remove -y -q reframe > /dev/null 2>&1 ;;
esac
[ ! -e /usr/bin/reframe ] && [ ! -L /usr/bin/reframe ] || fail "/usr/bin/reframe is left"
[ ! -e "$app" ] || fail "left in $app: $(find "$app" | head)"
[ ! -e /usr/bin/reframe-desktop ] && [ ! -e "$entry" ] || fail "files left"
ok "removed: no /usr/bin/reframe, no $app, no desktop entry"
echo "== PASS: $PRETTY_NAME, $kind"
