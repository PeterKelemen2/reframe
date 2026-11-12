# The smoke test's Linux image: the desktop build image (desktop/packaging/linux/Dockerfile) with
# WebKitWebDriver, Xvfb and tauri-driver, as an Ubuntu 22.04 CI runner has them.
ARG BUILD_IMAGE=reframe-linux-build
FROM ${BUILD_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends webkit2gtk-driver xvfb xauth python3-xlib procps \
    && rm -rf /var/lib/apt/lists/*

ARG TAURI_DRIVER_VERSION=2.1.0
RUN cargo install --locked "tauri-driver@${TAURI_DRIVER_VERSION}" \
    && rm -rf /opt/cargo/registry /opt/cargo/git
