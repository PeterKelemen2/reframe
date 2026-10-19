# 0008 — Encoder detection: real failure texts, the filter list, cache and issue details

- Status: accepted
- Date: 2026-10-13
- Steps: C-4, C-7, C-8, C-11

## Context

05 §C-4 says how to map a failed hardware test encode to a reason:

> `MFX_ERR_UNSUPPORTED` → "Intel QSV not supported on this GPU". Unknown patterns keep the
> last stderr line.

Real FFmpeg n9.0.2 (the pinned BtbN build and the Arch package) shows that this cannot work
(`testdata/README.md` §Hardware encoder failures and §Encoder detection; the stderr texts are
in `testing/reframe_testing/fake_data/detect_*.stderr.txt` and `hw_*.stderr.txt`):

1. **`MFX_ERR_UNSUPPORTED` is never printed.** The string is not in the build at all
   (`library_strings.json`). oneVPL errors print a number: `[hevc_qsv @ 0x…] Error creating a
   MFX session: -9.` With the QSV setup of the definitions (`-init_hw_device qsv=hw`) FFmpeg
   fails while it parses the global options and names no device:

   ```console
   $ ffmpeg -hide_banner -nostdin -init_hw_device qsv=hw -filter_hw_device hw -f lavfi \
       -i color=size=640x360 -frames:v 3 -vf format=nv12,hwupload=extra_hw_frames=64,format=qsv \
       -c:v hevc_qsv -f null -          # exit 187, no Intel GPU
   Device creation failed: -542398533.
   Failed to set value 'qsv=hw' for option 'init_hw_device': Generic error in an external library
   Error parsing global options: Generic error in an external library
   ```

2. **The last stderr line says nothing.** It is `Conversion failed!` when the encoder cannot
   open, `Nothing was written into output file, …` with `-v error`, and `Error parsing global
   options: <strerror>` when a hardware device cannot be created. The useful line is the one
   that the encoder (`[hevc_nvenc @ 0x…] Cannot load libcuda.so.1`) or the device (`[VAAPI @
   0x…] No VA display found for device /dev/dri/renderD999.`, `[AMF @ 0x…] DLL
   libamfrt64.so.1 failed to open`) logs.

3. C-7 must choose `libplacebo` or `zscale,tonemap` (03 §Filters) and needs to know which
   filters the build has. The plan gives no step that reads the filter list.

4. The plan does not say what a detection does when the cache already has a result, what
   happens to a hardware encoder that was not tested (Settings: hardware tests off), or which
   severity the `encoder.checking` issue has (03: "Queueing waits until the encoder's status is
   known").

## Decision

### 1. Reason mapping

`reframe.capabilities.reasons.explain_failure()` maps the texts that FFmpeg really prints.
The first rule that matches any line wins; a match gives the state `unavailable`:

| Text (as printed) | Reason |
|-------------------|--------|
| `Driver does not support the required nvenc API version. Required: A Found: B` (+ `The minimum required Nvidia driver for nvenc is V or newer`) | NVIDIA driver too old: NVENC needs driver V or newer |
| `Cannot load libcuda.so.1` / `Cannot load nvcuda.dll` | NVIDIA driver not found |
| `No CUDA capable devices found` | No NVIDIA GPU found |
| `No capable devices found` (NVENC) | No NVIDIA GPU that can encode H.265 |
| `Codec not supported` (NVENC) | This NVIDIA GPU cannot encode AV1 |
| `OpenEncodeSessionEx failed: …` | NVENC could not open an encoding session (…) |
| `10 bit encode not supported` (NVENC) | 10-bit is not supported by this GPU |
| `Error creating / initializing / querying a(n) MFX session` | No Intel QSV device (needs an Intel GPU with its media driver) |
| `No VA display found for device X.` / `… for any default device.` / `Failed to create a VAAPI device` | No VAAPI device (X) |
| `Failed to initialise VAAPI connection: N (E).` | VAAPI driver failed to start on X (E) |
| `DLL libamfrt64.so.1 failed to open` | AMD AMF runtime not found (libamfrt64.so.1) |
| `10-bit encoder is not supported by AMD GPU drivers versions lower than V.` | AMD driver too old for 10-bit (needs V or newer) |
| `10-bit input video is not supported by AMF H264 encoder` | 10-bit is not supported by this encoder |
| `Failed to create  hardware device context (AMF) : E` | AMD AMF could not start (E) |
| `Failed to set value 'V' for option 'init_hw_device'` (or `vaapi_device`), no line above | QSV: No Intel QSV device …; VAAPI: No VAAPI device (X) |

Every text in the table is either provoked on the capture machine (`detect_*` / `hw_*` captures)
or found byte for byte in the pinned build (`library_strings.json`, asserted in tests).

Anything else gives the state `error` ("the check itself failed", as `EncoderState` says) with
the **most informative line**: the first line logged by the encoder itself, else the first
line logged by a hardware device context (`VAAPI`, `AMF`, `AVHWDeviceContext`, …), else the
first `Device creation failed` / `Failed to set value` line, else the first line that is not
fftools bookkeeping (`Conversion failed!`, `[vf#…]`, `Task finished …`, progress, Mesa
notices), else the last line. A crash (signal, or a Windows NTSTATUS exit code) is named.
`EncoderStatus.detail` keeps the line, with the pointer addresses removed (`[hevc_nvenc] …`),
so it is stable between runs.

### 2. The filter list

C-4 also runs `ffmpeg -hide_banner -filters` and stores the names in
`CapabilitySnapshot.filters` (`has_filter()`), in parallel with `-encoders`. A failed list
gives `filters = None` ("not known"), never an error status.

### 3. Detection details

- **Test command**: `ffmpeg -hide_banner -nostdin <init_args> -f lavfi -i color=size=640x360
  -frames:v 3 (-vf <filter_tail> | -pix_fmt <sw_pix_fmt>) -c:v <id> -f null -`, from the
  definition's `hardware_setup` (placeholders `{vaapi_device}`, default `/dev/dri/renderD128`,
  and `{sw_pix_fmt}`). The 10-bit test runs when the definition has a 10-bit pixel format,
  after a working 8-bit test; it sets `supports_10bit` and, on failure, the new field
  `EncoderStatus.reason_10bit`. An encoder without a 10-bit pixel format gets
  `supports_10bit = False` without a test. Software encoders get `supports_10bit` from
  `Supported pixel formats` of `-h encoder=` (new field `EncoderStatus.pix_fmts`). For
  hardware encoders that list is not used: `h264_amf` lists `p010le` and still refuses
  10-bit.
- **Order**: `-encoders` and `-filters`, then `-h encoder=<id>` (4 at a time, about 10 ms
  each), then the test encodes (3 at a time, 10 s each). So every published status already
  has its options and presets.
- **Presets** (`EncoderStatus.presets`): the named values of `-preset` (NVENC `p1`…`p7`, QSV,
  AMF), or the numbers of an integer range without names (SVT-AV1 `-2`…`13`). x264 and x265
  take a free string, so their list is empty: C-6 must not read "empty" as "no presets".
- **Not tested**: hardware tests off → `unknown`, `in_build` set, reason "Not tested: hardware
  test encodes are off (Settings → Encoders)". Encoders whose `platforms` exclude this OS →
  `unavailable` ("Not available on Windows"). ffmpeg missing, too old or broken →
  `unavailable` with "FFmpeg not found" / "FFmpeg is too old" / "FFmpeg does not work" and the
  tool's reason in `detail`.
- **Cache**: one JSON file per key in `<cache dir>/capabilities/` (the newest 8 are kept, so
  switching between a few ffmpeg builds keeps their results). The key is the plan's (binary
  path, size, mtime, version, GPU fingerprint) plus the tool's extra environment
  (`LIBVA_DRIVERS_PATH`), the detection options, a hash of the definition fields that
  detection reads and a hash of the detection code. An entry that does not validate is a miss
  (it is a cache, not a document: no `schema_version`, no migration).
- **"Checked again in the background"**: every start runs the full detection. While it runs,
  the cached statuses stay (`from_cache=True`, `detecting=True`); only statuses that differ are
  published, then all of them when it ends. Without a cache hit, and on an explicit
  `rescan()`, every encoder is `checking` until its result is in.
- **A new ffmpeg** (a `tools.changed` event with another path, version, status or extra
  environment) starts a new detection (02 §Bundled FFmpeg: "Changing the path triggers a new
  encoder detection").
- **GPU fingerprint on Windows**: the display adapter class key in the registry (`DriverDesc`,
  `DriverVersion`) with `winreg`: no subprocess, no WMI. Read once per service, in a worker
  thread.
- An exception inside the detection (a bug) is logged and turns the open statuses into `error`
  ("Encoder detection failed: …"), so `detecting` never stays on.

### 4. Encoder issues

`reframe.capabilities.encoder_issues()` (pure; C-8 registers it as its encoder rule):

| Code | Severity | When |
|------|----------|------|
| `encoder.unknown` | error | not in the definitions |
| `encoder.checking` | **info** | `checking`, or `unknown` before the encoder list was read |
| `encoder.untested` | warning | a hardware encoder in the build that was not tested (tests off) |
| `encoder.unavailable` | error | `unavailable` or `error`; fix "Use libx265 (closest match)" = `replace /video/encoder` with `closest_available()`; no fix when nothing is available |

`encoder.checking` is `info`: an `error` would block *Add to queue* (03 §Validation), but 03
says the job can be edited and queueing waits; nothing is wrong yet, so not a `warning`
either. The queue (C-11) waits for `CapabilityService.wait()` before it starts a job whose
encoder is still being checked. `encoder.untested` is a new code: with the tests off the user
chose not to test, so it must not block, but the encode can fail.

## Follow-up (M2 review, 2026-10-14)

The milestone review found these. Each one has a regression test that failed before the fix.

1. **A stale cached `unavailable` blocked `plan` and `encode`.** The GPU fingerprint does not
   change when a user-space driver changes (AMF runtime, Mesa / libva, oneVPL), so a cached
   `unavailable` can be wrong. `encoder_issues` treated it as final and gave
   `encoder.unavailable`. The command exited before the re-check ended, so the cache was never
   corrected. Decision: while a cached result is checked again (`from_cache` and `detecting`),
   a status that is not `available` gives `encoder.checking` (info). The message keeps the
   cached result: "hevc_amf (AMD AMF H.265) is being checked again (last result:
   unavailable, AMD AMF runtime not found (libamfrt64.so.1)). The job waits for the result
   before it starts." Callers that wait for `encoder.checking` (C-15 `JobService.validate`,
   C-11) get the new result, and `wait()` returns only after the new result is in the cache.
   A cached `available` stays final, so a job does not wait for it. The snapshot itself is not
   changed (03: the cached statuses stay until their new results are in). Test:
   `test_recheck.py` (the CLI repro) and `test_issues.py::test_a_cached_result_is_checked_again`.
2. **The 10-bit test took exit code 0 as proof.** Checked with FFmpeg n9.0.2: when an encoder
   does not take the `-pix_fmt` it is given, FFmpeg logs "Incompatible pixel format 'p010le'
   for codec 'libx264', auto-selecting format 'yuv420p10le'", encodes with the format it
   picked and exits 0. Decision: the 10-bit test fails when FFmpeg replaced the 10-bit pixel
   format of the definition. The reason is "<encoder> does not take p010le in this FFmpeg
   build (it got nv12)" and the FFmpeg line is the detail. It fails even when the format that
   FFmpeg picked is 10-bit: the builder passes the definition's format, and the definition
   does not match this build. With the pinned build this cannot happen for the current
   definitions: NVENC and AMF all list `p010le`, and VAAPI and QSV get the format through a
   filter. It protects against another FFmpeg build (Settings → Tools). The 8-bit test still
   takes exit code 0: the encoder works. Test: `test_real.py` (real FFmpeg), `test_hwtest.py`,
   `test_detect.py`.
3. **A forced VAAPI node was lost with hardware tests off.** The encode then used
   `renderD128`. Now the node that Settings → Encoders forces is the `device` of the
   `unknown` VAAPI statuses too. Without a forced node, the device stays empty: no node is
   known without a test.
4. **Filter results under another ffmpeg.** A detection without a cache hit kept the last
   filter results until the new ones were in. Now it does so only for the same build (path
   and version); for another ffmpeg the filters are not known (`None`) until they are read.
5. **An exception from tool discovery** (not "closed") left `detecting` on for ever. It is now
   a failed detection like any other bug: `error` statuses ("Encoder detection failed: …")
   and a final `capabilities.changed` event.
6. **`close()` did not wait for a detection that `rescan()` replaced**, which can still be
   killing its test encodes. `close()` now waits for every detection that the service started.
7. **The Windows registry reader** (`winreg`) is now unit-tested on Linux with a fake `winreg`
   module; its `pragma: no cover` is removed.

## Consequences

- Reasons are plain language for every failure that was provoked or confirmed in the build;
  an unknown failure still shows a useful line, never `Conversion failed!`.
- The QSV and NVENC texts other than "no device" / "no driver" were not provoked (no Intel GPU,
  no NVIDIA driver on the capture machine). They are confirmed only as strings in the build.
  Revisit with real hardware (Q-2.4 local samples, a `needs_gpu` run on an Intel or NVIDIA
  machine), and on Windows (`nvcuda.dll`, D3D11 QSV texts are not checked at all).
- Each start runs the test encodes again (about 0.2 s on the capture machine, at most 10 s per
  test). The cache only removes the "checking…" period.
- C-6: `presets` can be empty for encoders that take free strings; `supported_options()` must
  treat an empty `private_options` list (help could not be read) as "not known".
- C-8 registers `encoder_issues` and adds the quality conversion to the fix.
- C-11 waits for the capability service before it starts a job (`encoder.checking`).
- The CLI (`reframe probe`) now also starts a detection that `close()` cancels. C-15 may want
  a way to skip it for commands that do not encode.

## Plan changes

- `docs/plan/05-core.md` §C-4: the reason-mapping bullet is replaced; a bullet for the filter
  list is added; the hardware-test and cache bullets say what this record decides
  (10-bit test, re-check, new ffmpeg).
