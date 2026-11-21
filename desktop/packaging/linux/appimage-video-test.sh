#!/bin/sh
# Checks video playback in an AppImage's window, in a Debian 12 container without FUSE under Xvfb,
# with a PulseAudio server: makes short clips with the presets' codecs (ffmpeg on PATH, or
# REFRAME_FFMPEG), then appimage-video.py plays each one through WebKitWebDriver.
# Usage: desktop/packaging/linux/appimage-video-test.sh FILE.AppImage [yes|no] [gpu]
# The second argument is whether the shell must say that the window plays video (default yes).
# Without a GPU only VP9 must play; every other clip must end in the preview's frame compare.
# With `gpu` the container gets /dev/dri and Debian's libva with its VA-API drivers (Mesa, Intel
# iHD), and H.264, HEVC and the AV1 of this machine's VA-API encoder must play too.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
appimage=$(realpath "${1:?usage: appimage-video-test.sh FILE.AppImage [yes|no] [gpu]}")
expect=${2:-yes}
gpu=${3:-}
ffmpeg=${REFRAME_FFMPEG:-ffmpeg}
clips=$(mktemp -d)
trap 'rm -rf "$clips"' EXIT

clip() {
    name=$1
    shift
    "$ffmpeg" -hide_banner -loglevel error -y \
        -f lavfi -i testsrc2=size=320x180:rate=25:duration=3 \
        -f lavfi -i sine=frequency=440:duration=3 -pix_fmt yuv420p "$@" "$clips/$name"
}
vp9="-c:v libvpx-vp9 -b:v 300k"
x265="-c:v libx265 -x265-params log-level=error"
svtav1="-c:v libsvtav1 -svtav1-params log-level=0"
clip h264-aac.mp4 -c:v libx264 -c:a aac
clip h264-aac.mkv -c:v libx264 -c:a aac
clip hevc-aac.mkv $x265 -c:a aac
clip hevc-aac.mp4 $x265 -tag:v hvc1 -c:a aac
clip hevc-10bit-aac.mkv $x265 -pix_fmt yuv420p10le -c:a aac
clip av1-opus.mkv $svtav1 -c:a libopus
clip av1-opus.mp4 $svtav1 -c:a libopus
clip av1-opus.webm $svtav1 -c:a libopus
clip av1-10bit-opus.mkv $svtav1 -pix_fmt yuv420p10le -c:a libopus
clip vp9-opus.webm $vp9 -c:a libopus
clip vp9-opus.mkv $vp9 -c:a libopus
clip vp9-opus.mp4 $vp9 -c:a libopus
clip vp9-flac.mkv $vp9 -c:a flac
clip vp9-mp3.mkv $vp9 -c:a libmp3lame
clip vp9-aac.mkv $vp9 -c:a aac
clip vp9-ac3.mkv $vp9 -c:a ac3
clip vp9-eac3.mkv $vp9 -c:a eac3
clip vp9.mkv $vp9 -an

must_play=vp9
device=
va_packages=
if [ "$gpu" = gpu ]; then
    must_play=vp9,h264,hevc
    device=--device=/dev/dri
    va_packages="libva2 libva-drm2 mesa-va-drivers intel-media-va-driver vainfo"
    # GStreamer 1.20's AV1 decoder base fails on the hidden frames that software encoders write
    # (av1-*: frame compare); a hardware encoder's AV1 has none and must play.
    if "$ffmpeg" -hide_banner -loglevel error -y -vaapi_device /dev/dri/renderD128 \
        -f lavfi -i testsrc2=size=320x180:rate=25:duration=3 -f lavfi -i sine=frequency=440:duration=3 \
        -vf format=nv12,hwupload -c:v av1_vaapi -c:a libopus "$clips/av1hw-opus.mkv" 2> /dev/null; then
        must_play=$must_play,av1hw
    else
        rm -f "$clips/av1hw-opus.mkv"
        echo "-- no AV1 VA-API encoder here: no hardware AV1 clip"
    fi
fi

docker run --rm $device \
    -v "$appimage:/app/Reframe.AppImage:ro" \
    -v "$here:/tests:ro" \
    -v "$clips:/clips:ro" \
    -e EXPECT="$expect" \
    -e MUST_PLAY="$must_play" \
    -e VA_PACKAGES="$va_packages" \
    debian:12 sh -c '
        set -e
        apt-get update -qq
        # The libraries that an AppImage leaves to the host system (as appimage-test.sh), the
        # WebDriver, a sound server and, with a GPU, the system libva and its drivers.
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            xvfb dbus python3 webkit2gtk-driver pulseaudio procps ca-certificates \
            libdrm2 libegl1 libexpat1 libfontconfig1 libfreetype6 libfribidi0 libgbm1 libgl1 libgles2 \
            libharfbuzz0b libwayland-client0 libx11-6 libx11-xcb1 libxcb1 $VA_PACKAGES > /dev/null 2>&1
        if [ -n "$VA_PACKAGES" ]; then
            vainfo --display drm 2>&1 | grep -E "Driver version|VLD" | sed "s/^ */-- vainfo: /"
        fi
        export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/run APPIMAGE_EXTRACT_AND_RUN=1
        mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
        export REFRAME_DATA_DIR=$HOME/data REFRAME_CONFIG_DIR=$HOME/config REFRAME_CACHE_DIR=$HOME/cache
        Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp > /dev/null 2>&1 &
        export DISPLAY=:99
        dbus-run-session -- sh -c "
            pulseaudio --daemonize --exit-idle-time=-1 > /dev/null 2>&1 || echo \"-- no sound server\"
            python3 /tests/appimage-video.py /app/Reframe.AppImage /clips --expect-player $EXPECT \
                --must-play $MUST_PLAY 2> /tmp/driver.log
            status=\$?
            grep -a -i -E \"crash|abort|signal|no element|missing\" /tmp/driver.log | sort | uniq -c | head -20
            ls \$HOME/.cache/org.reframe.desktop/ 2> /dev/null | sed \"s/^/-- registry: /\"
            exit \$status"'
