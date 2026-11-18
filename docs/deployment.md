# Deployment

How to run the Reframe web server on a NAS or a home server: in Docker, or on bare metal
with a systemd user unit, and behind a reverse proxy. Reframe is not published yet (no image
on a registry, no wheel on PyPI), so every way below starts from a checkout of this
repository. The choices are recorded in
[decision 0059](decisions/0059-s6-docker-image-and-bare-metal.md).

## Docker

### What the image holds

`docker/Dockerfile` builds one image for `linux/amd64` or `linux/arm64` in four stages:

| Stage | What it does |
|-------|--------------|
| `notices` | Checks that `docker/notices/THIRD_PARTY_NOTICES` is there and is the one for the image's platform (`docker-linux-x64` or `docker-linux-arm64`) |
| `frontend` | `npm ci` and `npm run build:web` (Node 24) |
| `python` | uv and a uv-managed CPython 3.14.8 (`.python-version` names 3.14, the version CI tests) |
| `app` | `uv sync --frozen` installs `reframe[cli]` and `reframe-server` from `uv.lock` into `/opt/reframe/venv` |

The runtime image is Debian 13 (trixie) slim. It contains **no FFmpeg**: the first start
downloads it into `/data/tools/ffmpeg/` (see [Getting FFmpeg](user/ffmpeg.md#docker)). It has:

- on `linux/amd64` only, the GPU user-space drivers that a downloaded FFmpeg loads at run time,
  with Debian's libva:
  `mesa-va-drivers` (AMD and other Mesa VAAPI drivers), `intel-media-va-driver-non-free`
  (Intel VAAPI) and `libmfx-gen1.2` (the oneVPL GPU runtime for Intel QSV). The NVIDIA driver
  comes from the host, through the NVIDIA Container Toolkit. The `linux/arm64` image has no GPU
  drivers: it has the software encoders only (see [GPU](#gpu));
- in `/opt/reframe/notices/`: `THIRD_PARTY_NOTICES` (the licence texts, and at its end the
  copyright file of each Debian package in the image, added during the build) and
  `DEBIAN_PACKAGES`, written during the build: each Debian package in
  the image with its version, its source package and version, and that source on
  [snapshot.debian.org](https://snapshot.debian.org/), which keeps every Debian source version;
- the web frontend in `/opt/reframe/frontend/` (`REFRAME_STATIC_DIR`);
- `tini` as process 1, and `reframe-entrypoint`, which starts the server as `PUID:PGID`.

The base images are pinned by tag and digest, the Debian packages that the Dockerfile names
by exact version, the Python packages by `uv.lock` and the npm packages by
`package-lock.json`. The dependencies of those Debian packages are not pinned: they come from
the Debian archive on the day of the build.

### Build

From the repository root, first write the notices for the platform of the image
(`docker-linux-x64`, or `docker-linux-arm64` on an arm64 host), then build. The notices take
the frontend's licences from `frontend/node_modules` and the CPython licence from the
interpreter that runs the script, which must be the image's (`--python`):

```sh
(cd frontend && npm ci)
uv run --python 3.14.8 --with pip-licenses==5.5.5 python scripts/third-party-notices.py \
    --platform docker-linux-x64 --out docker/notices/THIRD_PARTY_NOTICES
docker build -f docker/Dockerfile -t reframe:local .
```

or `docker compose -f docker/compose.example.yml build` for the second line. Without the
notices, or with the notices of the other platform, the build stops at the `notices` stage
and says so. The Dockerfile uses no BuildKit-only syntax: it also builds with the classic
builder (`DOCKER_BUILDKIT=0`, or a Docker without buildx, where `docker compose build` uses the
classic builder by itself). It then builds for the architecture of the host. With buildx,
`--platform linux/arm64` builds the arm64 image (buildx's `TARGETARCH`); build one platform at a
time, each with its own notices.

### Run with Docker Compose

1. Copy `docker/compose.example.yml` to `docker/compose.yml` (its build context, `..`, is
   the repository) and change the host paths of the four folders:

   | In the container | What | Access |
   |------------------|------|--------|
   | `/config` | `settings.json`, `presets.json`, `auth.json` (the password hash) | read and write |
   | `/data` | the queue database, logs, `server.json`, the cache (`/data/cache`), the downloaded FFmpeg (`/data/tools/ffmpeg`) | read and write |
   | `/media` | your videos | read only (`:ro`) |
   | `/output` | the encoded files | write |

   The image declares no `VOLUME`: mount all four. A folder that is not mounted is lost with
   the container.

   Make the host folders before the first start, as the user of `PUID:PGID` (or `chown`
   them to it). Docker makes a missing folder as `root`, and then the server cannot write to
   `/output`: each job fails with `output.not_writable`.

   ```sh
   mkdir -p /srv/reframe/config /srv/reframe/data /srv/encoded
   ```

   The example publishes port 8765 on every address of the host. Docker's published ports
   pass by host firewalls such as ufw (Docker's
   [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)),
   so the port is open to every network that the host is on. To limit it, publish on one
   address: `192.168.1.10:8765:8765` for one LAN address, `127.0.0.1:8765:8765` for a
   reverse proxy on the host ([Reverse proxy in Docker](#reverse-proxy-in-docker)).

2. Set `PUID` and `PGID` to the user and group that must own the files (`id -u`, `id -g`).
   The server runs as that user. At start, `/config` and `/data` are given to it
   (`chown -R`, only when the folder's owner is another one). `/media` and `/output` are not
   changed: that user must be able to read `/media` and write `/output`.

   With `docker run --user` (or `user:` in compose) the entrypoint changes nothing, so
   `/config` and `/data` must already be writable by that user. If `/data` is not, the
   server starts and the container is `healthy`, but it saves no job.

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

5. Get FFmpeg: the first-run screen offers the download (or **Install from file** with an
   archive in `/media`). Or set `REFRAME_FFMPEG_BUILD: default` in the compose file, and the
   server downloads it at start when `/data` has none. The download stays in `/data`, so keep
   that folder: [Getting FFmpeg](user/ffmpeg.md#docker).

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

The `HEALTHCHECK` calls the port of `REFRAME_PORT`. To change the port in the container, set
`REFRAME_PORT`, not `--port` in the command: with `--port` the container becomes
`unhealthy`. To use another port on the host, change only the published one (`9000:8765`).

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

**arm64.** The `linux/arm64` image has the software encoders only: it has no VAAPI drivers, and
no QSV or NVENC is claimed for it. Delete the `devices` lines and use the `reframe` service.

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
by the downloaded build without telling you.

### Rootless Docker and Podman

There the container's root is your own user on the host. Set `PUID=0` and `PGID=0`: the
entrypoint then starts the server without changing the user, and the files on the host
belong to you.

In rootful Docker, `PUID=0` runs the server as the host's root, with every capability that
Docker gives the container. The entrypoint warns: `PUID=0 runs the server as root on the
host`. It knows rootful Docker from the container's user map, which maps each id to itself.

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
`uv tool install` resolves the newest allowed versions, not `uv.lock`.

The wheels do not contain FFmpeg. Fetch the pinned build:

```sh
reframe tools fetch                       # the default build; --build compat for older NVIDIA drivers
reframe tools fetch --file ARCHIVE        # an archive downloaded on another computer
```

It downloads the build of `tools/ffmpeg.toml` (or takes the file), checks its size and
SHA-256, and installs it in `<data dir>/tools/ffmpeg` (`~/.local/share/reframe/tools/ffmpeg`),
where it counts as the bundled build. `reframe tools status` shows what is used. Reframe needs
no other tool: it writes Matroska headers and estimates bit rates itself. For VAAPI and QSV,
install your distribution's VAAPI driver and add your user to the `render` group; the build
then uses your distribution's libva, and `reframe encoders` says when it is too old for the
build. [Getting FFmpeg](user/ffmpeg.md) has the choices and the warnings for users.

The web UI is not in the wheel. Build it and put it where the server can find it:

```sh
cd frontend && npm ci && npm run build:web
rm -rf ~/.local/share/reframe-web && cp -r dist ~/.local/share/reframe-web
```

Remove the old folder first: when the target folder exists, `cp -r` copies into
`reframe-web/dist/`, and the server keeps the old UI.

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
- **Client address and HTTPS.** The login limit (5 wrong passwords per minute) counts each
  client address, and the session cookie gets `Secure` only over HTTPS. Behind a proxy the
  server sees the proxy's address and plain HTTP, unless it reads the proxy's
  `X-Forwarded-For` and `X-Forwarded-Proto`. uvicorn reads them only from the addresses in
  `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`). Trust the proxy's own address, and no
  other:
  - When the server does not trust the proxy, all clients share one login limit: five wrong
    passwords from anyone lock out everyone for a minute, the owner too. The cookie gets no
    `Secure` behind HTTPS.
  - When the server trusts an address that a client can connect from, that client names any
    address in `X-Forwarded-For`, a new one for each try, so the limit never stops it. With
    `X-Forwarded-Proto: https` it gets a `Secure` cookie over plain HTTP.

  On bare metal with the proxy on the same host, the default is correct: the proxy connects
  from 127.0.0.1. For a proxy on another machine, set `FORWARDED_ALLOW_IPS` to its address.
  In Docker the default does not apply: see [Reverse proxy in Docker](#reverse-proxy-in-docker).

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
        # A proxy container on the compose network: proxy_pass http://reframe:8765;
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

### Reverse proxy in Docker

In a container the proxy does not connect from 127.0.0.1, so the server trusts no proxy until
you set `FORWARDED_ALLOW_IPS`. Set it to the one address that the proxy connects from, and
keep every other client away from the server's port. Do not trust a range, such as
`172.16.0.0/12`: then the host and the containers in that range can name any client. Use one
of these two set-ups in `docker/compose.yml`. The subnet `172.30.87.0/24` is an example: use
one that no other network of the host uses (`ip route`, `docker network inspect`). A fixed
subnet keeps the trusted address the same when Compose makes the network again
(`docker compose down` removes it).

**A proxy on the Docker host** (nginx or Caddy installed on the host,
`proxy_pass http://127.0.0.1:8765`). Publish the port on 127.0.0.1 only, and trust the
gateway of the network: a connection from the host to a published port comes from the
gateway.

```yaml
x-reframe: &reframe
  # … the rest of the example
  ports:
    - "127.0.0.1:8765:8765"
  environment:
    FORWARDED_ALLOW_IPS: "172.30.87.1"
    REFRAME_ALLOWED_HOSTS: '["reframe.example.org"]'
    # … PUID, PGID, TZ

networks:
  default:
    ipam:
      config:
        - subnet: 172.30.87.0/24
          gateway: 172.30.87.1
```

A client on the LAN cannot reach the port. Each process on the host can connect from the
gateway and so name any client, as on bare metal from 127.0.0.1. Do not publish the port on
another address while the gateway is trusted: every connection that Docker's port
forwarding passes on, over IPv6 for example, also comes from the gateway.

**A proxy container in the same compose file.** Delete the `ports` lines of the Reframe
services: only the proxy publishes a port. Give the proxy a fixed address and trust that
address. `ip_range` keeps the addresses that Docker gives out by itself in the upper half of
the subnet, so no other container gets the proxy's address.

```yaml
x-reframe: &reframe
  # … the rest of the example, with no ports
  environment:
    FORWARDED_ALLOW_IPS: "172.30.87.10"
    REFRAME_ALLOWED_HOSTS: '["reframe.example.org"]'
    # … PUID, PGID, TZ

services:
  # … reframe and reframe-nvidia as in the example

  proxy:
    image: nginx:1.31.8-alpine-slim
    restart: unless-stopped
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /srv/reframe/certs:/etc/nginx/certs:ro
    networks:
      default:
        ipv4_address: 172.30.87.10

networks:
  default:
    ipam:
      config:
        - subnet: 172.30.87.0/24
          ip_range: 172.30.87.128/25
          gateway: 172.30.87.1
```

Name the gateway: with `ip_range` and no `gateway`, Docker takes the first address of the
range. In `nginx.conf` the `proxy_pass` is `http://reframe:8765`. The host connects to the
server from the gateway and the other containers from their own addresses: the server
ignores their `X-Forwarded-*` headers. The proxy sees the clients that reach it over
IPv6, or from the host, at the gateway's address too, so they share one login limit.
