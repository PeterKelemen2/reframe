# Getting FFmpeg

Reframe uses FFmpeg to read and encode your videos. Reframe does not contain FFmpeg: you get it
once, the first time you use Reframe. This page tells you how.

## Why Reframe downloads FFmpeg

- One FFmpeg build does not fit every computer. For example, the newest build needs a newer
  NVIDIA driver than older graphics cards can get. You choose the build that fits your
  computer.
- The download is a known build. Reframe checks its size and checksum before it installs it,
  and it is the build that Reframe is tested with.
- The app and its installers are much smaller.

You can also use your own FFmpeg build instead.

## The desktop app: the first start

When the app finds no FFmpeg, it shows the first-run screen. It lists the builds you can
install, each with a short note on who it is for, its licence and where its source code is.
You have three choices:

- **Download**: Reframe downloads the build you choose, checks it and installs it. This needs
  an internet connection.
- **Install from file**: choose an FFmpeg archive that you downloaded before, for example on
  another computer (see [Without internet](#without-internet)). Reframe checks it in the same
  way as a download.
- **Choose path**: use your own FFmpeg. Settings → Tools opens, where you set the path to your
  `ffmpeg` program. Reframe finds `ffprobe` in the same folder.

Until FFmpeg is installed, you can look at presets and settings, but you cannot encode.

On Linux, the app also puts its own copy of the VA-API library (libva) into the build that it
installs, so that hardware encoding with VAAPI works on older distributions too.

## Docker

The Docker image does not contain FFmpeg. Reframe downloads it into the data folder,
`/data/tools/ffmpeg/`, when you ask it to (below).

- **Keep `/data` persistent.** Mount a folder of the host at `/data` (the example
  `compose.example.yml` does this). If `/data` is empty or deleted, the next start must download
  FFmpeg again.
- **Download from the web UI.** Open Reframe in your browser. The first-run screen offers the
  download.
- **Download at start.** Set `REFRAME_FFMPEG_BUILD=default` (or `compat`). When no FFmpeg is
  installed in `/data`, the server downloads that build at start, without a visit to the web UI.
  The download continues in the background; watch it with `docker logs`.
- **Install from a file.** Put the archive into a folder that the container can read as a media
  folder (for example `/media`), then use **Install from file** on the first-run screen or in
  Settings → Tools.
- **Your own build.** Mount it into the container and set `REFRAME_FFMPEG` (and
  `REFRAME_FFPROBE` if it is not next to `ffmpeg`):

  ```sh
  docker run … -v /opt/my-ffmpeg:/opt/custom-ffmpeg:ro \
      -e REFRAME_FFMPEG=/opt/custom-ffmpeg/bin/ffmpeg reframe:local
  ```

For hardware encoding in Docker, see [Deployment → GPU](../deployment.md#gpu).

## A server without Docker

Install FFmpeg with the `reframe` command:

```sh
reframe tools fetch                    # the default build
reframe tools fetch --build compat     # the compatibility build
reframe tools status                   # what Reframe uses now
```

The build goes into Reframe's data folder (on Linux `~/.local/share/reframe/tools/ffmpeg/`).
For VAAPI on Linux, your distribution's libva must be new enough for the build. If it is not,
`reframe encoders` tells you (see [The "needs newer system software" warning](#the-needs-newer-system-software-warning)).

## Without internet

1. Find the download address (URL) of the build. When `reframe tools fetch` cannot reach the
   internet, it prints it:

   ```text
   hint: download https://github.com/…/ffmpeg-….tar.xz on another computer, then run "reframe tools fetch --file ARCHIVE" here.
   ```

   The addresses and SHA-256 checksums of all builds are in `tools/ffmpeg.toml` in Reframe's
   source code.
2. On a computer with internet, download the archive. Keep its file name: Reframe finds the
   build by the name of the file.
3. Copy the archive to the computer with Reframe.
4. Install it: **Install from file** on the first-run screen or in Settings → Tools, or

   ```sh
   reframe tools fetch --file ffmpeg-….tar.xz
   ```

   With another file name, name the build: `reframe tools fetch --file ARCHIVE --build compat`.

Reframe checks the size and the SHA-256 checksum of the file before it unpacks anything. A
file that is not one of Reframe's builds is refused.

When a download cannot reach the internet, Reframe tells you so and offers these choices:
**Install from file** and your own FFmpeg.

## Which build to choose

| Build | Choose it when |
|-------|----------------|
| **Recommended** (`default`) | Almost always. It is the build that Reframe is tested with. For NVIDIA hardware encoding (NVENC) it needs NVIDIA driver 610 or newer. |
| **Compatibility** (`compat`) | You have an NVIDIA card whose newest driver is older than 610, for example a GeForce 10 series card (GTX 1050, 1060, 1070, 1080) or older. It is an older FFmpeg version. |

If you are not sure, take **Recommended**. If Reframe then shows the warning below for an
NVIDIA encoder, change to **Compatibility**.

## The "needs newer system software" warning

Sometimes an encoder is in the FFmpeg build, but your computer cannot use it with this build:
for example, the NVIDIA driver is older than the build needs. Reframe then shows the encoder as
unavailable, with the reason and a warning that the build needs newer system software.

What to do:

- Update the driver, if your graphics card can get a newer one, or
- Use another build: **Use another FFmpeg…** on the Video tab opens Settings → Tools, where you
  can install the other build, install a build from a file, or set your own path. On the
  command line: `reframe tools fetch --build compat`, or set `REFRAME_FFMPEG`.

`reframe encoders` and `reframe tools status` print the same advice as a `hint:` line, for
example:

```text
hint: hevc_nvenc needs newer system software than this FFmpeg build expects: update the driver, or use another build (reframe tools fetch --build compat, or REFRAME_FFMPEG / tools.ffmpeg).
```

An encoder that works only in 8-bit is not this warning: you can still use it for 8-bit video.

## After an app update

A new version of Reframe can expect a newer FFmpeg build. Settings → Tools then says: "This
release pins another version of the build …". **Download** installs the new one. Your old build
keeps working until you do. `reframe tools status` says the same, and the server log has a
warning at start (below).

## What the server log says

The server writes these lines to its console (`docker logs`, or the systemd journal), not only
to its log file. The examples are from a server in Docker; the versions and paths may differ.

- **At start without FFmpeg**, a warning that Reframe cannot encode yet, with the reason and
  the ways out:

  ```text
  WARNING:  Reframe cannot encode yet: no usable FFmpeg (ffmpeg: ffmpeg was not found: …; ffprobe: …). Ways out: open the web UI and download a build on its first-run screen; or set REFRAME_FFMPEG_BUILD=default to download one at start; or mount your own build and set REFRAME_FFMPEG (and REFRAME_FFPROBE).
  ```

- **With `REFRAME_FFMPEG_BUILD`**, the server says that it starts the download:

  ```text
  INFO:     REFRAME_FFMPEG_BUILD: no FFmpeg found, so the download of the FFmpeg build 'default' starts (task t-…)
  ```
- **When a download or file install starts**, one line with the build, its version, platform
  and size, where it comes from, the folder, the licence and the source code:

  ```text
  INFO:     FFmpeg build 'default' (n9.0.2-…, linux-x64, 68.7 MB): installing from https://github.com/… into /data/tools/ffmpeg. Licence GPL-3.0-or-later; source: https://github.com/FFmpeg/FFmpeg/commit/…
  ```

- **During the transfer**, at most every 10 %:

  ```text
  INFO:     FFmpeg build 'default': downloaded 40 % (27.5 MB of 68.7 MB)
  ```

  (`copied` instead of `downloaded` for a file install.)
- **At the end**, the result:

  ```text
  INFO:     Installed FFmpeg build 'default' (n9.0.2-…) into /data/tools/ffmpeg; checked: the size and SHA-256 of the archive, ffmpeg -version and ffprobe -version
  ```

  or an error line with the reason, for example
  `FFmpeg download of build 'default' failed: …`. When the server could not reach the internet,
  the line ends with the other choices: *Without a connection, install the build from its
  archive file (downloaded on another computer), or use an FFmpeg that is already on this
  computer (its path in Settings > Tools, or REFRAME_FFMPEG and REFRAME_FFPROBE).*
- **When the build is already installed and intact**:
  `FFmpeg build 'default' (…) is already installed in /data/tools/ffmpeg and every file is intact: nothing to do`.
- **At start with an outdated build**:

  ```text
  WARNING:  The downloaded FFmpeg build 'default' (version n9.0.1-…) is not the one this release pins: download it again (the web UI's Settings → Tools, or reframe tools fetch --build default). It keeps working until then.
  ```
