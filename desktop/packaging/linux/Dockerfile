# The Linux desktop build image: Tauri 2's build dependencies on the oldest supported distro,
# so the AppImage, the frozen sidecar and the .deb need no newer glibc than Ubuntu 22.04's.
# build.sh builds it with the classic builder and runs build-in-container.sh in it.

ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:74b12b11ffa550fba1929ad4d8d16533c34f6612728469671afba1b03b66881c
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM ${UV_IMAGE} AS uv

FROM ${UBUNTU_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
# Every package comes from the archive as it was at APT_SNAPSHOT, so the libraries the Linux
# packages carry stay the ones the source manifest was resolved from until this moves (22.04's
# apt has no --snapshot). The snapshot is HTTPS only: until ca-certificates is in, apt trusts the
# archive's signatures alone, as it does with the image's default http:// archive.
ARG APT_SNAPSHOT=20261114T000000Z
# libdrm-dev, meson and ninja-build: bundle-tools.py builds the libva that the packages ship.
RUN printf 'deb https://snapshot.ubuntu.com/ubuntu/%s %s main restricted universe multiverse\n' \
        "$APT_SNAPSHOT" jammy "$APT_SNAPSHOT" jammy-updates "$APT_SNAPSHOT" jammy-security \
        > /etc/apt/sources.list \
    && apt-get -o Acquire::https::Verify-Peer=false update \
    && apt-get -o Acquire::https::Verify-Peer=false install -y --no-install-recommends ca-certificates \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl file git pkg-config wget xz-utils \
        libayatana-appindicator3-dev librsvg2-dev libssl-dev libwebkit2gtk-4.1-dev libxdo-dev \
        desktop-file-utils libdrm-dev meson ninja-build gcc \
    && rm -rf /var/lib/apt/lists/*

ARG NODE_VERSION=24.22.1
ARG NODE_SHA256=6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6
RUN curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --exclude='*/CHANGELOG.md' --exclude='*/README.md' \
    && rm /tmp/node.tar.xz

ARG RUSTUP_VERSION=1.29.3
ARG RUSTUP_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
ARG RUST_VERSION=1.99.1
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -fsSLo /tmp/rustup-init "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" \
    && echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c - \
    && chmod +x /tmp/rustup-init \
    && /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain "${RUST_VERSION}" \
    && rm /tmp/rustup-init

# Only for THIRD_PARTY_NOTICES; it never ships.
ARG CARGO_ABOUT_VERSION=0.9.3
RUN cargo install --locked --features cli "cargo-about@${CARGO_ABOUT_VERSION}" \
    && cargo about --version \
    && rm -rf /opt/cargo/registry /opt/cargo/git

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON_PREFERENCE=only-managed
RUN uv python install 3.14.8

# The bundler cannot mount the linuxdeploy AppImages without FUSE, which containers lack.
ENV APPIMAGE_EXTRACT_AND_RUN=1
