#!/bin/sh
# The CI job's desktop-smoke steps on Linux, in run.sh's image: the packaged libva, the frozen
# sidecar, the release app, the FFmpeg archive (cached in the image's cache volume), the
# fixture, then the smoke test under Xvfb.
set -eu

cd /build/reframe
export UV_PROJECT_ENVIRONMENT=/build/venv UV_LINK_MODE=copy

uv sync --frozen
uv run python scripts/bundle-tools.py --platform linux-x64
uv run python desktop/sidecar/build.py
(cd frontend && npm ci --no-audit --no-fund)
(cd desktop && npm ci --no-audit --no-fund && npx tauri build --no-bundle)
cargo install --locked tauri-driver@2.1.0

cache=/root/.cache/reframe-smoke/ffmpeg-archive
archive=$(uv run python desktop/tests/smoke/ffmpeg-archive.py "$cache")
ffmpeg_bin=$(uv run python desktop/tests/smoke/ffmpeg-archive.py "$cache" --extract "$(mktemp -d)/ffmpeg")
REFRAME_FFMPEG=$ffmpeg_bin/ffmpeg REFRAME_FFPROBE=$ffmpeg_bin/ffprobe \
    uv run python scripts/make-testdata.py --only multitrack

cd desktop
npm run smoke:typecheck
../frontend/node_modules/.bin/oxlint -c ../frontend/.oxlintrc.json --deny-warnings tests/smoke
../frontend/node_modules/.bin/oxfmt -c ../frontend/.oxfmtrc.json --check tests/smoke
REFRAME_SMOKE_FFMPEG_ARCHIVE=$archive dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24' npm run smoke
