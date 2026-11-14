#!/bin/sh
# Writes the AppImage's distro packages with their source packages and versions, read in the
# Linux build image before any package is built, for sources-manifest.py --appimage-libs.
# Usage: desktop/packaging/linux/appimage-libs.sh OUT_FILE
# REFRAME_BUILD_NAME names the image, as for build.sh (which then checks the AppImage against it).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
out=$(realpath -m "${1:?usage: appimage-libs.sh OUT_FILE}")
name=${REFRAME_BUILD_NAME:-reframe-linux-build}

DOCKER_BUILDKIT=0 docker build -t "$name" "$here"
mkdir -p "$(dirname "$out")"
docker run --rm \
    -v "$repo/scripts:/src/scripts:ro" \
    -v "$here:/src/desktop/packaging/linux:ro" \
    -v "$(dirname "$out"):/out" \
    -e OUT_OWNER="$(id -u):$(id -g)" \
    "$name" sh -c 'uv run --no-project python /src/scripts/appimage-libs.py resolve --out "/out/$1" \
        && chown "$OUT_OWNER" "/out/$1"' sh "$(basename "$out")"
