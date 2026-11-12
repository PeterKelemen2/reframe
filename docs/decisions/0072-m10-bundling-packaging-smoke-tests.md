# 0072 — M10: tool bundling, packaging, updater and smoke tests

- Status: accepted
- Date: 2026-11-12
- Steps: D-7, D-8, D-9, Q-3, Q-1.4

## Context

The rest of M10 that the Windows test VM (libvirt `win10`: Windows 10 Pro 22H2 19045, 6 logical
processors, 8 GB, no GPU) makes possible: D-7 (the bundled tools and Settings → Tools), D-8
(installers, packages, updater, licence notices) and D-9 (the `tauri-driver` smoke tests), each
with its Linux and its Windows half, and the Windows checks of Part 1 (the CI commands on 22H2,
the cold start again, the "Not verified" leftovers). Who builds what is in
[m10-breakdown.md](../m10-breakdown.md). D-7's host results are in
[0002](0002-bundled-ffmpeg.md).

The owner's answers (2026-11-12):

1. **Signing**: Windows installers are signed with a self-signed test certificate made on the
   VM (its private key stays there). The updater's test key pair is generated outside the
   repository, in `~/.config/reframe-test-keys/` on the host. Real signing with a bought
   certificate is out of scope.
2. **The Windows FFmpeg build**: try another Windows build against the `fieldmatch` crash of
   BtbN n9.0.2 win64 ([0070](0070-windows-testing-phase.md) "The desktop part"); switch the
   `windows-x64` pin if it is clean and meets 02 §Bundled FFmpeg.
3. The owner checks at the VM window when asked; one display head, so two monitors stay not
   verified.
4. NSIS, WiX, `tauri-driver` and `msedgedriver` may be installed on the VM; Docker containers may
   run on the host.

## Decision

1. **The bundled tools** are laid out by `scripts/bundle-tools.py` in
   `desktop/src-tauri/resources/tools/` and shipped as `<resources>/tools/` next to
   `<resources>/sidecar/` ([0005](0005-tool-discovery-details.md) item 2's layout; the core
   already searches `<exe dir>/../tools`). `bundle.active` is on; the bundle targets are per
   platform (`tauri.linux.conf.json`, `tauri.windows.conf.json`).
2. **The oldest supported Linux distro is Ubuntu 22.04 LTS** (glibc 2.35, the first Ubuntu with
   `libwebkit2gtk-4.1`, which Tauri 2 needs). The plan did not name one; the AppImage and the
   `.deb` are built in its image.

## Part 1 — the VM checks (lead)

**The CI commands and the whole suite on 22H2** (2026-11-12, `m10-hardening` 3a5a2cb, the VM's
clone in Git Bash over SSH; FFmpeg n9.0.2 as the bundled build in `%LOCALAPPDATA%\Reframe\tools`,
not on `PATH`; MKVToolNix 103.0 and MediaInfo CLI 26.10 on `PATH`): `uv lock --check`,
`uv sync --frozen`, `python -m reframe.tools --require ffmpeg,ffprobe --expect-origin bundled`,
ruff, ruff format (542 files), mypy and `mypy --platform linux` (540 files), the test media
(16 up to date); every frontend command (`npm ci`, lint, fmt:check, typecheck, `npm test` 1940
passed, build:web, build:desktop); the Rust job (`cargo fmt --check`, clippy `-D warnings`,
`cargo test` 24 passed). The whole `uv run pytest` with `REFRAME_REQUIRE_FFMPEG=1` (also the
`needs_gpu` and `benchmark` tests): **7481 passed, 3 failed, 204 skipped in 23 min**. The three
failures are `needs_gpu` tests, which CI's selection leaves out:

- `capabilities/test_real.py::test_every_hardware_encoder_gets_a_final_state` and
  `preview/test_frames.py::test_hdr_frames_with_libplacebo`: they need a GPU (expected).
- `capabilities/test_real.py::test_libplacebo_without_a_vulkan_driver`: **a wrong reason.** The
  VM's Vulkan loader reports instance API 1.0.0; libplacebo says `Instance API version 1.0.0 is
  lower than the minimum required version of 1.2.0, cannot proceed!`, which Reframe's reason
  table does not know, so libplacebo is `error` instead of `unavailable`. Fixed in task T.

**Q-3, the desktop cold start again**: the release build of 096836f with its frozen sidecar,
measured as 0070 did: **median 1.38 s, worst 1.43 s** (10 runs; the first run after the build
2.66 s); the frozen sidecar alone is ready in 0.96–1.03 s. The budget is met on this VM; the
4.7 s of 0071 was the laptop VM's CPU ([0071](0071-server-start-and-windows-cold-start.md)
"Follow-up").

## Task T — the bundled tools (D-7)

The results and the host tests are in [0002](0002-bundled-ffmpeg.md); this section is what the
other tasks need.

**Built.** `tools/bundled-tools.toml` (MKVToolNix 103.0 portable zip, only `mkvpropedit.exe`
and its licence files; MediaInfo CLI 26.10 zip, `MediaInfo.exe` and its licence files; both
`windows-x64` only). `scripts/bundle-tools.py` (reuses `reframe.tools.fetch`: download with
the size limit, `verify_file`, `safe_extract`, the tree digest of the marker); `fetch.py`
extracts a zip without a top folder. Tests: `testing/tests/test_bundle_tools.py`, three tests
in `packages/reframe/tests/tools/test_fetch.py`. The FFmpeg pin does not change.

**The CI step** (the S task's job, and the L task's Docker build in `ubuntu:22.04`), after
`uv sync --frozen`:

```sh
uv run python scripts/bundle-tools.py --platform linux-x64     # on Linux
uv run python scripts/bundle-tools.py --platform windows-x64   # on Windows (or on Linux)
```

It exits 1 with the reason on stderr (a checksum, a download, a foreign file in the folder,
a tool that discovery does not find as `bundled` with its pinned version). Its downloads can
be cached keyed on `tools/ffmpeg.toml` and `tools/bundled-tools.toml` (cache the archives, not
`resources/tools/`: the script re-hashes the folder anyway). The Linux layout needs a Linux
host (the tarball has symbolic links); the Windows layout builds on either. On a Windows whose
root store lacks mediaarea.net's root the MediaInfo download fails with
`CERTIFICATE_VERIFY_FAILED`; then run it with `SSL_CERT_FILE` set to the output of
`uv run python -m certifi` (needed on the VM; the GitHub runner is not checked).

**For L (packages)**: the `.deb` / `.rpm` get the tools in `/usr/lib/Reframe/tools/` (Tauri's
resource folder; the core finds it next to the sidecar), not 02's `/usr/lib/reframe/tools/`
(plan corrected). The licence files are `tools/ffmpeg/LICENSE.txt`,
`tools/mkvtoolnix/doc/COPYING.txt` (+ `README.txt`), `tools/mediainfo/LICENSE`
(+ `License.html`); the source links are in the two manifests (`source_commit`,
`build_scripts_commit`; `source_url`, `source_repository`, `source_tag`). The FFmpeg folder is
the archive root as it is (234 MB on Linux, `ffplay` and the headers included).

**Plan changes (in the same commit as 0002)**: 07 §D-7 bullet 2 said `resources/tools/<os>/`,
but one build makes one platform's package, so the layout is `resources/tools/` per build;
07 §Tool bundling and 02 §Bundled FFmpeg named `/usr/lib/reframe/tools/ffmpeg/` for the
`.deb` / `.rpm`, but Tauri installs resources under `/usr/lib/<productName>/`; 02 notes that
the build's VAAPI needs libva 2.22 or newer. 07 §D-7 bullet 1 is ticked; bullet 2 waits for
the CI job (S).

**Found for the lead and the owner**: VAAPI is unavailable with the bundled build on Ubuntu
22.04 / 24.04 and Debian 12 (their libva lacks `vaMapBuffer2`), and their distro FFmpeg is
older than Reframe's minimum, so the 07 risk table's remedy does not help there (0002
"Consequences"). The Windows Detelecine crash stays (no build without it; one filter thread
does not avoid it). The `status.md` open items on the
Detelecine crash and on D-7's `LIBVA_DRIVERS_PATH` are answered by 0002 (the lead's rows).

## Task U — Settings → Tools and the first-run check (D-7)

*Placeholder: filled by task U.*

## Task L — Linux packages and licence notices (D-8)

*Placeholder: filled by task L.*

## Task W — Windows installers and the updater (D-8)

*Placeholder: filled by task W.*

## Task S — the smoke tests (D-9)

*Placeholder: filled by task S.*

## Review and fix round

*Placeholder: filled by the lead.*

## Consequences

*Filled at the end.*

## Plan changes

*Filled at the end.*
