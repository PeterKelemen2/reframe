#!/bin/sh
# Runs the desktop smoke test in Ubuntu 22.04, for a host without WebKitWebDriver: builds the
# release app from a clean copy of the working tree (its tracked and untracked files), as the CI
# job does, and runs the test under Xvfb.
# REFRAME_BUILD_NAME: the image that desktop/packaging/linux/build.sh built (default
# reframe-linux-build). REFRAME_SMOKE_NAME: this test's image and cache volumes (default
# reframe-smoke).
# Usage: desktop/tests/smoke/linux/run.sh [COMMAND…]   (default: in-container.sh)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
base=${REFRAME_BUILD_NAME:-reframe-linux-build}
name=${REFRAME_SMOKE_NAME:-reframe-smoke}

DOCKER_BUILDKIT=0 docker build -t "$name" --build-arg "BUILD_IMAGE=$base" "$here"

[ $# -gt 0 ] || set -- sh desktop/tests/smoke/linux/in-container.sh
cd "$repo"
git ls-files -z --cached --others --exclude-standard --deduplicate \
    | tar --null --files-from=- --ignore-failed-read -cf - \
    | docker run --rm -i \
        -v "$name-cargo:/opt/cargo/registry" \
        -v "$name-target:/build/target" \
        -v "$name-cache:/root/.cache" \
        -e CARGO_TARGET_DIR=/build/target \
        -e npm_config_cache=/root/.cache/npm \
        "$name" sh -c 'mkdir -p /build/reframe && tar -xf - -C /build/reframe && cd /build/reframe && exec "$@"' sh "$@"
