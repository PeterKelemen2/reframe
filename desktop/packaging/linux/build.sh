#!/bin/sh
# Builds the Linux desktop packages (AppImage, .deb, .rpm) in the Ubuntu 22.04 build image from a
# clean copy of the working tree: its tracked and untracked files, without the ignored ones.
# Usage: desktop/packaging/linux/build.sh OUT_DIR
# REFRAME_BUILD_NAME names the image and the cache volumes (default reframe-linux-build).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
out=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
name=${REFRAME_BUILD_NAME:-reframe-linux-build}

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
        -e CARGO_TARGET_DIR=/build/target \
        -e npm_config_cache=/root/.cache/npm \
        -e OUT_OWNER="$(id -u):$(id -g)" \
        "$name" sh -c '
            mkdir -p /build/reframe && tar -xf - -C /build/reframe
            sh /build/reframe/desktop/packaging/linux/build-in-container.sh
            status=$?
            chown -R "$OUT_OWNER" /out
            exit $status'
ls -l "$out"
