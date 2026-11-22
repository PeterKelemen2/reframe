#!/bin/sh
# Installs the packages that build.sh wrote into OUT_DIR in a container of each distro and runs
# install-test-in-container.sh there: the .deb in Ubuntu 22.04 and Debian 12, the .rpm in Fedora.
# Usage: desktop/packaging/linux/install-test.sh OUT_DIR [IMAGE…]
# The test media come from testdata/media (scripts/make-testdata.py). REFRAME_FFMPEG_ARCHIVE is
# the default build's archive (desktop/tests/smoke/ffmpeg-archive.py) for a file install; without
# it each container downloads the build. A host with /dev/dri passes it on (REFRAME_TEST_DRI=0
# does not), so that the containers check VAAPI.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
out=$(realpath "${1:?usage: install-test.sh OUT_DIR [IMAGE…]}")
shift
[ $# -gt 0 ] || set -- ubuntu:22.04 debian:12 fedora:45
[ -s "$repo/testdata/media/multitrack.mkv" ] || { echo "no testdata/media/multitrack.mkv" >&2; exit 1; }

archive_args=""
if [ -n "${REFRAME_FFMPEG_ARCHIVE:-}" ]; then
    archive=$(realpath "$REFRAME_FFMPEG_ARCHIVE")
    [ -f "$archive" ] || { echo "install-test.sh: no file $archive" >&2; exit 1; }
    archive_args="-v $archive:/archive/${archive##*/}:ro -e FFMPEG_ARCHIVE=/archive/${archive##*/}"
fi
dri_args=""
if [ -d /dev/dri ] && [ "${REFRAME_TEST_DRI:-1}" != 0 ]; then
    dri_args="--device /dev/dri"
fi

status=0
for image in "$@"; do
    case $image in
        fedora* | *rhel* | *rocky* | *alma*) kind=rpm ;;
        *) kind=deb ;;
    esac
    pkgs=$(mktemp -d)
    cp "$out"/*."$kind" "$pkgs"/
    # shellcheck disable=SC2086 # each holds options, without spaces in them
    docker run --rm $archive_args $dri_args \
        -v "$pkgs:/pkgs:ro" \
        -v "$repo/testdata/media:/media:ro" \
        -v "$here:/tests:ro" \
        "$image" sh /tests/install-test-in-container.sh "$kind" || status=1
    rm -rf "$pkgs"
done
exit $status
