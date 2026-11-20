# Reframe web server, for linux/amd64 and linux/arm64. It contains no FFmpeg: the first start
# downloads it into /data/tools/ffmpeg (docs/user/ffmpeg.md). Write
# docker/notices/THIRD_PARTY_NOTICES for the platform first (docs/deployment.md), then build from
# the repository root:
#   docker build -f docker/Dockerfile -t reframe:local .
# It also builds with the classic builder (no BuildKit-only syntax). buildx sets TARGETARCH;
# without it each stage takes the architecture it runs on.

ARG DEBIAN_IMAGE=debian:trixie-20261027-slim@sha256:26c37952d274874448dd4f0943fc79bfb7c3d9cc8c8004ac4dc987489ca931be
ARG NODE_IMAGE=node:24.22.1-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM ${UV_IMAGE} AS uv

FROM ${DEBIAN_IMAGE} AS notices
ARG TARGETARCH
COPY docker/notices/ /notices/
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && file=docker/notices/THIRD_PARTY_NOTICES \
    && if [ ! -s /notices/THIRD_PARTY_NOTICES ]; then \
        echo "$file is missing: write it with scripts/third-party-notices.py --platform docker-linux-<x64|arm64> (docs/deployment.md)" >&2; \
        exit 1; \
    fi \
    && case "$arch" in \
        amd64) want=docker-linux-x64 ;; \
        arm64) want=docker-linux-arm64 ;; \
        *) echo "no image is built for $arch" >&2; exit 1 ;; \
    esac \
    && if ! head -n 1 /notices/THIRD_PARTY_NOTICES | grep -qF "($want)"; then \
        echo "$file is not the one for $want (its first line: $(head -n 1 /notices/THIRD_PARTY_NOTICES))" >&2; \
        exit 1; \
    fi

FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build:web

FROM ${DEBIAN_IMAGE} AS python
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/reframe/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_NO_CACHE=1
RUN uv python install 3.14.8

FROM python AS app
ENV UV_PROJECT_ENVIRONMENT=/opt/reframe/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /src
COPY .python-version pyproject.toml uv.lock ./
COPY packages/reframe/pyproject.toml packages/reframe/README.md packages/reframe/
COPY packages/reframe-server/pyproject.toml packages/reframe-server/README.md packages/reframe-server/
RUN uv sync --frozen --no-dev --all-packages --extra cli --no-install-workspace
COPY packages/reframe/src packages/reframe/src
COPY packages/reframe-server/src packages/reframe-server/src
RUN uv sync --frozen --no-dev --all-packages --extra cli --no-editable

FROM ${DEBIAN_IMAGE}
ARG TARGETARCH
COPY --from=notices /notices/THIRD_PARTY_NOTICES /opt/reframe/notices/THIRD_PARTY_NOTICES
COPY docker/debian-packages.sh /tmp/debian-packages.sh
# The GPU drivers that a downloaded FFmpeg loads, with Debian's libva. non-free: the Intel
# media driver with every encoder (the free build has no H.264/HEVC encode before Ice Lake).
# QSV runtimes: libmfx-gen for Tiger Lake and newer; libmfx1 (Media SDK) for the older GPUs,
# which libmfx-gen refuses. Debian 13 has no libmfx1, so it comes from Debian 12, pinned low.
# arm64 gets no GPU drivers: its image claims software encoders only. ca-certificates: the
# FFmpeg download checks the server's certificate.
# Versions are exact; a Debian point release that drops one fails the build.
RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in \
        amd64) gpu="intel-media-va-driver-non-free=25.2.3+ds1-1 libmfx-gen1.2=25.1.4-1 libmfx1=22.5.4-1 mesa-va-drivers=25.0.7-2+deb13u1" ;; \
        arm64) gpu="" ;; \
        *) echo "no image is built for $arch" >&2; exit 1 ;; \
    esac \
    && sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
    && echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list.d/bookworm.list \
    && printf 'Package: *\nPin: release n=bookworm\nPin-Priority: 100\n' > /etc/apt/preferences.d/bookworm \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        $gpu \
        ca-certificates=20250419+deb13u1 \
        tini=0.19.0-3+b8 \
    && rm -rf /var/lib/apt/lists/* /etc/apt/sources.list.d/bookworm.list /etc/apt/preferences.d/bookworm \
    && sh /tmp/debian-packages.sh /opt/reframe/notices/DEBIAN_PACKAGES \
        /opt/reframe/notices/THIRD_PARTY_NOTICES \
    && rm /tmp/debian-packages.sh

COPY --from=python /opt/reframe/python /opt/reframe/python
COPY --from=app /opt/reframe/venv /opt/reframe/venv
COPY --from=frontend /src/frontend/dist /opt/reframe/frontend
COPY docker/entrypoint.sh /usr/local/bin/reframe-entrypoint
RUN chmod 0755 /usr/local/bin/reframe-entrypoint \
    && ln -s reframe-entrypoint /usr/local/bin/reframe \
    && ln -s reframe-entrypoint /usr/local/bin/reframe-server \
    && mkdir -p /config /data /media /output

# List values are JSON, as pydantic-settings reads them from the environment.
# REFRAME_CONTAINER: the server offers no sleep or shut down, which a container cannot do.
ENV PUID=1000 \
    PGID=1000 \
    REFRAME_CONTAINER=1 \
    REFRAME_HOST=0.0.0.0 \
    REFRAME_PORT=8765 \
    REFRAME_AUTH=password \
    REFRAME_CONFIG_DIR=/config \
    REFRAME_DATA_DIR=/data \
    REFRAME_CACHE_DIR=/data/cache \
    REFRAME_MEDIA_ROOTS='["/media"]' \
    REFRAME_OUTPUT_ROOTS='["/output"]' \
    REFRAME_STATIC_DIR=/opt/reframe/frontend \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
    PYTHONUNBUFFERED=1

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/opt/reframe/venv/bin/python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['REFRAME_PORT'], timeout=4)"]
# The server ends a clean stop by raising SIGTERM again: tini reports that as 143.
ENTRYPOINT ["/usr/bin/tini", "-e", "143", "--", "/usr/local/bin/reframe-entrypoint"]
CMD ["reframe-server"]
