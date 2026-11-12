# M10 task breakdown: D-7, D-8, D-9 and the Windows VM checks

Working notes of the lead for the branch `m10-hardening`: the part of M10 that the Windows test
VM (no GPU) makes possible. The plan ([plan/07-desktop-app.md](plan/07-desktop-app.md) §Tool
bundling, §D-7 to §D-9; [plan/08-roadmap.md](plan/08-roadmap.md) §M10 and "Windows testing
phase"; [plan/09-quality-and-release.md](plan/09-quality-and-release.md) §Q-3 and §Licensing;
[plan/02-architecture.md](plan/02-architecture.md) §Bundled FFmpeg) is the spec; this file says
who builds which part, in which order, and what each part must offer to the others. Decision:
[0072](decisions/0072-m10-bundling-packaging-smoke-tests.md) (the lead's choices, what the plan
got wrong, one section per task). D-7's host results go to
[0002](decisions/0002-bundled-ffmpeg.md) (reserved by the plan). Status: [status.md](status.md).
If the lead's context is summarised, this file and `status.md` are the source of truth.

## Scope

| Task | Step | What is built | Plan |
|------|------|---------------|------|
| lead | Part 1 | the CI commands and the full pytest on the 22H2 VM; Q-3's desktop cold start again (6 processors); the "Not verified" Windows leftovers with the owner (tray menu, theme, a profile path with accents and CJK) | 08 §Windows testing phase; 0070; 0071 |
| T | D-7 | the bundle step: pins for MKVToolNix and MediaInfo next to `tools/ffmpeg.toml`, `scripts/bundle-tools.py` (download, SHA-256 before extract, the 0005 layout in `desktop/src-tauri/resources/tools/`); the choice of the Windows FFmpeg build (the `fieldmatch` crash); the host tests; `0002-bundled-ffmpeg.md` | 07 §Tool bundling, §D-7 bullets 1–2; 02 §Bundled FFmpeg; 0005 |
| U | D-7 | Settings → Tools and the first-run check for a desktop app that bundles its tools: **Use bundled** per tool, **Test**, environment overrides read-only, the first-run screen that shows which binary is in use and where it came from | 07 §Tool bundling "Override", §D-7 bullet 3; 03 §Settings |
| L | D-8 | Linux: the AppImage built in the oldest supported distro's image (Docker), `.deb`, `.rpm` (FFmpeg bundled, `Recommends: mkvtoolnix, mediainfo`, `%F` in the desktop entry); `THIRD_PARTY_NOTICES` with the bundled tools' source links, in every artefact | 07 §D-8 bullet 2; 09 §Licensing |
| W | D-8 | Windows: the per-user NSIS installer (no admin), the WebView2 bootstrapper, the optional MSI, signing with the owner's self-signed test certificate, the PATH offer, file associations, the notification's identity, the long-paths question, uninstall; the updater (`tauri-plugin-updater`, a signed `latest.json`, an older installed version updated to a newer one from a test release served by the host) | 07 §D-8 bullets 1 and 3, §Native integrations "Updates" |
| S | D-9 | the `tauri-driver` smoke test: start, backend ready, a fixture opened from argv, a job queued and finished, quit with no orphan processes; on Linux (Ubuntu container, Xvfb, `WebKitWebDriver`) and on the VM (`msedgedriver` for WebView2 157); the CI job | 07 §D-9 |

**Out of scope**: Windows GPU encoders, the magnifier's update rate, Windows 11, GitHub Actions
runs (recorded as not verified); F-16, F-17 in WebKit, Q-4, Q-5; Docker/GHCR publishing; real
code signing with a bought certificate.

## Waves

| Wave | Tasks (one agent and one worktree each) | Builds on |
|------|------------------------------------------|-----------|
| 0 | the lead: Part 1 steps 1–2; this file, 0072 with one placeholder section per task, the skeleton (`bundle.active`, the `resources/tools/` placeholder, the per-platform bundle files), the VM clones | `m10-hardening` 3a5a2cb |
| 1 | T (uses the VM, no GUI), U, L (against the placeholder tools layout) | wave 0 |
| 2 | W (the VM's GUI session), S (phase 1: Linux and the Windows preparation without GUI; phase 2 on the VM when the lead says W has finished its GUI work) | T merged (L and U merged when ready) |
| owner | one session at the VM window: tray menu, theme follow, the accented/CJK profile, Explorer double-click open-with, the installed app's notification | W's installer merged |
| 3 | two reviews (R1: the bundle step, packaging, updater and installer safety; R2: Settings → Tools, first run, smoke tests), the lead's reproduction of every blocker and major, the fix round, the final checks on Linux and the VM, the docs | wave 2 merged |

The lead merges each task with `--no-ff`, runs the checks, mutates once per task, and removes the
worktree and its branch. Every agent: `model: "opus"`, `effort: "high"` (the owner's rule for this
run), a fresh agent (not a fork), `isolation: "worktree"`.

## Who owns which files

An agent edits only the files it owns and creates new files only inside its own folders. A change
anywhere else goes back to the lead (say so in the report; do not make it). Every agent updates
only its own `docs/status.md` row (D-7 is shared by T and U: T writes the row, U adds one sentence
to it at the end) and its own section of 0072.

| Task | Owns |
|------|------|
| T | `tools/` (new manifest for MKVToolNix and MediaInfo, the Windows pin of `tools/ffmpeg.toml` if it changes, `tools/README.md`), the packaged copy `packages/reframe/src/reframe/tools/ffmpeg.toml` and `fetch.py` (only to reuse or extend its download / verify / extract code), `scripts/bundle-tools.py`, `scripts/fetch-tools.py`, their tests, `desktop/src-tauri/resources/tools/README.md`, `docs/decisions/0002-bundled-ffmpeg.md`, `testdata/README.md` ("Verified tool behaviour") |
| U | `frontend/src/components/settings/{ToolsSection,ToolRow}.vue`, `settings/tools.ts`, `components/shell/FirstRunScreen.vue`, their tests, the en messages they use; `reframe/tools/discovery.py`, `reframe/models/tools.py` and the server's system routes only for what the UI needs (say so in the report; `scripts/gen-api.sh` afterwards) |
| L | `desktop/packaging/linux/**` (Dockerfile, build script, install tests), `desktop/src-tauri/linux/**`, `desktop/src-tauri/tauri.linux.conf.json`, `scripts/third-party-notices.py` and its output path (and its one entry in `bundle.resources` of `tauri.conf.json`), `docs/plan/09-quality-and-release.md` §Licensing checkboxes |
| W | `desktop/src-tauri/windows/**`, `desktop/src-tauri/tauri.windows.conf.json`, `desktop/packaging/windows/**`, the updater: `Cargo.toml` (the plugin), `src/updater.rs` (new), its registration in `main.rs`, `capabilities/main.json` (the updater permissions only), `plugins.updater` in `tauri.conf.json`, the frontend part of an update prompt if one is needed (`frontend/src/platform/desktop/updater.ts`) |
| S | `desktop/tests/smoke/**` (new), `desktop/package.json` (dev dependencies of the smoke test), a `desktop-smoke` job in `.github/workflows/ci.yml` |

The lead owns `tauri.conf.json` except `plugins.updater`, `main.rs` except W's registration line,
`Cargo.toml` except W's plugin line, `.gitignore`, this file, and the status rows of Part 1.

## Contracts

### The bundled tools layout (T builds it, L, W and S use it)

- `uv run python scripts/bundle-tools.py --platform linux-x64|windows-x64 --dest DIR` (default
  `desktop/src-tauri/resources/tools`) writes `DIR/ffmpeg/` (the pinned build's own layout: `bin/`
  with `lib/` on Linux, the DLLs in `bin/` on Windows), and on Windows also `DIR/mkvtoolnix/` and
  `DIR/mediainfo/` (0005 item 2), each with the tool's licence file. Every download's SHA-256 and
  size are checked before anything is extracted (as `scripts/fetch-tools.py`). It is rerunnable
  and leaves nothing else in `DIR` but the committed `README.md`.
- `tauri.conf.json` maps `resources/tools/` to `tools/` (wave 0), so an installed app has
  `<resources>/tools/ffmpeg/…` next to `<resources>/sidecar/`; the core already searches
  `<exe dir>/../tools` for the sidecar's layout (`reframe.paths.bundled_tool_roots`).
- Until T merges, the folder holds only the README: the app builds and finds no bundled tools.

### The oldest supported Linux distro (L)

Ubuntu 22.04 LTS (glibc 2.35, the first Ubuntu with `libwebkit2gtk-4.1`, which Tauri 2 needs).
The AppImage, the sidecar inside it and the `.deb` are built in an `ubuntu:22.04` image. A
different choice is written in 0072 with the reason.

### The updater (W)

The updater test key pair is generated outside the repository, in
`/home/peti/.config/reframe-test-keys/` (the owner's choice); only the public key is committed,
marked as a test key in a comment of the record (JSON has none). The private key and its password
never enter the repository, a log in the repository, or a decision record.

### The self-signed code-signing certificate (W)

The owner chose a self-signed test certificate: made on the VM (`New-SelfSignedCertificate
-Type CodeSigningCert` in `Cert:\CurrentUser\My`), its public part imported into the VM's
`Root` and `TrustedPublisher` stores, and used by `signtool` through Tauri's
`bundle.windows.certificateThumbprint` or `signCommand` in a config overlay that is not committed
(the thumbprint is per machine). The private key never leaves the VM.

## Done when (word for word from the plan, in each agent's brief)

**T (D-7, bullets 1 and 2):**
- Choose the FFmpeg build for `tools/ffmpeg.toml` against the requirements in 02 §Bundled
  FFmpeg. Test it on the hosts that are available, aiming at Intel (VAAPI + QSV), AMD (VAAPI, AMF
  on Windows) and NVIDIA (NVENC), on at least two Linux distros (Debian/Ubuntu and Fedora or Arch)
  and on Windows *(Windows testing phase)*. Record each host and its result in
  `docs/decisions/0002-bundled-ffmpeg.md`, and list there the hosts that were not tested as not
  verified.
- CI downloads the pinned FFmpeg / MKVToolNix / MediaInfo builds, verifies the checksums, and puts
  them in `resources/tools/<os>/`. The same step feeds the .deb/.rpm layout.
- The hosts of this run: this Linux host (CachyOS/Arch, AMD RX 7600: VAAPI and AMF), an
  Ubuntu or Debian container with `/dev/dri`, the Windows VM (software encodes; every hardware
  encoder shows the right "unavailable" reason). Not verified: Intel QSV, NVIDIA, Windows with a
  GPU. The owner's choice for the Windows build: try another Windows build against the
  `fieldmatch` crash (2 of 40 runs with BtbN n9.0.2 win64), and switch the `windows-x64` pin if it
  is clean and meets 02's requirements.

**U (D-7, bullet 3):** Settings → Tools: a path override per tool, **Test**, **Use bundled**, env
overrides shown read-only. The first-run check runs before the main UI. (07 §Tool bundling: "The
first-run screen shows which binary is in use and where it came from.")

**L (D-8, bullet 2, and 09 §Licensing):** Linux: AppImage (built on the oldest supported distro
image, for glibc compatibility), `.deb`, `.rpm`. CI generates `THIRD_PARTY_NOTICES`
(`pip-licenses`, `license-checker`, `cargo about`) and bundles it with every artefact. It also
writes source links for the bundled tool builds. Each package installed and run in a container
of its distro (and the AppImage on this host, headless) with the bundled FFmpeg found as
`bundled`.

**W (D-8, bullets 1 and 3):** Windows: NSIS installer (per-user, no admin rights), WebView2
bootstrapper, optional MSI. Installed and run on Windows *(Windows testing phase)*: install, run,
uninstall with nothing left behind; the file associations; the NSIS PATH offer, and whether an
update keeps the PATH entry; the installed app's notification name and icon; whether the
installer offers to turn on long paths. Updater: signed `latest.json` (in GitHub Releases for a
real release), tested with a test release served from the host to the VM, from an older
installed version to a newer one.

**S (D-9):** `tauri-driver` (WebDriver) on Linux and Windows CI: the app starts, the backend
becomes ready, a fixture opens from argv, a job is queued and finishes, and quitting leaves no
orphan processes. On Windows: *(Windows testing phase)*.

## Machines and commands

- **This host**: `/home/peti/Programming/reframe` (CachyOS, AMD Ryzen 5 5600, RX 7600). The
  pinned FFmpeg (not in a worktree):
  `/home/peti/Programming/reframe/.tools/ffmpeg/default-linux-x64/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0/bin`.
  Test media: `mkdir -p testdata/media && cp -a /home/peti/Programming/reframe/testdata/media/. testdata/media/`.
  MediaInfo is not installed; `mkvpropedit` is (`/usr/bin`). Docker (classic builder, no
  buildx) may run containers; remove the images you pulled or built when you are done.
  `WebKitWebDriver` is not installed here.
- **Cargo**: one shared `CARGO_TARGET_DIR=/mnt/Data/reframe-build/m10-target` for agents on this
  host; `touch desktop/src-tauri/build.rs` before a check build (worktrees that share a target dir
  share build-script output, so a binary can carry another worktree's capabilities). Copy the
  binary you test into your own scratch folder in the same command as the build. The lead's
  final checks use their own target dir.
- **The VM**: `ssh TestWin@192.168.122.4` (Git Bash, elevated). Start every command with
  `export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"`; `MSYS_NO_PATHCONV=1` for Windows tools
  with `/switch` arguments; `tr -d '\000'` on PowerShell output. It has Git, uv (Python 3.14),
  Node 24, Rust MSVC + VS Build Tools 2022, MKVToolNix and MediaInfo CLI on `PATH`, WebView2 157,
  the pinned FFmpeg in `%LOCALAPPDATA%\Reframe\tools\ffmpeg` (not on `PATH`). No GPU.
  `LongPathsEnabled` is 0 (keep it; set it back if a check needs 1).
  **The VM cannot fetch from the host**: each agent has its own clone `C:\Users\TestWin\wt\<task>`
  (`~/wt/<task>` in Git Bash) and syncs it from its worktree with the lead's
  `vmsync.sh <task>` (it pushes the worktree's state, committed and staged, and checks it out
  there; `git add` new files first). Cargo on the VM: `CARGO_TARGET_DIR=C:\Users\TestWin\cargo-agents`
  (shared, `touch build.rs` first). **Only one agent at a time runs GUI or timing work on the VM**;
  the lead says when. A GUI program must run in the logged-on console session (a scheduled task
  with `/IT`, as 0070 "The desktop part"); check `query user` first and tell the lead if nobody is
  logged on (never log on, log off, lock or restart the VM yourself).
- **Ports**: agent N uses 87N0 to 87N9 (8750 and 8751 belong to `npm run e2e`): T 871x, U 872x,
  L 873x, W 874x, S 877x, R1 878x, R2 879x, the lead 876x, fix agents 870x.

The commands (CLAUDE.md): Python `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`,
`uv run mypy --platform win32`, `uv run pytest <your tests>`; frontend (from `frontend/`) lint,
fmt:check, typecheck, `npm test`, build:web, build:desktop; Rust (from `desktop/src-tauri/`)
`cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`;
`scripts/gen-api.sh --check`. The app: `cd desktop && npm ci && npx tauri build` (with bundles) or
`--no-bundle`; the frozen sidecar first: `uv run python desktop/sidecar/build.py`.

## Rules for every agent (word for word in each brief)

### The code

- Use CLAUDE.md. Load the `code-comments` skill before writing code: a comment says why, never
  step IDs, plan sections or history. Strict TypeScript, every visible string through vue-i18n.
  Rust: edition 2024, no `unwrap()` on a path a user can reach, no `println!`, `unsafe` only with
  a `SAFETY:` comment.
- Build what the plan says and nothing more: no extra options, settings or hooks. Reuse what
  exists (`reframe.tools.fetch`, the M4 Settings → Tools, the D-2 sidecar build, the D-3 quit
  flow). No new dependency unless you can say why an existing one cannot do it.
- Real behaviour of FFmpeg, MKVToolNix, MediaInfo, NSIS, WiX, WebView2, the Tauri bundler and its
  updater is checked against the real tool, and recorded in a test, `testdata/README.md` or your
  section of the decision record, not taken from memory.
- If the plan is wrong or cannot be done, write it in your section of 0072 and edit the plan file
  in the same commit.

### Displays and windows

- On this host, nothing opens a window on the owner's displays: no app start outside a headless
  session (the virtual KWin of 0069 Context item 4:
  `env -u DISPLAY -u WAYLAND_DISPLAY dbus-run-session -- kwin_wayland --virtual --no-lockscreen --socket reframe-<task> --width 1600 --height 1000 --exit-with-session <script>`,
  with private `XDG_*` and `REFRAME_*_DIR` folders, or Xvfb inside a container), no headed
  browser, no `xdg-open`, no `notify-send` on the real bus, no input tools, no browser-use plugin.
- On the VM, GUI work only when the lead has said it is your turn.

### Safety

- Every server or app you start uses isolated data, config and cache folders in a temp folder and
  `REFRAME_POWER_DRY_RUN=1`. Never use the owner's real data folder (it may hold a real
  `server.json`). On the VM, an installed app's data folder is `%LOCALAPPDATA%\Reframe`
  (shared with the lead's checks): remove only what your test made, and say so in the report.
- Kill only processes you started, by pid (never `pkill -f` with a pattern from your own command
  line; it kills your own shell).
- Disk: at most the shared target dirs, no copy of `target/`; remove Docker images and containers
  you made.
- Never put the owner's email address in a User-Agent or any request. Downloads from GitHub, the
  MKVToolNix and MediaInfo sites need no account.
- Commit per step with the step ID first (`D-7: …`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage files by name. Never push to
  any remote but the VM clone, never merge into `main` or `m10-hardening`.

### Test rules

A test is meaningful only if it fails when the code has a defect that a user would see. Name
that defect before you write the test.

- Write tests for what your "Done when" requires, each script's contract (the checksum refused,
  the layout written, the rerun), every branch you wrote.
- Do not test Tauri, NSIS, Vue or the browser themselves, snapshots of whole components, or
  mocks that return what the test told them.
- Mutation check before you report: break the code each test covers at least once per test
  function; the test must fail, and pass again when you restore it (`touch` a restored Python
  file). Report the tests per file and the mutations.

### The report

It starts with your model ID; then the real output of every check command (the last lines), what
you checked on which machine and how, every deviation from the plan and from this file, every
file touched outside your list, what you chose not to build, what later tasks need, and anything
left on the VM or in Docker.

## Progress

| Date | What |
|------|------|
| 2026-11-12 | Owner answers: a self-signed Windows test certificate and an updater test key in `~/.config/reframe-test-keys/`; try another Windows FFmpeg build; the owner at the VM window when asked, one display head (two monitors stays not verified); installing NSIS / WiX / tauri-driver / msedgedriver on the VM and Docker containers on the host is allowed. Part 1 step 1 (VM `win10`, 22H2, 6 processors): the lock, ruff, format, both mypy runs, every frontend command (1940 tests) and the Rust job (24 tests) pass. |
| 2026-11-12 | Wave 0 committed (096836f). Part 1 step 1: the whole pytest on the VM 7481 passed, 3 failed (`needs_gpu`; one is a wrong libplacebo reason, given to T); step 2: cold start median 1.38 s, the budget is met (0071 "Follow-up"). Next: wave 1 (T, U, L). |
| 2026-11-12 | U merged (0b7df9e); T merged (7c08a89: the Windows FFmpeg pin stays BtbN, every candidate crashes about 1 % with `fieldmatch`; the bundled FFmpeg's VAAPI aborts with libva < 2.22, so T2 ships libva 2.22 built on Ubuntu 22.04 next to FFmpeg). Theme and tray pass (35af7e0), real icon set (c4107e5). W launched (the VM's GUI session is W's). |
| 2026-11-12 | L merged (f59cffb), T2 (1ad3733: libva 2.24.1 bundled; tools started by a frozen app get the user's environment), S phase 1 (b62f4d6), W (2907ded), S phase 2 (60cddb8) and the lead's `comfort.rs` change for msedgedriver (ecd81cd: the Windows smoke run 6 of 6). Reviews R1, R2 (no blocker; 5 majors, all reproduced); fixes FA (92b9374), FB (9900547), FU (af8d4b2), S (the CI job's packages); the lead's docs (0ad8fbe). Final checks on Linux and the VM (7a0430f). |

## Where this run ended (2026-11-12)

On `m10-hardening`, not merged into `main`, not pushed. Every task (T, T2, U, L, W, S, FA, FB,
FU) is merged and its worktree removed; the reviews and the final checks are in 0072 "Review and
fix round".

- **Done**: Part 1 steps 1 and 2, and step 3's tray menu and theme; D-7; D-8 except a GitHub
  release; D-9 on Linux and the VM.
- **Waiting for the owner at the VM window**: a Windows user whose profile path has accents and
  CJK (the user `Zoé 東京` exists; the signed test installers and a test file are in
  `C:\ReframeTest`), and the signed MSI's UAC prompt by eye (on the secure desktop, no
  screenshot). The installed app's notification name and icon were checked by task W (the
  shortcut's AUMID and a screenshot); a look by eye is optional.
- **Owner questions**: the GPL corresponding source for releases (status "Questions"); the
  Windows FFmpeg build (every candidate crashes with `fieldmatch` about as often: keep BtbN,
  and report upstream if wanted).
- **Left in place**: Docker images `reframe-l` and `reframe-s` with their volumes (`reframe-l-*`,
  `reframe-s-*`) and their base images `ubuntu:22.04` and `ghcr.io/astral-sh/uv:0.13.5`; the
  updater test key in `~/.config/reframe-test-keys/`; on the VM the test certificate (in
  `CurrentUser\My`, `LocalMachine\Root`, `TrustedPublisher`), `cargo-about`, tauri-driver,
  msedgedriver, the agents' clones and outputs under `C:\Users\TestWin\wt` and `w-*`, the
  test user and `C:\ReframeTest`.
- **Rest of M10**: F-16, F-17 in WebKit, Q-4, Q-5 (the release workflow: package builds,
  signing, `latest.json`, source archives), the release checklist.
