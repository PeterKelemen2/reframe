# 0059 — S-6: the Docker image, the compose example and bare metal

- Status: accepted
- Date: 2026-10-28
- Steps: S-6

## Context

06 §S-6 asks for a multi-stage image (a `node` stage, a `tools` stage that fetches the pinned
FFmpeg, a Debian slim runtime with the GPU user-space drivers, non-root through
`PUID`/`PGID`, the folders `/config`, `/data`, `/media`, `/output`, a `HEALTHCHECK`), a
compose example for Intel/AMD and NVIDIA with a commented override, a bare-metal install with
a systemd user unit, and reverse-proxy notes. It is built early, on `server-complete`
([0055](0055-server-complete-order.md)), in wave 2, after S-7's owner (0056) and S-4 (0058).

What the image must take into account, from the merged code:

- web mode off loopback refuses `auth: none` (exit 2) and refuses an output outside the
  output roots; `static_dir` has no default (0058);
- every server opens the queue and writes `<data dir>/server.json` (0056); a CLI in the
  container reaches it through `docker exec`;
- `auth.json` is written by `reframe-server --set-password` and must be readable by the
  server's user.

What was found on the real tools is in [testdata/README.md](../../testdata/README.md),
"Docker image and deployment (S-6, task D)": this Docker has no buildx; `docker compose build`
falls back to the classic builder; Debian 13's Mesa has every VAAPI codec; Debian's free
Intel driver lacks encoders before Ice Lake; a clean stop of the server ends with SIGTERM (143);
`docker exec` runs as root; uvicorn trusts `X-Forwarded-*` only from `FORWARDED_ALLOW_IPS`.

## Decision

1. **Stages** (`docker/Dockerfile`, build context the repository root, `.dockerignore` lets
   only the needed files in): `frontend` (`node:24.22.1-trixie-slim`, `npm ci`,
   `npm run build:web`); `python` (Debian `trixie-20261027-slim`, uv 0.13.5 from its image,
   a uv-managed CPython 3.14.8 in `/opt/reframe/python`); `tools` (`scripts/fetch-tools.py
   --install-dir /opt/reframe/tools/ffmpeg`: size and SHA-256 before extraction, both
   binaries run); `app` (`uv sync --frozen --no-dev --all-packages --extra cli --extra
   mediainfo --no-editable` into `/opt/reframe/venv`, dependencies in their own layer); and
   the runtime. Base images are pinned by tag and digest. The Dockerfile uses no BuildKit-only
   syntax (0055 item 7).
2. **The interpreter is uv's, not Debian's.** Debian 13 has Python 3.13; the project's
   `.python-version` is 3.14, which CI tests. The venv and the interpreter are copied into the
   runtime at the same paths.
3. **Runtime packages, exact versions**: `mesa-va-drivers`, `intel-media-va-driver-non-free`,
   `libmfx-gen1.2` (oneVPL GPU runtime), `mkvtoolnix`, `mediainfo`, `tini`. The **non-free**
   Intel driver, from Debian's `non-free` component: the free build has no H.264 or HEVC encode
   before Ice Lake, which many NAS CPUs are. A Debian point release that removes a pinned
   version makes the build fail; then the pins are raised. Not in the image: Vulkan drivers
   (`mesa-vulkan-drivers`), so a `libplacebo` filter on the GPU does not work in Docker; the
   plan's list does not name them.
4. **The bundled FFmpeg tree is kept as fetched** (with `include/`, `man/`, `doc/`, about
   20 MB), so its `.fetch-tools.json` still matches the files.
5. **The image's settings**: `REFRAME_HOST=0.0.0.0`, `REFRAME_PORT=8765` (the port the Vite
   dev proxy uses), `REFRAME_AUTH=password`, `REFRAME_MEDIA_ROOTS=["/media"]`,
   `REFRAME_OUTPUT_ROOTS=["/output"]`, config `/config`, data `/data`, cache `/data/cache`,
   `REFRAME_STATIC_DIR=/opt/reframe/frontend`, `PUID`/`PGID` 1000,
   `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility`. `password` is the mode a browser user
   can log in with; until `--set-password` runs the server starts and warns, and the local
   token of `server.json` still works. `tests/test_deploy.py` checks that every `REFRAME_*`
   name of the image is read by the server or the core, and what the config resolves to.
6. **Non-root**: `tini` is process 1 (`-e 143`: a clean stop is exit 0) and runs
   `reframe-entrypoint`, which, as root, gives `/config` and `/data` to `PUID:PGID` (a
   recursive `chown` only when the folder's owner differs), adds the groups of the
   `/dev/dri/*` nodes (the `render` group's id differs between hosts; group 0 is skipped), sets
   `HOME=/data`, and starts the command with `setpriv --no-new-privs`. Started as another
   user (`--user`), or with `PUID=0` (rootless Docker, Podman), it runs the command as it is.
   `reframe` and `reframe-server` in `/usr/local/bin` are links to the entrypoint, so
   `docker exec … reframe-server --set-password` and the CLI also run as `PUID:PGID`.
7. **No `VOLUME` instruction.** `/config`, `/data`, `/media` and `/output` are mount points
   that the docs and the compose example mount. An anonymous volume would hide a missing
   mount: encodes written to an anonymous `/output` disappear with it.
8. **`HEALTHCHECK`**: the venv's Python fetches `http://127.0.0.1:$REFRAME_PORT/api/health`
   every 30 s (no curl in the image). A loopback `Host` passes the Host check.
9. **Compose example**: an anchor with the build, image, ports, environment and the four
   mounts; service `reframe` (Intel/AMD, `/dev/dri`), started by `docker compose up`; service
   `reframe-nvidia` in profile `nvidia` with `deploy.resources.reservations.devices`
   (`docker compose up reframe-nvidia`). The override (`REFRAME_FFMPEG`, the mount) and
   `REFRAME_ALLOWED_HOSTS` are commented out. `stop_grace_period: 30s`.
10. **Bare metal** (`docs/deployment.md`): the plan's `uv tool install 'reframe[cli]' --with
    reframe-server --with-executables-from reframe-server` needs the packages on PyPI, which
    they are not. Until then the same command takes the paths of a checkout. `reframe tools
    fetch` puts FFmpeg in the data dir; the web build is built and copied by hand, then named
    with `REFRAME_STATIC_DIR`. The unit is a `Type=exec` user service with
    `Restart=on-failure` and `RestartPreventExitStatus=2`; `loginctl enable-linger` keeps it
    running.
11. **Reverse proxy** (`docs/deployment.md`): served at the site root; the proxy's name in
    `REFRAME_ALLOWED_HOSTS` and the browser's `Host` passed on; `Upgrade`/`Connection` for
    `/api/events`, an idle timeout above the 15 s heartbeat; `client_max_body_size 16m` (a job
    is 3–4 KB of JSON); `FORWARDED_ALLOW_IPS` for a proxy that is not on loopback, so the
    login limit counts clients and the cookie is `Secure`. Checked through nginx in Docker.

### Verified here, and what is not

Verified on the owner's desktop without a GPU in the container: the build (classic builder),
`docker compose up` of the example with the devices removed by a test override, the health
check (`healthy`), the static UI, `--set-password` through `docker compose exec -T` (file
owned by `PUID`), password login, a software encode (libx265) of the `multitrack` fixture
through the API into `/output`, an output outside `/output` refused, `REFRAME_FFMPEG` with a
mounted build (origin `env`, ffprobe next to it), `PUID`/`PGID` changes, a bad `PUID` (exit 2),
`docker compose stop` during an encode, and the bare-metal install, fetch and server. The
interactive `docker compose exec -it … --set-password` was not run (no terminal here).

Not verified: the "Done when" itself. The lead runs it in wave 4, in a slot the owner gives,
because the test encodes share the GPU with the owner's movie: `docker compose up` of the
example with `/dev/dri` and `encoders.hardware_tests` on, then the VAAPI encoders must be
`available` in `GET /api/system/encoders` and a VAAPI encode of a fixture must finish. Intel
QSV and NVIDIA NVENC in Docker are not verified until such a host is available
([0043](0043-plan-review-before-m3.md) item 7). The image is `linux/amd64` only.

### Proposals for the lead (files outside S-6)

- A `--static-dir` option (as 0058 proposes), so the systemd unit names the web build on its
  command line, and `REFRAME_FORWARDED_ALLOW_IPS` (or an option) passed to uvicorn, so the
  trusted proxies are a Reframe setting next to `allowed_hosts`.
- Q-2: a CI job that builds the image (it needs network access for the FFmpeg archive).

## Consequences

- The image is about 1.24 GB unpacked (327 MB compressed): FFmpeg 245 MB, LLVM for Mesa
  124 MB, Python 107 MB, the venv 95 MB.
- A Debian security update that replaces a pinned package breaks the build until the pin is
  raised.
- `docker exec` without the links (for example `python -m reframe`) runs as root and can
  leave root-owned files in `/data`; the docs name only the linked commands.

## Plan changes

- [06-web-app.md](../plan/06-web-app.md) §S-6: the items are ticked; a paragraph after them
  says what this record decided (no `VOLUME`, the paths for `uv tool install` until the
  packages are published, the non-free Intel driver) and that the "Done when" waits for the
  GPU run.

## Follow-up (review), 2026-10-28

An independent review of S-6 found one major problem, four minor ones and some nits. All are
fixed. What Docker, uvicorn, `setpriv` and `cp` did is in
[testdata/README.md](../../testdata/README.md), "Docker image and deployment (S-6, task D)",
the part checked again on 2026-10-28.

- **F2 (major): the reverse-proxy notes were wrong for Docker.** This replaces the
  `FORWARDED_ALLOW_IPS` part of item 11. A proxy on the Docker host reaches the container
  from the network's gateway, not from 127.0.0.1, so with the old notes the server trusted no
  proxy: five wrong passwords from anyone locked out every client, the owner too, and the
  cookie had no `Secure`. The old example `FORWARDED_ALLOW_IPS=172.16.0.0/12` let a client on
  the published port name any `X-Forwarded-For` (12 wrong passwords, never 429) and get a
  `Secure` cookie over plain HTTP. The compose example published 8765 on every address, past
  ufw. Now `docs/deployment.md` says what goes wrong when the proxy is not trusted and when
  more than the proxy is trusted. A new section, "Reverse proxy in Docker", gives two set-ups,
  each with a fixed subnet: a proxy on the host (`127.0.0.1:8765:8765`, trust the gateway
  `172.30.87.1`), and a proxy container (no port for Reframe, the proxy at `172.30.87.10`,
  `ip_range` for the other containers, trust that address). It also says never to trust a
  range. The compose example says this next to `ports`. Proof (real containers, no GPU, the
  nginx block of the docs): through the proxy, a client that sent a new `X-Forwarded-For`
  with each wrong password got 429 at the 6th try. Another client then logged in (200,
  `Secure`). In the container set-up, a container that went past the proxy and the host (the
  gateway) each got 429 at the 6th try, and no `Secure` with `X-Forwarded-Proto: https`. In
  the host set-up, the LAN address and `[::1]` refused the connection, and a container of
  another network timed out. The same runs with the old notes gave the reviewer's result. No
  pytest: the behaviour is Docker's and uvicorn's, not Reframe code. The check also found
  that `ip_range` without `gateway` moves the gateway to the start of the range, so the docs
  name the gateway.
- **F4 (minor): `test_deploy.py` let data-loss changes through.** Two new tests. The first
  checks that the image's config, data and cache folders, as the core resolves them with
  `HOME=/` (`docker run --user`), are inside the folders that the entrypoint gives to `PUID`,
  and that the compose example mounts those folders. It catches the reviewer's mutations
  (data dir `/var/lib/reframe`, config and cache moved or removed), a `/data` that the
  entrypoint does not hand over, and a compose example without the `/data` mount. The second
  test asks the harness's password-mode app, without credentials, for the `HEALTHCHECK` URL
  path, and expects 200. It catches `/api/healthz` and a route that needs a login.
- **F5 (minor): a missing host folder became root's.** The docs now say to make the host
  folders first, as `PUID:PGID`. Proof: with only the media folder present, `/output` was
  `root:root` and the job failed with `output.not_writable`. After `mkdir -p` the encode
  finished.
- **F6 (minor): a second `cp -r dist ~/.local/share/reframe-web` kept the old UI.** The docs
  now remove the folder first, and say why. Proof: two stand-in builds copied the old way
  left build 1's `index.html`; the new way left build 2's only.
- **F7 (minor): the entrypoint compared `PUID` as text.** `PUID=00` took the `setpriv` path
  and ran as root with every capability. A `PUID` with leading zeros (`01000`) walked
  `/config` and `/data` at every start. The entrypoint now checks both numbers before it
  compares them, removes leading zeros, and warns on stderr when `PUID=0` runs in a container
  whose user map maps each id to itself (the container's root is the host's root). Rootless
  Docker and Podman map it to the host user, so they get no warning. A warning, not a
  refusal, because the user map is a guess (nested containers, Docker Desktop's VM), and
  `PUID=0` must be set on purpose. Four tests run the script with stand-in `id`, `stat`,
  `chown` and `setpriv`. `PUID=00` gives the warning and no `setpriv` (on the old script it
  ran `setpriv --reuid=00`). Under `unshare --user --map-root-user`, `PUID=0` gives no
  warning. `PUID=01000` gives `--reuid=1000` and no `chown` (on the old script, both
  `chown -R 01000:1000` lines). `PUID=1000x` gives exit 2. The image's `dash` gave the same
  results: `PUID=00` and `PUID=0` warn and run as root, `01000` runs as 1000.
- **F8 (nits)**, in the docs: the Python is CPython 3.14.8 (`.python-version` names 3.14);
  the Dockerfile pins the Debian packages that it names, not their dependencies; the
  `HEALTHCHECK` uses `REFRAME_PORT`, so the port is changed with `REFRAME_PORT`, not
  `--port` (checked: `--port 9000` became `unhealthy`, `REFRAME_PORT=9000` `healthy`); with
  `docker run --user`, `/config` and `/data` must be writable by that user (checked: with a
  `/data` the user cannot write, the container was `healthy` but saved no job).

Still a proposal for the lead (outside S-6): `REFRAME_FORWARDED_ALLOW_IPS` as a Reframe
setting, so that the trusted proxy is named next to `allowed_hosts`.

## The lead's GPU check, 2026-10-28

The "Done when", run by the lead in a slot the owner gave (the GPU is shared with the owner's
movie), on the merged branch (58cdac9): the image built with the classic builder in 87 s; the
compose example with only the host paths (temporary folders), the image name and a loopback
port changed (`127.0.0.1:18765:8765`); `settings.json` with `hardware_tests` on.

```
container devices: [{"PathOnHost":"/dev/dri","PathInContainer":"/dev/dri","CgroupPermissions":"rwm"}]
health: healthy
server process (pid from server.json): Name: reframe-server | Uid: 1000 1000 1000 1000 | Gid: 1000 1000 1000 1000 | Groups: 983 987 1000 | CapEff: 0000000000000000 | NoNewPrivs: 1
server.json (in the /data mount): pid 7 port 8765 api_version 1
  av1_vaapi: available
  h264_vaapi: available
  hevc_vaapi: available
  qsv / nvenc: h264/hevc/av1 _nvenc and _qsv unavailable
validate hevc_vaapi: [('info', 'dimensions.crop_not_detected', …)]
encode: done in 0.4 s
$ /opt/reframe/tools/ffmpeg/bin/ffmpeg … -init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va … format=p010le,hwupload … -c:v:0 hevc_vaapi -rc_mode:v:0 CQP -global_quality:v:0 22 …
ffprobe of the output (owner 1000): hevc 320x180 yuv420p10le, 3 aac, 3 subrip, duration 4.031000
compose log: ERROR lines 0 | token in the log: False
```

- The job was the draft with the encoder set to `hevc_vaapi` and the x265 fields cleared
  (preset, tune, profile, level, advanced, custom parameters): with only the encoder changed,
  validation refuses it (`encoder.preset_unsupported`, eight `encoder.custom_param_unknown`).
- FFmpeg printed `amdgpu: os_same_file_description couldn't determine if two DRM fds
  reference the same file description. If they do, bad things may happen!` in the container.
  The encode was not affected; the cause was not checked.
- Every container, image, network and the build's base images were removed; the Docker state
  equals the owner's snapshot from before phase 2, build cache 0 B.
