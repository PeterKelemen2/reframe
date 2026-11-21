#!/bin/sh
# Runs inside the build image (Dockerfile next to this file), in a clean copy of the repository
# at /build/reframe. Writes the AppImage, .deb and .rpm, THIRD_PARTY_NOTICES and glibc.txt to /out.
set -eu

cd /build/reframe
export UV_PROJECT_ENVIRONMENT=/build/venv UV_LINK_MODE=copy
tools=desktop/src-tauri/resources/tools

uv sync --frozen
uv run python scripts/bundle-tools.py --platform linux-x64 --dest "$tools"

# Tauri's bundler copies each symbolic link as one more copy of the file it points to: keep every
# library once, under the name the programs ask the loader for (its soname).
find "$tools" -type l -delete
for library in "$tools"/*/*.so.*; do
    soname=$(readelf -d "$library" | sed -n 's/.*(SONAME).*\[\(.*\)\]/\1/p')
    if [ -n "$soname" ] && [ "${library##*/}" != "$soname" ]; then
        mv "$library" "${library%/*}/$soname"
    fi
done
# linuxdeploy would copy the packaged libraries a second time into usr/lib of the AppImage,
# and it fails on those that find each other only through the loading program. Keeping libva out
# of usr/lib also makes GStreamer's va plugin load the host's libva, the one the host's VA-API
# drivers are built for (Ubuntu 22.04's cannot load a driver newer than its own).
LINUXDEPLOY_EXCLUDED_LIBRARIES=$(find "$tools" -name '*.so*' -type f -printf '%f\n' | paste -sd ';' -)
export LINUXDEPLOY_EXCLUDED_LIBRARIES

uv run python desktop/sidecar/build.py
(cd frontend && npm ci --no-audit --no-fund)
(cd desktop && npm ci --no-audit --no-fund)
# build.sh passes the sources release of a release build and mounts its files in /sources.
set -- --platform linux-x64
if [ -n "${REFRAME_SOURCES_URL:-}" ]; then
    set -- "$@" --sources-url "$REFRAME_SOURCES_URL" --sources-sums /sources/SHA256SUMS \
        --sources-manifest /sources/manifest.json --sources-texts /sources/licence-texts.json
fi
uv run --with pip-licenses==5.5.5 python scripts/third-party-notices.py "$@"

LDAI_RUNTIME_FILE=$(sh desktop/packaging/linux/appimage-runtime.sh "$HOME/.cache/reframe")
export LDAI_RUNTIME_FILE

# The bundler's GStreamer plugin copies every file of these folders into the AppImage.
gstreamer=/usr/lib/x86_64-linux-gnu/gstreamer-1.0
GSTREAMER_PLUGINS_DIR=$(mktemp -d)
GSTREAMER_HELPERS_DIR=$(mktemp -d)
for plugin in $(sed 's/#.*//' desktop/packaging/linux/appimage-gstreamer-plugins.txt); do
    cp "$gstreamer/libgst$plugin.so" "$GSTREAMER_PLUGINS_DIR/"
done
cp /usr/lib/x86_64-linux-gnu/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner "$GSTREAMER_HELPERS_DIR/"
export GSTREAMER_PLUGINS_DIR GSTREAMER_HELPERS_DIR

rm -rf "$CARGO_TARGET_DIR/release/bundle"
version=$(node -p 'require("./desktop/src-tauri/tauri.conf.json").version')
case $version in
    *-*)
        # rpm refuses a `-` in a version: the rpm of a pre-release is X.Y.Z with the pre-release
        # in a release below 1 (0.1.0-dev.0 → 0.1.0-0.dev.0), which sorts before X.Y.Z-1.
        release=0.$(printf %s "${version#*-}" | tr - .)
        rpm_config="{\"version\": \"${version%%-*}\", \"bundle\": {\"linux\": {\"rpm\": {\"release\": \"$release\"}}}}"
        (cd desktop && npx tauri build --verbose --bundles deb,appimage \
            && npx tauri bundle --verbose --bundles rpm --config "$rpm_config")
        ;;
    *) (cd desktop && npx tauri build --verbose) ;;
esac

bundle="$CARGO_TARGET_DIR/release/bundle"
uv run --no-project python scripts/appimage-libs.py check-runtime "$bundle"/appimage/*.AppImage \
    --runtime "$LDAI_RUNTIME_FILE"
mkdir -p /out
cp "$bundle"/deb/*.deb "$bundle"/rpm/*.rpm "$bundle"/appimage/*.AppImage \
    desktop/src-tauri/resources/notices/THIRD_PARTY_NOTICES /out/
sh desktop/packaging/linux/glibc-report.sh /out/*.AppImage > /out/glibc.txt
