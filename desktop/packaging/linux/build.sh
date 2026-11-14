#!/bin/sh
# Builds the Linux desktop packages (AppImage, .deb, .rpm) in the Ubuntu 22.04 build image from a
# clean copy of the working tree: its tracked and untracked files, without the ignored ones.
# Usage: desktop/packaging/linux/build.sh OUT_DIR
# REFRAME_BUILD_NAME names the image and the cache volumes (default reframe-linux-build).
# A release sets REFRAME_SOURCES_URL, REFRAME_SOURCES_SUMS and REFRAME_SOURCES_MANIFEST (its
# sources release and that release's SHA256SUMS and manifest.json files, for the notices) and
# REFRAME_APPIMAGE_LIBS (the appimage-libs.sh file the source manifest was made from: the
# AppImage must carry exactly those packages).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
out=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
name=${REFRAME_BUILD_NAME:-reframe-linux-build}
sums=/dev/null
manifest=/dev/null
if [ -n "${REFRAME_SOURCES_URL:-}${REFRAME_SOURCES_SUMS:-}${REFRAME_SOURCES_MANIFEST:-}" ]; then
    if [ -z "${REFRAME_SOURCES_URL:-}" ] || [ -z "${REFRAME_SOURCES_SUMS:-}" ] \
        || [ -z "${REFRAME_SOURCES_MANIFEST:-}" ]; then
        echo "build.sh: set REFRAME_SOURCES_URL, REFRAME_SOURCES_SUMS and" \
            "REFRAME_SOURCES_MANIFEST together, or none of them" >&2
        exit 1
    fi
    sums=$(realpath "$REFRAME_SOURCES_SUMS")
    manifest=$(realpath "$REFRAME_SOURCES_MANIFEST")
    # docker run would mount a missing file as an empty folder.
    for file in "$sums" "$manifest"; do
        [ -f "$file" ] || { echo "build.sh: no file $file" >&2; exit 1; }
    done
fi
if [ -n "${REFRAME_APPIMAGE_LIBS:-}" ]; then
    libs=$(realpath "$REFRAME_APPIMAGE_LIBS")
    [ -f "$libs" ] || { echo "build.sh: no file $libs" >&2; exit 1; }
fi

DOCKER_BUILDKIT=0 docker build -t "$name" "$here"
mkdir -p "$out"

cd "$repo"
git ls-files -z --cached --others --exclude-standard --deduplicate \
    | tar --null --files-from=- --ignore-failed-read -cf - \
    | docker run --rm -i \
        -v "$out:/out" \
        -v "$name-cargo:/opt/cargo/registry" \
        -v "$name-target:/build/target" \
        -v "$name-cache:/root/.cache" \
        -v "$sums:/sources/SHA256SUMS:ro" \
        -v "$manifest:/sources/manifest.json:ro" \
        -e CARGO_TARGET_DIR=/build/target \
        -e npm_config_cache=/root/.cache/npm \
        -e OUT_OWNER="$(id -u):$(id -g)" \
        -e REFRAME_SOURCES_URL="${REFRAME_SOURCES_URL:-}" \
        "$name" sh -c '
            mkdir -p /build/reframe && tar -xf - -C /build/reframe
            sh /build/reframe/desktop/packaging/linux/build-in-container.sh
            status=$?
            chown -R "$OUT_OWNER" /out
            exit $status'

if [ -n "${REFRAME_APPIMAGE_LIBS:-}" ]; then
    docker run --rm \
        -v "$repo/scripts:/src/scripts:ro" \
        -v "$here:/src/desktop/packaging/linux:ro" \
        -v "$libs:/appimage-libs.json:ro" \
        -v "$name-target:/build/target:ro" \
        "$name" sh -c 'uv run --no-project python /src/scripts/appimage-libs.py \
            check /build/target/release/bundle/appimage/*.AppDir --expected /appimage-libs.json'
fi
ls -l "$out"
