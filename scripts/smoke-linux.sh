#!/bin/sh
# Runs the desktop smoke test (desktop/smoke/smoke.py) in Ubuntu 22.04 against the .deb in
# dist/linux/ (scripts/build-linux-packages.sh), on a virtual display. FIXTURE is a media file
# in the repository (default: testdata/media/chapters.mkv, from scripts/make-testdata.py).
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=${FIXTURE:-testdata/media/chapters.mkv}
image=reframe-linux-smoke

docker build --target smoke -t "$image" -f "$repo/desktop/packaging/linux.Dockerfile" "$repo/desktop/packaging"
docker run --rm -v "$repo:/src:ro" -e FIXTURE="$fixture" "$image" sh -euc '
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends /src/dist/linux/*.deb
    mkdir -p "$HOME"
    UV_CACHE_DIR=/tmp/uv xvfb-run -a dbus-run-session -- \
        uv run --no-project python /src/desktop/smoke/smoke.py --app /usr/bin/reframe-desktop \
        --fixture "/src/$FIXTURE"
'
