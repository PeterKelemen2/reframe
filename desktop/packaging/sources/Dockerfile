# The image that runs scripts/sources-fetch.py in the release workflow. BtbN's download commands
# expect the tools of BtbN's base image (images/base/Dockerfile, Ubuntu 26.04): Ubuntu 22.04's
# git is too old for libplacebo's `submodule update --filter=blob:none`, and LAME's autoreconf
# needs autoconf 2.73.
#   DOCKER_BUILDKIT=0 docker build -t reframe-sources-fetch desktop/packaging/sources

ARG UBUNTU_IMAGE=ubuntu:26.04@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM ${UV_IMAGE} AS uv

FROM ${UBUNTU_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
# Every version below comes from the archive as it was at this time (snapshot.ubuntu.com), so
# the pins keep working after the archive moves on. Reaching the snapshot needs the trust store.
ARG APT_SNAPSHOT=20261114T000000Z
ARG AUTOCONF_DEB=autoconf_2.73-2_all.deb
ARG AUTOCONF_SHA256=7708a595b2857bca8bfa4fbbde7d33005dbb0219d0abad305810fce9eaa63270
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get update --snapshot "$APT_SNAPSHOT" \
    && apt-get install -y --no-install-recommends curl=8.18.0-1ubuntu2.8 \
    && curl -fsSL -o "/tmp/$AUTOCONF_DEB" \
        "https://snapshot.ubuntu.com/ubuntu/$APT_SNAPSHOT/pool/main/a/autoconf/$AUTOCONF_DEB" \
    && echo "$AUTOCONF_SHA256  /tmp/$AUTOCONF_DEB" | sha256sum -c - \
    && apt-get install -y --no-install-recommends \
        "/tmp/$AUTOCONF_DEB" \
        automake=1:1.18.1-3build1 \
        cargo=1.93.1ubuntu1 \
        git=1:2.53.0-1ubuntu1.1 \
        libtool=2.5.4-9 \
        meson=1.10.1-1ubuntu2 \
        pkgconf=2.5.1-4 \
        python3=3.14.3-0ubuntu2 \
        subversion=1.14.5-6build1 \
        xz-utils=5.8.3-1ubuntu0.1 \
    && rm -rf /var/lib/apt/lists/* "/tmp/$AUTOCONF_DEB"

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy
RUN uv python install 3.14.8
