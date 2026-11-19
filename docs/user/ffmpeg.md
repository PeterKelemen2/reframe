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
install, each with a short note on who it is for and its licence. Under **Source code and
archive** you find where its source code is, and the address (URL) and SHA-256 checksum of
its archive for your computer. You have three choices:

- **Download**: Reframe downloads the build you choose, checks it and installs it. This needs
  an internet connection.
- **Install from file**: choose the build in the list, then an FFmpeg archive of that build
  that you downloaded before, for example on another computer (see
  [Without internet](#without-internet)). Reframe checks the file against the build you chose
  in the same way as a download.
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
- **Download at start.** Set `REFRAME_FFMPEG_BUILD=default` (or `compat`). When the server
  finds no FFmpeg that works at start (none in `/data`, or only one on the `PATH` that is too
  old or does not run), it downloads that build, without a visit to the web UI. The download
  continues in the background; watch it with `docker logs`. The server does not download when
  `REFRAME_FFMPEG` / `REFRAME_FFPROBE` or a path in Settings → Tools is set (a download never
  replaces your own path, even one that does not work), or when another Reframe process uses
  the same data folder. The log then says why, and the first-run screen shows it.
- **Install from a file.** Put the archive into a folder that the container can read as a media
  folder (for example `/media`), then choose its build and use **Install from file** on the
  first-run screen or in Settings → Tools.
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

1. Find the download address (URL) of the build. The first-run screen and Settings → Tools
   show it with its SHA-256 checksum: open **Source code and archive** under the build. When
   a download cannot reach the internet, the message names the archive too. When
   `reframe tools fetch` cannot reach the internet, it prints it:

   ```text
   hint: download https://github.com/…/ffmpeg-….tar.xz on another computer, then run "reframe tools fetch --file ARCHIVE" here.
   ```

   The addresses and SHA-256 checksums of all builds are also in `tools/ffmpeg.toml` in
   Reframe's source code.
2. On a computer with internet, download the archive.
3. Copy the archive to the computer with Reframe.
4. Install it: choose its build in the list, then **Install from file** on the first-run
   screen or in Settings → Tools, or

   ```sh
   reframe tools fetch --file ffmpeg-….tar.xz
   ```

   The command finds the build by the name of the file. With another file name, name the
   build: `reframe tools fetch --file ARCHIVE --build compat`.

Reframe checks the size and the SHA-256 checksum of the file before it unpacks anything. A
file that is not the archive of the chosen build is refused, and the message says so, for
example:

```text
ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0.tar.xz is not the archive of the FFmpeg build 'compat' for linux-x64 (ffmpeg-n8.1.3-9-g29e619e767-linux64-gpl-shared-8.1.tar.xz), or it is damaged: the size is 68653636 bytes, expected 71911604
```

When a download cannot reach the internet, Reframe tells you so and offers these choices:
**Install from file** and your own FFmpeg. It also names the archive of the build, with its
address and SHA-256 checksum.

## Which build to choose

| Build | Choose it when |
|-------|----------------|
| **Recommended** (`default`) | Almost always. It is the build that Reframe is tested with. For NVIDIA hardware encoding (NVENC) it needs NVIDIA driver 610 or newer. |
| **Compatibility** (`compat`) | Your NVIDIA driver is 570 to 609, for example a GeForce 10 series card (GTX 1050, 1060, 1070, 1080) with driver 580, its last driver series. It is an older FFmpeg version. For NVENC it needs NVIDIA driver 570 or newer. |

If you are not sure, take **Recommended**. If Reframe then shows the warning below for an
NVIDIA encoder, change to **Compatibility**.

With an NVIDIA driver older than 570, no build can use NVENC. For example, Debian 13 has
driver 550. Update the driver to 570 or newer, or use your own FFmpeg that was built for your
driver.

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

When the **Compatibility** build already shows this warning, no other build helps, and the
hint says so: update the driver, or use your own FFmpeg.

An encoder that works only in 8-bit is not this warning: you can still use it for 8-bit video.

## "Every NVENC session of the GPU is in use"

A GeForce card runs only a few NVENC encodes at the same time, for all programs together.
When other programs (for example a media server that transcodes) use all of them, Reframe
cannot check its NVIDIA encoders. It tries again a few times, and then shows the encoder as
"could not be checked" with this reason. A job that starts at that moment fails with the same
reason. When the other encodes finish, click **Check again** in Settings → Tools, or run
`reframe encoders` again, and run the job again.

## After an app update

A new version of Reframe can expect a newer FFmpeg build. Settings → Tools then says: "This
release pins another version of the build …". The button next to it, for example **Download
Recommended**, installs the new one. Your old build keeps working until you do.
`reframe tools status` says the same, and the server log has a warning at start (below).

## What the server log says

The server writes these lines to its console (`docker logs`, or the systemd journal), not only
to its log file. The examples are copied from a real server; its data folder is written as
`/data`, as in Docker. The versions and paths may differ.

- **At start without FFmpeg**, a warning that Reframe cannot encode yet, with the reason and
  the ways out:

  ```text
  WARNING:  Reframe cannot encode yet: no usable FFmpeg (ffmpeg: ffmpeg was not found: no bundled build, nothing on PATH. Set its path in Settings or REFRAME_FFMPEG, or run `reframe tools fetch`; ffprobe: ffprobe was not found: no bundled build, nothing on PATH. Set its path in Settings or REFRAME_FFPROBE, or run `reframe tools fetch`). Ways out: open the web UI and download a build on its first-run screen; or set REFRAME_FFMPEG_BUILD=default to download one at start; or mount your own build and set REFRAME_FFMPEG (and REFRAME_FFPROBE).
  ```

  When `REFRAME_FFMPEG_BUILD` is set, the warning does not suggest it again.
- **With `REFRAME_FFMPEG_BUILD`**, one line says what the server does with it:

  ```text
  INFO:     REFRAME_FFMPEG_BUILD=default: no usable FFmpeg found, so the download of the FFmpeg build 'default' starts (task t-4763b6-1)
  INFO:     REFRAME_FFMPEG_BUILD=default: FFmpeg is found, so nothing is downloaded
  ```

  When it downloads nothing for another reason, a warning says why. The first-run screen shows
  the same problem:

  ```text
  WARNING:  REFRAME_FFMPEG_BUILD=Default names no offered FFmpeg build (the offered builds: default, compat), so nothing is downloaded
  WARNING:  REFRAME_FFMPEG_BUILD=default: nothing is downloaded, because the FFmpeg path comes from REFRAME_FFMPEG. A download never replaces a path set in the environment or in Settings → Tools. Correct or remove that path.
  WARNING:  REFRAME_FFMPEG_BUILD=default: nothing is downloaded, because another Reframe process uses this data folder. Let the process that owns the data folder download it, or download a build on the web UI's first-run screen.
  ```

- **When a download or file install starts**, one line with the build, its version, platform
  and size, where it comes from, the folder, the licence and the source code:

  ```text
  INFO:     FFmpeg build 'default' (n9.0.2-17-g2a571b6068-20260930, linux-x64, 65.5 MiB): installing from https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0.tar.xz into /data/tools/ffmpeg. Licence GPL-3.0-or-later; source: https://github.com/FFmpeg/FFmpeg/commit/2a571b606854520cf89804d8030c8b328e621689
  ```

- **During the transfer**, at most every 10 %:

  ```text
  INFO:     FFmpeg build 'default': downloaded 40 % (26.2 MiB of 65.5 MiB)
  ```

  (`copied` instead of `downloaded` for a file install.)
- **At the end**, the result:

  ```text
  INFO:     Installed FFmpeg build 'default' (n9.0.2-17-g2a571b6068-20260930) into /data/tools/ffmpeg; checked: the size and SHA-256 of the archive, ffmpeg -version and ffprobe -version
  ```

  or an error line with the reason. When the server could not reach the internet, the line
  ends with the other choices:

  ```text
  ERROR:    FFmpeg download of build 'default' failed: cannot reach the download server github.com (Connection refused; 4 attempt(s)). Without a connection, install the build from its archive file (downloaded on another computer), or use an FFmpeg that is already on this computer (its path in Settings > Tools, or REFRAME_FFMPEG and REFRAME_FFPROBE).
  ```

  When the download was the one of `REFRAME_FFMPEG_BUILD`, one more line follows:

  ```text
  WARNING:  REFRAME_FFMPEG_BUILD=default: the download failed, so Reframe cannot encode yet (the download's error line says why)
  ```

- **When the build is already installed and intact**:

  ```text
  INFO:     FFmpeg build 'default' (n9.0.2-17-g2a571b6068-20260930) is already installed in /data/tools/ffmpeg and every file is intact: nothing to do
  ```

- **At start with an outdated build**:

  ```text
  WARNING:  The downloaded FFmpeg build 'default' (version n9.0.1-1-gdeadbeef-20260801) is not the one this release pins: download it again (the web UI's Settings → Tools, or reframe tools fetch --build default). It keeps working until then.
  ```
