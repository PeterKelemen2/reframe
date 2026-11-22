# 0098 — Build-mismatch causes, the download retry policy, putting back an interrupted install

- Status: accepted
- Date: 2026-11-19
- Steps: C-21, D-10; refines items 4 and 6 of [0093](0093-ffmpeg-download-and-build-choice.md)
  and item 5 of [0094](0094-docker-image-without-ffmpeg.md)

## Context

Review R1 of C-21 and D-10 (2026-11-18) found, among other things:

- The CLI hint told a user with an old system libva (Ubuntu 22.04's 2.14) to download the other
  build. Both pinned Linux builds load libva through `implib-gen` stubs and ship none, and in an
  `ubuntu:22.04` container both abort with `failed to resolve symbol 'vaMapBuffer2'`: another
  build does not help.
- A download that cannot reach the server was retried 4 times with back-off: 14 s for a name
  that does not resolve, 54–74 s for an unroutable address, and a certificate failure was
  retried too.
- A process killed between the two renames of the install swap leaves no build in
  `<data dir>/tools/ffmpeg` and the previous one in `.fetch-*/previous`, where the stale-work
  clean-up deletes it later.
- The sources release still listed FFmpeg's source and cloned BtbN, although no artefact
  conveys FFmpeg any more.

## Decision

1. `EncoderStatus.build_mismatch_cause: "driver" | "system_library" | None`, set from the reason
   rule that matched (`build_mismatch` stays a `bool`). The capability cache format is 3. The
   CLI prints one hint per cause: for `driver`, update the driver or use another build (as
   before); for `system_library`, install or update the library (libva) or use your own FFmpeg,
   and the desktop app ships a libva for its downloaded build. No `--build` suggestion there.
2. Retry policy of a download: name resolution, an unreachable network or host, and any TLS
   error during the connection get one attempt; a refused connection or a connect timeout two;
   an error after the response began and HTTP 429 / 5xx keep four. The offline classification
   (`tools.fetch_offline`) is unchanged.
3. When the install folder is missing and a `.fetch-*/previous` holds an intact build for this
   platform (marker and every file hash), the first tool discovery and every fetch put it back
   before anything else, with a log warning.
4. A packaged libva folder whose links loop or leave the folder is refused before the download.
5. The sources release lists no FFmpeg or BtbN source; the Windows installers are checked for
   FFmpeg files in the release workflow.

## Consequences

Offline failures are reported in about 0–2 s instead of 14 s or more, except for a connect
timeout (two 20 s attempts). Measured times are in `testdata/README.md`. Built by the R1 fix
round (merge 0b591021). Not run on Windows: the installer check.

## Plan changes

`05-core.md` C-21 (the mismatch and CLI items); `docs/m10-ffmpeg-breakdown.md` (the hint
contract).
