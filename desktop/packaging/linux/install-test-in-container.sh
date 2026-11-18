#!/bin/sh
# Installs the .deb or .rpm from /pkgs with the distro's package manager, checks the installed
# app, then removes it. Runs as root in a container of the distro, started by install-test.sh,
# with the test media at /media. Every check prints "ok: …"; the first failure ends the run.
# The package has no FFmpeg: the test installs the pinned build from FFMPEG_ARCHIVE (a mounted
# archive of it) or, without one, downloads it. With /dev/dri it also checks VAAPI.
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
        dpkg -L reframe > /tmp/files.txt
        ;;
    rpm)
        dnf install -y -q /pkgs/*.rpm > /tmp/install.log 2>&1 || { cat /tmp/install.log; fail "dnf install"; }
        ok "dnf install $(basename /pkgs/*.rpm)"
        dnf install -y -q desktop-file-utils jq xorg-x11-server-Xvfb dbus-daemon curl procps-ng > /dev/null
        rpm -q --qf '%{NAME} %{VERSION}-%{RELEASE}\n' reframe
        rpm -q --requires reframe | sed 's/^/  requires: /'
        rpm -q --recommends reframe | sed 's/^/  recommends: /'
        rpm -ql reframe > /tmp/files.txt
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
if grep -E '/(ffmpeg|ffprobe)(\.exe)?$|/tools/ffmpeg(/|$)|/libav(codec|format|util|filter|device)[.-]' /tmp/files.txt; then
    fail "the package contains FFmpeg"
fi
ok "the package contains no ffmpeg, ffprobe or FFmpeg library ($(wc -l < /tmp/files.txt) files)"
case $kind in
    deb) dpkg-query -W -f '${Depends} ${Recommends}\n' reframe | grep -q 'mkvtoolnix\|mediainfo' \
        && fail "the package still asks for MKVToolNix or MediaInfo" ;;
    rpm) { rpm -q --requires reframe; rpm -q --recommends reframe; } | grep -q 'mkvtoolnix\|mediainfo' \
        && fail "the package still asks for MKVToolNix or MediaInfo" ;;
esac
ok "no MKVToolNix or MediaInfo in the dependencies"
# The FFmpeg download checks the server's certificate against the system's CA store.
case $kind in
    deb) dpkg-query -W -f '${Depends}\n' reframe | grep -q 'ca-certificates' ;;
    rpm) rpm -q --requires reframe | grep -q 'ca-certificates' ;;
esac || fail "the package does not depend on ca-certificates"
ok "the package depends on ca-certificates"

app=/usr/lib/Reframe
libva=$app/tools/libva
[ "$(readlink /usr/bin/reframe)" = "$app/sidecar/reframe" ] || fail "/usr/bin/reframe is not the link to $app/sidecar/reframe"
ok "/usr/bin/reframe -> $(readlink /usr/bin/reframe)"
for library in libva.so.2 libva-drm.so.2; do
    [ -f "$libva/$library" ] && [ ! -L "$libva/$library" ] || fail "no file $libva/$library"
done
[ -s "$libva/LICENSE-libva.txt" ] || fail "no $libva/LICENSE-libva.txt"
ok "the packaged libva: $(ls "$libva" | tr '\n' ' ')"
notices=$app/notices/THIRD_PARTY_NOTICES
[ -s "$notices" ] || fail "no $notices"
grep -q '^  source_tag: ' "$notices" || fail "no libva source link in the notices"
grep -q 'tools/ffmpeg.toml' "$notices" && fail "the notices name an FFmpeg pin"
ok "$notices ($(wc -c < "$notices") bytes): libva, no FFmpeg"

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
installed=$REFRAME_DATA_DIR/tools/ffmpeg

echo "-- reframe version: $(reframe version)"
reframe tools status --json > "$work/tools.json" || true
[ "$(jq -r .ffmpeg.status "$work/tools.json")" = missing ] \
    || fail "before an install ffmpeg is $(jq -c .ffmpeg "$work/tools.json")"
ok "before an install: ffmpeg missing"

if [ -n "${FFMPEG_ARCHIVE:-}" ]; then
    how="installed from the file $(basename "$FFMPEG_ARCHIVE")"
    reframe tools fetch --file "$FFMPEG_ARCHIVE" > "$work/fetch.log" 2>&1 \
        || { cat "$work/fetch.log"; fail "reframe tools fetch --file $FFMPEG_ARCHIVE"; }
else
    how="downloaded"
    reframe tools fetch --build default > "$work/fetch.log" 2>&1 \
        || { cat "$work/fetch.log"; fail "reframe tools fetch"; }
fi
for library in libva.so.2 libva-drm.so.2; do
    cmp "$libva/$library" "$installed/lib/$library" || fail "$installed/lib/$library is not the packaged one"
done
ok "the default build $how into $installed, with the packaged libva in its lib/"
reframe tools status --json > "$work/tools.json" || fail "reframe tools status"
for tool in ffmpeg ffprobe; do
    origin=$(jq -r ".$tool.origin" "$work/tools.json")
    path=$(jq -r ".$tool.path" "$work/tools.json")
    [ "$origin" = bundled ] && [ "$path" = "$installed/bin/$tool" ] || fail "$tool is $origin at $path"
    ok "$tool: bundled at $path ($(jq -r ".$tool.version" "$work/tools.json"))"
done
[ "$(jq -c keys "$work/tools.json")" = '["ffmpeg","ffprobe"]' ] \
    || fail "reframe tools status lists $(jq -c keys "$work/tools.json")"

if [ -c /dev/dri/renderD128 ]; then
    case $kind in
        deb) apt-get install -y -qq --no-install-recommends mesa-va-drivers > /dev/null ;;
        rpm) dnf install -y -q mesa-va-drivers > /dev/null ;;
    esac
    # The build loads libva at run time: the loader's log names the file it took.
    LD_DEBUG=libs "$installed/bin/ffmpeg" -hide_banner -v verbose \
        -init_hw_device vaapi=va:/dev/dri/renderD128 -f lavfi -i testsrc=size=256x144:rate=1 \
        -frames:v 1 -f null - > "$work/vaapi.log" 2>&1 \
        || { grep -v '^ *[0-9]*:' "$work/vaapi.log" | tail -20; fail "ffmpeg -init_hw_device vaapi"; }
    loaded=$(sed -n 's/.*calling init: \(.*\/libva\.so\.2\)$/\1/p' "$work/vaapi.log" | head -n 1)
    [ -n "$loaded" ] && loaded=$(realpath -m "$loaded")
    [ "$loaded" = "$installed/lib/libva.so.2" ] || fail "FFmpeg loaded ${loaded:-no libva.so.2}"
    version=$(sed -n 's/.*libva: VA-API version \([0-9.]*\).*/\1/p' "$work/vaapi.log" | head -n 1)
    driver=$(sed -n 's/.*VAAPI driver: \(.*\)\.$/\1/p' "$work/vaapi.log" | head -n 1)
    ok "FFmpeg opens /dev/dri/renderD128 with $loaded (VA-API $version; $driver)"
    reframe encoders --json > "$work/encoders.json" || fail "reframe encoders"
    jq -r '.encoders[] | select(.id | endswith("_vaapi")) | "-- \(.id): \(.state)\(if .reason then " (\(.reason))" else "" end)"' "$work/encoders.json"
    available=$(jq -r '[.encoders[] | select((.id | endswith("_vaapi")) and .state == "available") | .id] | join(" ")' "$work/encoders.json")
    [ -n "$available" ] || fail "no VAAPI encoder is available"
    ok "VAAPI encoders available: $available"
else
    echo "-- no /dev/dri/renderD128: VAAPI not checked"
fi

mkdir "$work/out"
reframe encode -p very-fast-1080p30 -o "$work/out/multitrack.mkv" /media/multitrack.mkv > "$work/encode.log" 2>&1 \
    || { tail -20 "$work/encode.log"; fail "reframe encode"; }
[ -s "$work/out/multitrack.mkv" ] || fail "no encoded file"
"$installed/bin/ffprobe" -v error -show_entries format=format_name:stream=codec_name -of csv=p=0 "$work/out/multitrack.mkv" \
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
jq -e ".tools.ffmpeg.origin == \"bundled\" and .tools.ffmpeg.path == \"$installed/bin/ffmpeg\"" \
    "$work/system.json" > /dev/null || fail "the app's ffmpeg: $(jq -c .tools.ffmpeg "$work/system.json")"
ok "reframe-desktop under Xvfb: its sidecar $exe answers on port $port in mode $mode, ffmpeg the installed build"
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
