# Deployment

How to run the Reframe web server on a NAS or a home server: in Docker, or on bare metal
with a systemd user unit, and behind a reverse proxy. Reframe is not published yet (no image
on a registry, no wheel on PyPI), so every way below starts from a checkout of this
repository. The choices are recorded in
[decision 0059](decisions/0059-s6-docker-image-and-bare-metal.md).

## Docker

### What the image holds

`docker/Dockerfile` builds one image in four stages:

| Stage | What it does |
|-------|--------------|
| `frontend` | `npm ci` and `npm run build:web` (Node 24) |
| `python` | uv and a uv-managed Python (the version of `.python-version`) |
| `tools` | `scripts/fetch-tools.py` downloads the pinned FFmpeg of `tools/ffmpeg.toml`, checks its size and SHA-256 before it extracts anything, and runs `ffmpeg -version` and `ffprobe -version` |
| `app` | `uv sync --frozen` installs `reframe[cli,mediainfo]` and `reframe-server` from `uv.lock` into `/opt/reframe/venv` |

The runtime image is Debian 13 (trixie) slim with:

- the bundled FFmpeg in `/opt/reframe/tools/ffmpeg/`, where tool discovery finds it;
- `mkvtoolnix` (mkvpropedit) and `mediainfo` from Debian;
- the GPU user-space drivers that FFmpeg loads at run time: `mesa-va-drivers` (AMD and other
  Mesa VAAPI drivers), `intel-media-va-driver-non-free` (Intel VAAPI) and `libmfx-gen1.2`
  (the oneVPL GPU runtime for Intel QSV). The NVIDIA driver comes from the host, through the
  NVIDIA Container Toolkit;
- the web frontend in `/opt/reframe/frontend/` (`REFRAME_STATIC_DIR`);
- `tini` as process 1, and `reframe-entrypoint`, which starts the server as `PUID:PGID`.

Every package version and base image is pinned in the Dockerfile.

### Build

From the repository root:

```sh
docker build -f docker/Dockerfile -t reframe:local .
```

or `docker compose -f docker/compose.example.yml build`. The Dockerfile uses no BuildKit-only
syntax: it also builds with the classic builder (`DOCKER_BUILDKIT=0`, or a Docker without
buildx, where `docker compose build` uses the classic builder by itself).

### Run with Docker Compose

1. Copy `docker/compose.example.yml` to `docker/compose.yml` (its build context, `..`, is
   the repository) and change the host paths of the four folders:

   | In the container | What | Access |
   |------------------|------|--------|
   | `/config` | `settings.json`, `presets.json`, `auth.json` (the password hash) | read and write |
   | `/data` | the queue database, logs, `server.json`, the cache (`/data/cache`) | read and write |
   | `/media` | your videos | read only (`:ro`) |
   | `/output` | the encoded files | write |

   The image declares no `VOLUME`: mount all four. A folder that is not mounted is lost with
   the container.

2. Set `PUID` and `PGID` to the user and group that must own the files (`id -u`, `id -g`).
   The server runs as that user. At start, `/config` and `/data` are given to it
   (`chown -R`, only when the folder's owner is another one). `/media` and `/output` are not
   changed: that user must be able to read `/media` and write `/output`.

3. Start it, then set the login password:

   ```sh
   docker compose -f docker/compose.yml up -d
   docker compose -f docker/compose.yml exec -it reframe reframe-server --set-password
   ```

   The command asks twice. From a script, the first line of the input is the password:

   ```sh
   printf '%s\n' "$PASSWORD" | docker compose -f docker/compose.yml exec -T reframe \
       reframe-server --set-password
   ```

   `reframe-server` and `reframe` in the container run as `PUID:PGID` also through
   `docker exec`, so the server can read the file they write. A running server reads the
   new password at once; sessions that are open stay open until it restarts.

4. Open `http://<host>:8765/`. `GET /api/health` needs no login; the image's `HEALTHCHECK`
   calls it every 30 s.

`docker compose stop` stops a running encode and removes its partial file; the job is
`interrupted` at the next start. The CLI works in the container too, for example
`docker compose exec reframe reframe tools status`.

### What the image sets

| Variable | Value | Why |
|----------|-------|-----|
| `REFRAME_HOST`, `REFRAME_PORT` | `0.0.0.0`, `8765` | Reachable through the published port |
| `REFRAME_AUTH` | `password` | A server that binds another address than loopback refuses `auth: none` (exit 2) |
| `REFRAME_MEDIA_ROOTS` | `["/media"]` | The only folder the client may read |
| `REFRAME_OUTPUT_ROOTS` | `["/output"]` | The only folder the client may write; another output path is refused (`path.outside_roots`) |
| `REFRAME_CONFIG_DIR`, `REFRAME_DATA_DIR`, `REFRAME_CACHE_DIR` | `/config`, `/data`, `/data/cache` | |
| `REFRAME_STATIC_DIR` | `/opt/reframe/frontend` | The web UI |
| `PUID`, `PGID` | `1000` | The user the server runs as |

List values are JSON, because pydantic-settings reads lists from the environment as JSON:
`REFRAME_MEDIA_ROOTS='["/media", "/mnt/archive"]'`. A second media folder must also be
mounted. `auth: token` also works (`REFRAME_AUTH=token`, `REFRAME_TOKEN=<secret>`); without
`REFRAME_TOKEN` the token is new at each start.

**Host names.** Without `REFRAME_ALLOWED_HOSTS` the server accepts any IP address in the
browser's address bar (`http://192.168.1.10:8765/`) but no host name, against DNS rebinding.
To use a name (`http://nas.local:8765/`, or a reverse proxy's name), list it:
`REFRAME_ALLOWED_HOSTS='["nas.local", "192.168.1.10"]'`. A list replaces the default, so name
the IP addresses you use too. Loopback names always work.

### GPU

**Intel and AMD (VAAPI, QSV).** The `reframe` service of the compose example passes
`/dev/dri`. The entrypoint adds the server's user to the groups that own the device nodes
(the `render` group has another id on each host), so no `group_add` is needed. Without
`--user`, that is; when you start the container with `--user`, add the group yourself
(`--group-add $(getent group render | cut -d: -f3)`).

**NVIDIA (NVENC).** Install the NVIDIA Container Toolkit on the host, then start the other
service: `docker compose -f docker/compose.yml up -d reframe-nvidia`. It reserves the GPUs
with `deploy.resources.reservations.devices`; the image sets
`NVIDIA_DRIVER_CAPABILITIES=compute,video,utility`, so the toolkit mounts the encoder library.

**No GPU.** Delete the `devices` lines. The software encoders (x264, x265, SVT-AV1) work.

The hardware encoders show as available in Settings → Encoders after a test encode. Test
encodes run at the first start unless `encoders.hardware_tests` is off.

| Host | Status |
|------|--------|
| AMD, VAAPI | To be verified on the owner's desktop ([decision 0059](decisions/0059-s6-docker-image-and-bare-metal.md)) |
| Intel, VAAPI and QSV | Not verified: no such host yet ([decision 0043](decisions/0043-plan-review-before-m3.md) item 7) |
| NVIDIA, NVENC | Not verified: no such host yet (0043 item 7) |

### Your own FFmpeg in Docker

Mount the build and point `REFRAME_FFMPEG` at it. `ffprobe` next to it is found without
`REFRAME_FFPROBE`:

```sh
docker run … -v /opt/my-ffmpeg:/opt/custom-ffmpeg:ro \
    -e REFRAME_FFMPEG=/opt/custom-ffmpeg/bin/ffmpeg reframe:local
```

The compose example has the same lines, commented out. `reframe tools status` then shows
the origin `env`. A missing or broken override is shown as a problem; it is never replaced
by the bundled build without telling you.

### Rootless Docker and Podman

There the container's root is your own user on the host. Set `PUID=0` and `PGID=0`: the
entrypoint then starts the server without changing the user, and the files on the host
belong to you.

## Bare metal

### Install

From a checkout (the packages are not on PyPI yet):

```sh
uv tool install './packages/reframe[cli]' --with ./packages/reframe-server \
    --with-executables-from reframe-server
```

One tool environment holds both packages, so `reframe` and `reframe-server` always have the
same version ([decision 0042](decisions/0042-one-scheduler-process-and-cli-clients.md)
item 11). Once the packages are published, the command is
`uv tool install 'reframe[cli]' --with reframe-server --with-executables-from reframe-server`.
`uv tool install` resolves the newest allowed versions, not `uv.lock`. Add
`'./packages/reframe[cli,mediainfo]'` for MediaInfo bit rates (pymediainfo brings its own
library).

The wheels do not contain FFmpeg. Fetch the pinned build:

```sh
reframe tools fetch
```

It downloads the build of `tools/ffmpeg.toml`, checks its size and SHA-256, and installs it
in `<data dir>/tools/ffmpeg` (`~/.local/share/reframe/tools/ffmpeg`), where it counts as the
bundled build. `reframe tools status` shows what is used. Install `mkvtoolnix` and
`mediainfo` from your distribution. For VAAPI and QSV, install your distribution's VAAPI
driver and add your user to the `render` group.

The web UI is not in the wheel. Build it and put it where the server can find it:

```sh
cd frontend && npm ci && npm run build:web
cp -r dist ~/.local/share/reframe-web
```

### Set the password

```sh
reframe-server --set-password
```

It writes `~/.config/reframe/auth.json` (mode 0600).

### systemd user unit

`~/.config/systemd/user/reframe.service`:

```ini
[Unit]
Description=Reframe web server

[Service]
Type=exec
ExecStart=%h/.local/bin/reframe-server \
    --host 0.0.0.0 --port 8765 --auth password \
    --media-root /srv/media --output-root /srv/encoded
Environment=REFRAME_STATIC_DIR=%h/.local/share/reframe-web
# Exit code 2 is a configuration error: restarting does not help.
Restart=on-failure
RestartPreventExitStatus=2
TimeoutStopSec=30

[Install]
WantedBy=default.target
```

```sh
systemctl --user daemon-reload
systemctl --user enable --now reframe.service
loginctl enable-linger "$USER"     # keep it running when you are not logged in
journalctl --user -u reframe -f     # the server logs to stderr
```

`--media-root` and `--output-root` can be given more than once. A stop (SIGTERM) ends a
running encode and removes its partial file; the server ends with the signal, which systemd
counts as a clean stop. To bind only this machine (for a reverse proxy on the same host),
use `--host 127.0.0.1`; the default `auth` there is `none`, so keep `--auth password`.
Bound to `0.0.0.0`, the server also accepts this machine's own name (`nas`, `nas.local`)
in `Host` without `REFRAME_ALLOWED_HOSTS`.

The server also writes `<data dir>/server.json` (mode 0600, with a token for this run), so
the `reframe` CLI of the same user finds it.

### Windows

Run `reframe-server` from a terminal. A Windows service wrapper comes later.

## Reverse proxy

- **Site root only.** Reframe has no setting for a path prefix: serve it at the root of its
  own host name (`https://reframe.example.org/`), not under `/reframe/`.
- **Host name.** Add the proxy's public name to `REFRAME_ALLOWED_HOSTS` (or the systemd unit's
  environment), and let the proxy send the browser's `Host`. Without it every request through
  the proxy gets 400 `request.host`. The `Origin` of a page on an allowed host is accepted.
- **WebSocket.** `/api/events` is a WebSocket. The proxy must pass `Upgrade` and
  `Connection`. The server sends a heartbeat every 15 s, so the proxy's idle timeout must be
  longer than that (nginx's default of 60 s is enough).
- **Timeouts.** Long work is a background task (`202` and a task id), so no request waits
  for an encode. Preview frames of a 4K source can take some seconds on a slow
  machine: allow a few minutes (`proxy_read_timeout 300s`).
- **Body size.** A job is about 3–4 KB of JSON, so adding a whole batch to the queue can
  pass nginx's default limit of 1 MB. Allow more, for example `client_max_body_size 16m`.
- **Client address and HTTPS.** uvicorn reads `X-Forwarded-For` and `X-Forwarded-Proto` only
  from the addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`). Set it to the
  proxy's address or network when the proxy is not on the same host, for example
  `FORWARDED_ALLOW_IPS=172.16.0.0/12` for a proxy container on a Docker network. Then the
  login limit (5 wrong passwords per minute) counts each client, not the proxy, and the
  session cookie gets `Secure` behind HTTPS. Do not trust a network that clients can reach
  directly.

nginx:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name reframe.example.org;
    # ssl_certificate …

    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Caddy passes the WebSocket upgrade and `Host` by itself:

```caddy
reframe.example.org {
    request_body {
        max_size 16MB
    }
    reverse_proxy 127.0.0.1:8765
}
```
