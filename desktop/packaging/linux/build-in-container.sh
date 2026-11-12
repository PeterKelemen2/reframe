#!/bin/sh
# Runs inside the build image (Dockerfile next to this file), in a clean copy of the repository
# at /build/reframe. Writes the AppImage, .deb and .rpm, THIRD_PARTY_NOTICES and glibc.txt to /out.
set -eu

cd /build/reframe
export UV_PROJECT_ENVIRONMENT=/build/venv UV_LINK_MODE=copy
tools=desktop/src-tauri/resources/tools

uv sync --frozen
uv run python scripts/bundle-tools.py --platform linux-x64 --dest "$tools"

# The bundler copies each symbolic link as one more copy of the file it points to: keep every
# library once, under the name the programs ask the loader for (its soname).
find "$tools" -type l -delete
for library in "$tools"/*/lib/*.so.*; do
    soname=$(readelf -d "$library" | sed -n 's/.*(SONAME).*\[\(.*\)\]/\1/p')
    if [ -n "$soname" ] && [ "${library##*/}" != "$soname" ]; then
        mv "$library" "${library%/*}/$soname"
    fi
done
# linuxdeploy would copy the bundled tools' libraries a second time into usr/lib of the AppImage,
# and it fails on those that find each other only through the program's RPATH.
LINUXDEPLOY_EXCLUDED_LIBRARIES=$(find "$tools" -path '*/lib/*.so*' -type f -printf '%f\n' | paste -sd ';' -)
export LINUXDEPLOY_EXCLUDED_LIBRARIES

uv run python desktop/sidecar/build.py
(cd frontend && npm ci --no-audit --no-fund)
(cd desktop && npm ci --no-audit --no-fund)
uv run --with pip-licenses==5.5.5 python scripts/third-party-notices.py --platform linux-x64

rm -rf "$CARGO_TARGET_DIR/release/bundle"
(cd desktop && npx tauri build --verbose)

bundle="$CARGO_TARGET_DIR/release/bundle"
mkdir -p /out
cp "$bundle"/deb/*.deb "$bundle"/rpm/*.rpm "$bundle"/appimage/*.AppImage \
    desktop/src-tauri/resources/notices/THIRD_PARTY_NOTICES /out/
sh desktop/packaging/linux/glibc-report.sh /out/*.AppImage > /out/glibc.txt
