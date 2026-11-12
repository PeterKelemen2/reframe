#!/bin/sh
# Installs the packages that build.sh wrote into OUT_DIR in a container of each distro and runs
# install-test-in-container.sh there: the .deb in Ubuntu 22.04 and Debian 12, the .rpm in Fedora.
# Usage: desktop/packaging/linux/install-test.sh OUT_DIR [IMAGE…]
# The test media come from testdata/media (scripts/make-testdata.py).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
out=$(realpath "${1:?usage: install-test.sh OUT_DIR [IMAGE…]}")
shift
[ $# -gt 0 ] || set -- ubuntu:22.04 debian:12 fedora:45
[ -s "$repo/testdata/media/multitrack.mkv" ] || { echo "no testdata/media/multitrack.mkv" >&2; exit 1; }

status=0
for image in "$@"; do
    case $image in
        fedora* | *rhel* | *rocky* | *alma*) kind=rpm ;;
        *) kind=deb ;;
    esac
    pkgs=$(mktemp -d)
    cp "$out"/*."$kind" "$pkgs"/
    docker run --rm \
        -v "$pkgs:/pkgs:ro" \
        -v "$repo/testdata/media:/media:ro" \
        -v "$here:/tests:ro" \
        "$image" sh /tests/install-test-in-container.sh "$kind" || status=1
    rm -rf "$pkgs"
done
exit $status
