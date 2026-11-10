# The image that builds the Linux packages (AppImage, .deb, .rpm) on the oldest supported distro,
# so that the app, the frozen sidecar and the shipped libva load on every newer one.
# scripts/build-linux-packages.sh builds and runs it; the repository is mounted at /src.

ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:076e7bf82319619f28dd0aa9c02ab34b055ad37100395b4f49a2ffba04fb5e11
ARG NODE_IMAGE=node:24.22.1-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node

FROM ${UBUNTU_IMAGE} AS build
ARG RUSTUP_VERSION=1.29.3
ARG RUSTUP_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
ARG RUST_TOOLCHAIN=1.99.1
ARG PYTHON_VERSION=3.14.8

# Tauri's libraries, the AppImage tools' needs (file, patchelf), and libva's build tools.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl file git patchelf pkg-config \
        libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev libssl-dev \
        meson ninja-build libdrm-dev bzip2 xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -sSfL -o /tmp/rustup-init \
        "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" \
    && echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c - \
    && chmod +x /tmp/rustup-init \
    && /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain "${RUST_TOOLCHAIN}" \
    && rm /tmp/rustup-init && chmod -R a+rX /opt/rustup /opt/cargo

ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install "${PYTHON_VERSION}" && chmod -R a+rX /opt/python

# The build runs as the caller's user (files in /src stay theirs); these get a writable home.
ENV HOME=/tmp/home CARGO_HOME=/cache/cargo UV_CACHE_DIR=/cache/uv UV_PROJECT_ENVIRONMENT=/cache/venv \
    CARGO_TARGET_DIR=/cache/target npm_config_cache=/cache/npm APPIMAGE_EXTRACT_AND_RUN=1
WORKDIR /src

# The smoke test (desktop/smoke/smoke.py) against an installed package: WebKitWebDriver, a
# virtual display, and tauri-driver.
FROM build AS smoke
ARG TAURI_DRIVER_VERSION=2.1.0
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        webkit2gtk-driver xvfb xauth dbus-x11 \
    && rm -rf /var/lib/apt/lists/*
RUN CARGO_HOME=/opt/cargo cargo install --locked --root /usr/local tauri-driver --version "${TAURI_DRIVER_VERSION}"
