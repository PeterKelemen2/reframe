# 0101 — NVENC session limit, and a build hint that names only an older FFmpeg

- Status: accepted
- Date: 2026-11-19
- Steps: C-4, C-11, C-21

## Context

The Linux NVENC host is Debian 13 with a GeForce GTX 1050 Ti (Pascal), set up on 2026-11-19.
Details are in `testdata/README.md` ("The NVENC minimum driver of each offered build", "NVENC
session limit (GeForce)").

| Item | Version |
|------|---------|
| Machine | 20 threads, 7.6 GB, kernel 6.12.117+deb13-amd64; a home server (Jellyfin uses the GPU) |
| Driver | Debian's 550.163.01 at first, then NVIDIA's 580.159.04 (`.run`, DKMS, proprietary module) |
| FFmpeg | `compat` n8.1.3-9-g29e619e767-20260930 (bundled), `default` n9.0.2-17-g2a571b6068-20260930 |

Three problems came up:

1. **Busy GPU reported as "no GPU".** `pytest -m needs_gpu` failed now and then (3 runs out of
   4 under xdist, never with `-n 0`): `test_the_facade_caches_the_real_result` saw
   `hevc_nvenc` (once `h264_nvenc`) as unavailable in one detection and available in the
   next. The reason was "No NVIDIA GPU that can encode H.265". A GeForce card runs 8 NVENC
   sessions at once. The 9th fails with `OpenEncodeSessionEx failed: incompatible client key
   (21)`, and then `No capable devices found` (FFmpeg skips the GPU). The rule for "No capable
   devices found" came before the session-error rule, so the summary line won over the cause.
   On a real computer, the same thing happens when a media server (Jellyfin here) or other
   encodes hold every session while Reframe detects. The encoder then stays "unavailable",
   with a false reason, until the next detection. A job that starts at that moment fails
   with "OpenEncodeSessionEx failed: incompatible client key (21): (no details); Error while
   opening encoder - maybe incorrect parameters …".
2. **The hint suggested a build that needs a newer driver.** With `compat` in use and driver
   550, `reframe encoders` said "update the driver, or use another build (reframe tools fetch
   --build default …)". The `default` build needs driver 610, and `compat` needs 570 (the
   source of both pinned commits, `libavcodec/nvenc.c`). `other_build()` took any offered
   build other than the one in use.
3. **The `compat` summary gave no lower limit.** It said "for NVIDIA drivers older than 610
   (GeForce 10 series and older)". Driver 550 (Debian 13's own) is older than 610, but
   `compat` cannot use NVENC with it.

## Decision

1. **Session errors before "No capable devices found"; status 21 is "busy".** The
   `OpenEncodeSessionEx failed` rules come before the "No capable devices found" rule. Status
   21 gives `Failure.busy` with state `error` (the check could not be done), never
   `unavailable`. The reason is "Every NVENC session of the GPU is in use by other programs
   (GeForce cards run only a few at once). Check the encoders again when they finish". It is
   not a build mismatch. Other session statuses keep "NVENC could not open an encoding
   session (…)" as `unavailable`.
2. **A busy test runs again.** Detection runs a busy test encode again up to two times, after
   2 s and then 4 s (`DetectionOptions.busy_retries`, `busy_wait`). The wait is outside the
   parallel limit of 3 tests. A short burst of other encodes (a parallel test run, the end
   of a transcode) then gives the right result. A GPU that stays busy costs at most about
   6 s more per test.
3. **Jobs:** `stderr_reason()` knows the status-21 line: "Every NVENC session of the GPU is in
   use by other programs (GeForce cards run only a few at once). Run the job again when they
   finish."
4. **The driver hint names only an older FFmpeg.** A newer FFmpeg release never lowers the
   NVENC driver requirement. So `other_build()` takes the newest offered build whose
   `release_version` is lower than that of the downloaded build in use. When there is none,
   the hint says: "update the driver (no offered build works with an older one), or use your
   own FFmpeg (REFRAME_FFMPEG / tools.ffmpeg)". With an FFmpeg that is not a downloaded
   build, the hint still names `compat` (unchanged).
5. **Texts.** The `compat` summary is "FFmpeg 8.1, for NVIDIA drivers 570 to 609, such as a
   GeForce 10 series card with driver 580. Checked with drivers 582.78 and 580.159."
   `docs/user/ffmpeg.md` gives the 570 floor. It says that an older driver (Debian 13's 550)
   gets NVENC from no build, and it explains the busy reason.

## Consequences

- A busy GPU is shown as "could not be checked" with a cause that the user can act on.
  Validation blocks `error` encoders like `unavailable` ones and offers the closest available
  encoder. After the other encodes end, *Check again* (Settings → Tools) or the next start
  gives the real result.
- A 10-bit test that stays busy after its retries gives `supports_10bit` false with the busy
  reason in `reason_10bit`, until the next detection.
- Only status 21 is verified as the session limit (driver 580, Linux). Older drivers are
  reported to use `out of memory (10)` for it. That is not verified, so it stays a plain
  session error (`unavailable`), but with the session error as the reason, not "no GPU".
  Windows is not checked.
- `needs_gpu` tests that encode with NVENC in parallel can still reach the limit for longer
  than the retries wait. On this host, five runs in a row passed after the change (see the
  commit).
- Debian 13 users with the distribution driver (550) get NVENC from no offered build. A third
  build with NVENC API 12.2 (driver 550.54.14 on Linux) is not offered. This is revisited if
  users ask for it.

## Plan changes

`05-core.md`: C-4 has a new "Busy GPU" item; the C-21 CLI item says which build the driver
hint names.
