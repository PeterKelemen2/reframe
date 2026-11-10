#!/bin/sh
# Builds the Linux packages (AppImage, .deb, .rpm) in Ubuntu 22.04 with Docker
# (desktop/packaging/linux.Dockerfile): the frontend, the frozen sidecar, the bundled tools with
# the libva built from source, then `tauri build`. The packages go to dist/linux/.
#
# The updater artefacts are signed with ~/.tauri/reframe-updater.key and its password file when
# they exist (TAURI_SIGNING_PRIVATE_KEY_PATH and TAURI_SIGNING_PRIVATE_KEY_PASSWORD_FILE
# override the paths); without a key the packages are built without them.
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
image=reframe-linux-build
cache=reframe-linux-build-cache
key=${TAURI_SIGNING_PRIVATE_KEY_PATH:-$HOME/.tauri/reframe-updater.key}
password=${TAURI_SIGNING_PRIVATE_KEY_PASSWORD_FILE:-$key.password}

docker build --target build -t "$image" -f "$repo/desktop/packaging/linux.Dockerfile" "$repo/desktop/packaging"
docker volume create "$cache" >/dev/null
docker run --rm -v "$cache:/cache" "$image" chown "$(id -u):$(id -g)" /cache

secrets=""
updater='{"bundle":{"createUpdaterArtifacts":false}}'
if [ -f "$key" ]; then
    secrets="-v $key:/run/updater.key:ro"
    [ -f "$password" ] && secrets="$secrets -v $password:/run/updater.key.password:ro"
    updater='{}'
fi

# linuxdeploy (AppImage) does not follow the bundled FFmpeg's RPATH and fails on its libraries;
# they load through that RPATH, and libva through LD_LIBRARY_PATH (reframe.platform.libva).
excluded="libavcodec.so*;libavdevice.so*;libavfilter.so*;libavformat.so*;libavutil.so*"
excluded="$excluded;libswresample.so*;libswscale.so*;libva.so*;libva-drm.so*"

# shellcheck disable=SC2086 # $secrets is a list of options
docker run --rm --user "$(id -u):$(id -g)" -v "$repo:/src" -v "$cache:/cache" $secrets \
    -e UPDATER_CONFIG="$updater" -e LINUXDEPLOY_EXCLUDED_LIBRARIES="$excluded" "$image" sh -euc '
        mkdir -p "$HOME"
        npm ci --prefix frontend --no-audit --no-fund
        npm ci --prefix desktop --no-audit --no-fund
        uv sync --frozen
        uv run python desktop/sidecar/build.py
        uv run --no-project python scripts/bundle-tools.py --libva-build native
        if [ -f /run/updater.key ]; then
            TAURI_SIGNING_PRIVATE_KEY=$(cat /run/updater.key)
            TAURI_SIGNING_PRIVATE_KEY_PASSWORD=$(cat /run/updater.key.password 2>/dev/null || true)
            export TAURI_SIGNING_PRIVATE_KEY TAURI_SIGNING_PRIVATE_KEY_PASSWORD
        fi
        (cd desktop && npx tauri build --config "$UPDATER_CONFIG")
        rm -rf dist/linux && mkdir -p dist/linux
        find /cache/target/release/bundle -mindepth 2 -maxdepth 2 -type f \( -name "*.AppImage" \
            -o -name "*.deb" -o -name "*.rpm" -o -name "*.sig" \) -exec cp {} dist/linux/ \;
        ls -la dist/linux
    '
