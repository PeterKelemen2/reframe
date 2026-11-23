#!/bin/sh
# Prints the path of the AppImage runtime that tools/static-builds.toml pins, downloaded into
# CACHE_DIR and checked against its SHA-256 (a cached copy is checked again before it is used).
# The bundler takes it from LDAI_RUNTIME_FILE instead of downloading a floating build.
# Usage: appimage-runtime.sh CACHE_DIR
set -eu

here=$(cd "$(dirname "$0")" && pwd)
cache=${1:?usage: appimage-runtime.sh CACHE_DIR}
pins="$here/../../../tools/static-builds.toml"

read -r url sha256 <<EOF
$(uv run --no-project python -c 'import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))["binaries"]["appimage-runtime"]
print(pin["url"], pin["sha256"])' "$pins")
EOF
runtime="$cache/appimage-runtime-$sha256"
# stdout too: uutils sha256sum (Ubuntu 26.04) prints "FAILED open or read" there despite --status.
if ! echo "$sha256  $runtime" | sha256sum -c --status - >/dev/null 2>&1; then
    mkdir -p "$cache"
    curl -fsSL --retry 3 -o "$runtime.part" "$url"
    if ! echo "$sha256  $runtime.part" | sha256sum -c --status - >/dev/null; then
        rm -f "$runtime.part"
        echo "appimage-runtime.sh: $url does not have the SHA-256 $sha256" >&2
        exit 1
    fi
    mv "$runtime.part" "$runtime"
fi
echo "$runtime"
