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
| 2026-11-13 | The owner's answer on the GPL source (0073, 476f444). The owner's VM session: the `Zoé 東京` profile path, the toast and the MSI's UAC prompt pass. |

## Where this run ended (2026-11-12)

On `m10-hardening`, not merged into `main`, not pushed. Every task (T, T2, U, L, W, S, FA, FB,
FU) is merged and its worktree removed; the reviews and the final checks are in 0072 "Review and
fix round".

- **Done**: Part 1 steps 1 and 2, and step 3's tray menu and theme; D-7; D-8 except a GitHub
  release; D-9 on Linux and the VM.
- **The owner's VM session** (2026-11-13, passed): as the user `Zoé 東京` (profile
  `C:\Users\Zoé 東京`), the per-user installer without UAC, the bundled tools, an Explorer
  double-click on `Ünnepi film – 東京.mkv` and its encode, the toast (*Reframe* with its icon),
  the theme kept after a restart, no process left after the quit; the signed MSI's UAC prompt
  names *Verified publisher: Reframe test signing*.
- **Owner questions**: the GPL corresponding source for releases was answered on 2026-11-13
  ([0073](decisions/0073-gpl-corresponding-source-per-tool-pin.md)); the Windows FFmpeg build
  (every candidate crashes with `fieldmatch` about as often: keep BtbN, and report upstream if
  wanted).
- **Left in place**: Docker images `reframe-l` and `reframe-s` with their volumes (`reframe-l-*`,
  `reframe-s-*`) and their base images `ubuntu:22.04` and `ghcr.io/astral-sh/uv:0.13.5`; the
  updater test key in `~/.config/reframe-test-keys/`; on the VM the test certificate (in
  `CurrentUser\My`, `LocalMachine\Root`, `TrustedPublisher`), `cargo-about`, tauri-driver,
  msedgedriver, the agents' clones and outputs under `C:\Users\TestWin\wt` and `w-*`, the
  test user and `C:\ReframeTest`.
- **Rest of M10**: F-19 (the Range selector, added on 2026-11-13 by
  [0074](decisions/0074-range-selector-in-m10.md); before F-16), F-16, F-17 in WebKit (five
  flows), Q-4, Q-5 (the release workflow: package builds,
  signing, `latest.json`, source archives), the release checklist.

## F-19: the Range selector (2026-11-13)

The spec is [0074](decisions/0074-range-selector-in-m10.md) (items 1–12 bind every task), with
[03 §Range](plan/03-features.md#range) and [06 §F-19](plan/06-web-app.md#f-19-range-selector) and
flow 5 of §F-17. No model, server or schema change is planned (0074): a task that finds one is
needed stops and tells the lead, who writes 0075 first. Same rules as above ("Rules for every
agent", "Machines and commands"); every agent `model: "opus"`, `effort: "high"`, a fresh agent,
`isolation: "worktree"` on `m10-hardening` (`git merge --ff-only m10-hardening` first). Commits
start with `F-19: `.

### Tasks and waves

| Wave | Task | What | Ports |
|------|------|------|-------|
| 1 | A | the selector: the pure range helpers, the button and popover in the source header, the editor-store glue (job and group target), the Summary's Source and Estimate cards, the en strings, unit tests, a server test against `chapters.mkv` through `jobs/validate` and `jobs/plan` | 871x |
| 1 → 2 | B | Playwright flow 5. Phase 1 (with A): the spec against the contract below, with what it needs from the e2e set-up. Phase 2 (resumed after A merges): run it, fix the flow, all flows twice | 872x |
| 3 | R1, R2 | two independent reviews: R1 correctness against 0074 and the group target; R2 the tests (each must fail on a defect a user would see), keyboard and i18n | 878x, 879x |
| 4 | fixes | one agent per area of the findings, each fix with a test that fails before it | 870x, 873x |
| lead | | merges (`--no-ff`, checks, one mutation per task, worktree and branch removed), the demo, the docs | 876x |

`npm run e2e` uses the ports 8750 and 8751: only one agent at a time runs it (A at its end, then
B in phase 2; the reviewers one after the other, R1 first).

### Who owns which files

| Task | Owns |
|------|------|
| A | `frontend/src/components/range/**` (new: the component(s), `range.ts` helpers, their tests, `range.server.test.ts`), `frontend/src/i18n/messages/en/range.json` (new), `frontend/src/views/WorkspaceView.vue` (the header slot only), `frontend/src/stores/editor.ts` (the range glue only) and its tests, `frontend/src/components/summary/{SourceCard,EstimateCard}.vue`, `summary/estimate.ts` and `estimate.test.ts`, the `summary.*` keys it adds to `en/summary.json`, the unit tests of those files |
| B | `frontend/e2e/flow5-range.spec.ts` (new); `frontend/e2e/support/**` only for a helper flow 5 needs (one that other flows may use too; say so in the report) |
| lead | `docs/status.md`, `docs/m10-breakdown.md`, 0074 "Built" and any 0075, the plan files, `frontend/e2e/support/servers.ts` fixtures list, `frontend/e2e/settings.json` |

### Contracts

**The editor store (A builds it; B, the reviewers and the fix agents use it).**

- `editor.setRange(range: Range): void` — the one way the selector changes the range. For a job:
  one `replace` patch on `/range`, one undo step (no coalescing with the next change). In a
  group, whatever the scope: the shown file's override (as `setNameField` does), one undo step;
  the template never gets a range (0040), and no "per file" refusal toast.
- `editor.rangeOverridden: boolean` — the edited group's shown file has a `/job/range` op in its
  override (either scope); `false` for a job.
- `editor.resetRangeToGroup(): void` — removes that op (the file encodes the whole source
  again), one undo step.
- `Range` is `Schemas['JobSettings']['range']` (`@/api/types`); no new type in the store.

**The range helpers (`frontend/src/components/range/range.ts`, A).**

- `parseTime(text: string): number | null` — `H:MM:SS.mmm`, `MM:SS`, plain seconds (with a
  fraction); `null` when it does not parse.
- `formatTime(seconds: number): string` — `H:MM:SS.mmm` (`0:01:30.000`).
- `convertRange(range, kind, source): Range` — item 6 of 0074 (frames from seconds: the average
  frame rate, start rounded down, end rounded up; seconds/frames to chapters: the chapters that
  hold the start and the end; else the mode's default).
- `rangeSeconds(job, source): number | null` — the seconds the range covers, the same
  arithmetic as `reframe.validation.range.range_duration` (clamped to the source as there).
  `summary/estimate.ts`'s `jobDuration` uses it, so the header, the Summary and the estimate
  give one length.

**The DOM (A builds it; flow 5 and the reviewers read it).**

| What | Selector |
|------|----------|
| the header button | `[data-field="range"]` in `.workspace__header`: a `button` whose accessible name has the range and its length; the label text in `[data-field="range-label"]`, the length in `[data-field="range-length"]`; `data-kind="full|chapters|time|frames"`; `data-state="overridden"` while `editor.rangeOverridden` |
| the popover | `.range-popover` (`role="dialog"`, labelled); open while the button's `aria-expanded="true"` |
| the modes | a radio group: `[data-range-mode="full|chapters|time|frames"]`, the inputs with the visible labels *Whole source*, *Chapters*, *Seconds*, *Frames*; a disabled mode `aria-disabled` / `disabled` with its reason in `[data-range-reason="chapters|frames"]` |
| the fields | `Field` with `path` `range.start` / `range.end` (so `data-path="range.start"` / `"range.end"`) for each mode: chapters *From* / *To* (PrimeVue `Select`, options labelled `2 · Part One · 0:00:01`), seconds *Start* / *End* (`InputText`), frames *From frame* / *To frame (not included)* (`InputText` or `InputNumber`); the `range` issues (path `range`) on the popover and on the button |
| *Reset to group* | `[data-action="range-reset"]` in the popover, only while overridden |
| the Summary | Source card `[data-card="source"] [data-field="range"]` (the range label and its length); Estimate card `[data-card="estimate"] [data-field="range"]` |

The texts are en strings from `en/range.json`: *Whole source*, *Chapters 2–3* (an en dash),
*0:01:30 – 0:45:00*, *Frames 0 – 1440*, as 0074 item 1.

### Done when (word for word in each brief)

03 §Range: "Done when: picking chapters 2–3 of a source updates the header, the Summary, the
output name and the command at once, and the encoded file lasts as long as those chapters."
06 §F-19: the four bullets. 06 §F-17 flow 5. 0074 items 1–12.

### The demo (the lead, headless)

`chapters.mkv` (5.021 s; chapters 1 *Opening* 0–1 s, 2 *Part One* 1–2.5 s, 3 *Part Two*
2.5–4 s, 4 *Credits* 4–5 s; H.264 25 fps; checked with ffprobe on 2026-11-13). *Chapters* 2–3 is
1.0–4.0 s = 3.0 s = 75 frames. Through the UI (headless Chromium against `dev-server.py` with the
real pinned FFmpeg, no fake): the header, the Summary, the output name with `{chapters}` and the
command drawer; a real encode; ffprobe of the output's duration and chapters; the same with
*Seconds* and *Frames*; undo step by step. The measured numbers go under "F-19 results" below.

### F-19 progress

| Date | What |
|------|------|
| 2026-11-13 | This section committed (5177b9c); wave 1 (A, B phase 1) launched. |
| 2026-11-13 | A merged (bcfc512), B phase 2 merged (44ad5e3); the lead's mutation per task caught. Reviews R1 (1 major, 3 minors, 2 nits) and R2 (1 major, 4 minors, test and i18n gaps); both majors reproduced by the lead. Fixes FX1 (5b48f57, the group target: [0075](decisions/0075-the-range-in-a-group-and-the-shown-job.md)) and FX2 (aba9d76). Final checks and the demo: below and in [0074](decisions/0074-range-selector-in-m10.md) "Built". |

#### F-19 results

Demo, 2026-11-13, at aba9d76: headless Chromium, `dev-server.py --tools-dir` the pinned FFmpeg
n9.0.2 (no fake), the default preset (H.265 software, MKV), `chapters.mkv` (5.021 s, 25 fps).
The driver set the template through the Summary's naming editor, the range through the header,
and read the command from the Video tab's drawer.

| Range | Header | Summary (Source / Estimate) | Name | Command | Output (ffprobe, pinned) |
|-------|--------|-----------------------------|------|---------|--------------------------|
| *Chapters* 2–3 | *Chapters 2–3* · 0:03 | *Chapters 2–3 (0:03)* / *Range: Chapters 2–3 (0:03)* | preview `chapters 2-3.mkv` at once; the path after *Use this path* | `-ss 1` before `-i`, `-t 3` | file 3.021 s; video HEVC 3.000 s, 75 frames; audio AAC 3.021 s; chapters *Part One* 0–1.5, *Part Two* 1.5–3.0 |
| *Seconds* (kept from the chapters) | *0:00:01 – 0:00:04* · 0:03 | the same label (0:03) | `chapters seconds.mkv` (template without `{chapters}`) | `-ss 1`, `-t 3` | the same: 3.021 s, 75 frames, the two chapters |
| *Frames* (kept) | *Frames 25 – 100* · 0:03 | the same label (0:03) | `chapters frames.mkv` | `-ss 1`, `-t 3` | the same: 3.021 s, 75 frames, the two chapters |

Chapters 2–3 last 3.0 s (75 frames). The video stream is exact; the file is 21 ms longer (the
last AAC frame), within one frame (40 ms). Undo, eight Ctrl+Z, one step each: the template, the
mode *Frames* → *Seconds*, the template, *Seconds* → *Chapters*, *Use this path*, *To* 3 → 4
(*Chapters 2–4*, 0:04), *From* 2 → 1 (*Chapters 1–4*, 0:05), *Chapters* → *Whole source*. The
same numbers came from a first run after task A (bcfc512).

#### Where F-19 ended (2026-11-13)

Done on Linux, on `m10-hardening`, not merged into `main`, not pushed. Every worktree and
branch of the run (A, B, R1, R2, FX1, FX2) is removed. Recorded, not fixed: 0074 "Built". Rest
of M10: F-16, F-17 in WebKit (five flows), Q-4, Q-5, the release checklist.

## F-16: the i18n and accessibility audit (2026-11-13)

The spec is [06 §F-16](plan/06-web-app.md#f-16-i18n-and-accessibility) and
[0076](decisions/0076-f16-i18n-and-accessibility-audit.md) (item 1: what the audit checks, item
2: the gate, item 5: what is not in F-16). Same rules as above ("Rules for every agent"); every
agent `model: "opus"`, `effort: "high"`, a fresh agent, `isolation: "worktree"` on
`m10-hardening` (`git merge --ff-only m10-hardening` first). Commits start with `F-16: `. Each
task fills its own section of 0076.

### Tasks and waves

| Wave | Task | What | Ports |
|------|------|------|-------|
| 1 | G | the gate (0076 item 2): `@axe-core/playwright`, the screen list, axe in both themes, the focus walk, the reduced-motion check, the per-area known lists; `REFRAME_E2E_PORT`; the shared layer (tokens, theme, global CSS, `components/base`) fixed; the i18n checks extended to strings built in scripts where a check can see them | 871x, e2e 8750 |
| 1 → 2 | K1, K2, K3 | phase 1 (with G): the keyboard paths, the focus and the strings of the area, walked in headless Chromium and Firefox with scripts of their own, fixed with tests. Phase 2 (resumed after G merges): the gate's findings of the area, the known list emptied | K1 872x (e2e 8720), K2 873x (e2e 8730), K3 874x (e2e 8740) |
| 3 | R1, R2 | R1: the gate itself (does it check what 0076 item 1 says, on every screen; can a finding slip through) and contrast/focus by eye on screenshots; R2: the keyboard paths and the strings, area by area, with tests that fail on a user-visible defect | 878x, 879x |
| 4 | fixes | one agent per area of the findings | 870x, 877x |
| lead | | merges, checks, one mutation per task, the docs | 876x |

### Who owns which files

| Task | Owns |
|------|------|
| G | `frontend/src/styles/**`, `frontend/src/components/base/**`, `frontend/src/i18n/**` (index, checks; message files `base.json`, `editor.json`), `composables/useReveal.ts`, `composables/useTheme.ts`, `frontend/e2e/a11y/**` (the gate, `screens/<area>.ts` and `known/<area>.ts` until it merges), `frontend/e2e/support/**`, `frontend/playwright.config.ts`, `frontend/package.json` and `package-lock.json` (the dev dependency) |
| K1 shell and pages | `components/{shell,sources,queue,settings,presets}/**` except `shell/PreviewPanel.vue`, `views/**`, `App.vue`, `router/**`, `platform/**`, `composables/{useShortcuts,useQuitFlow,useOpenPaths,useQueueActions,useQueueGroup}.ts`, messages `shell`, `sources`, `queue`, `settings`, `presets`, `app`, `desktop`, `window`, `api`; after G: `e2e/a11y/{screens,known}/shell.ts` |
| K2 picture and video | `components/{video,summary,dimensions,crop,filters,clip,media}/**`, `shell/PreviewPanel.vue`, `editor/tabs/{Summary,Dimensions,Filters,Video}Tab.vue`, messages `video`, `summary`, `dimensions`, `crop`, `filters`, `preview`, `clip`, `media`, `advanced`, `params`; after G: `e2e/a11y/{screens,known}/picture.ts` |
| K3 tracks and batch | `components/{tracks,language,chapters,naming,matrix,batch,defaults,range}/**`, `editor/tabs/{Audio,Subtitles,Chapters,Tags}Tab.vue`, messages `tracks`, `language`, `chapters`, `tags`, `naming`, `matrix`, `group`, `defaults`, `range`; after G: `e2e/a11y/{screens,known}/tracks.ts` |
| lead | `docs/**`, the stores (`src/stores/**`: a change there goes to the lead), anything not listed |

A change in another task's file goes back to the lead in the report.

### Contracts

**The screen list (G builds it; each area owns its file after G merges).** A screen is
`{ id, area, setup(page) }` in `e2e/a11y/screens/<area>.ts`; `setup` brings the app to the screen
through the UI from `openApp` (the e2e servers' fixtures: `multitrack`, the season,
`letterbox`, and `chapters` in the output root). The ids are binding; an area may add screens.

| Area | Screens |
|------|---------|
| shell | `workspace-empty`, `file-browser`, `preset-picker`, `status-issues` (the status bar's issue list open), `toast`, `queue` (waiting, done and failed jobs), `job-log`, `activity`, `presets`, `preset-name-dialog`, `settings-<section>` for each web section, `login` |
| picture | `summary`, `dimensions`, `crop-manual` (letterbox, magnifier), `filters`, `video`, `video-advanced`, `command-drawer`, `preview-frames`, `split-compare`, `preview-clip` |
| tracks | `audio`, `subtitles` (with an external subtitle), `chapters`, `tags`, `track-metadata`, `bulk-edit`, `language-picker`, `naming-editor`, `range` (`chapters.mkv`, the popover open), `group` (the banner, scope `file`), `matrix`, `queue-group`, `defaults`, `apply-to-group` |

**The known lists.** `e2e/a11y/known/<area>.ts` exports `{ screen, check: 'axe' | 'focus' |
'motion', theme?: 'light' | 'dark', rule?, target }[]`. The gate fails on a finding that is not
listed and on a listed one that did not happen. At the end of F-16 every list is empty, except
entries with a reason in 0076.

**Ports.** `REFRAME_E2E_PORT` (default 8750) is the first port of `npm run e2e`'s servers
(Chromium on it, Firefox on the next). K1 uses 8720, K2 8730, K3 8740 in phase 2.

**Numbers.** A number shown to the user goes through vue-i18n's `n(value, options)` (or `Intl`
with the app's `locale`), never `toFixed`/`String()` alone; a formatter in a `.ts` file takes
`n` as it takes `t` today (`summary/format.ts`). `toFixed` for arithmetic stays.

### Done when (word for word in each brief)

06 §F-16: "Audit that every string goes through vue-i18n (English first; the rule and its check
start in F-1). Full keyboard paths. Visible focus. WCAG AA contrast in both themes. Respect
`prefers-reduced-motion`." 0076 item 1 (points 1–5) for every screen of the task's area; for G,
0076 items 2–4 as well.

### F-16 progress

| Date | What |
|------|------|
| 2026-11-13 | This section and 0076 committed (d222ee7); wave 1 (G, K1, K2, K3 phase 1) launched. |
| 2026-11-13 | Phase 1 merged: K1 (b710275), K2 (50f37b6, follow-up c508865), K3 (e6c43ef, follow-up c77bc3b); G merged (f24bf3b: the gate, 42 screens, 124 e2e tests). K1–K3 phase 2 resumed on their own e2e ports. |
| 2026-11-14 | Phase 2 merged: K3 (556d091), K2 (0869075, with the probe's straight-alpha fix), K1 (41178b6); every known list and the script-text allowlist empty; e2e 144 twice. Reviews R1 (the gate: 2 majors) and R2 (keyboard and strings: 1 major), all reproduced by the lead. Fixes FP phase 1 (edb476b), FG (95c4f10: the gate widened, 198 e2e tests) and FP phase 2 (ef2e7c9). Final checks and the docs: [0076](decisions/0076-f16-i18n-and-accessibility-audit.md) "Review and fix round". |

#### Where F-16 ended (2026-11-14)

Done on Linux, on `m10-hardening`, not merged into `main`, not pushed. Every worktree and
branch of the run (G, K1, K2, K3, R1, R2, FG, FP) is removed. Each task was broken once by the
lead after its merge, and its tests caught it. Recorded, not fixed: 0076 "Review and fix
round". Owner question: a layout for small windows (default: a later step). The end-to-end run
now takes 7.7 min (198 tests: five flows, the layout checks, the gate and three keyboard
specs). Rest of M10: F-17 in WebKit (the five flows and the gate), Q-4, Q-5, the release
checklist.

## F-17: the flows and the gate in WebKit (2026-11-14)

The spec is [06 §F-17](plan/06-web-app.md#f-17-end-to-end-tests) and
[0077](decisions/0077-f17-webkit.md) (the host set-up, the first run's five causes A–E, the
Done when). Same rules as above ("Rules for every agent"), with 0077 in place of 0072; every
agent `model: "opus"`, `effort: "high"`, a fresh agent, `isolation: "worktree"` on
`m10-hardening` (`git merge --ff-only m10-hardening` first). Commits start with `F-17: `. Each
task fills its own section of 0077.

### Tasks and waves

| Wave | Task | What | Ports |
|------|------|------|-------|
| 1 | W1 | A (the thumbnail's focus ring) and D (the magnifier smoothed) | e2e 8720 |
| 1 | W2 | B (focused fields covered) and C (the language picker's typing) | e2e 8730 |
| 1 | W3 | E (flow 5: the Range popover's Selects) | e2e 8740 |
| 2 | R1 | review: the fixes, and the gate's measurements in WebKit | e2e 8780 |
| 3 | fixes | one agent per area of the findings | e2e 8770, 8700 |
| lead | | merges, checks, one mutation per task, the CI timeout, the docs | e2e 8750 |

Each agent runs e2e with `REFRAME_E2E_PORT=<its port>` (three servers on three ports from
it). `npm run test:server` has fixed ports: an agent runs it only for its own test files, never
the whole project at the same time as another agent.

### Who owns which files

| Task | Owns |
|------|------|
| W1 | `components/{media,crop,clip,dimensions}/**`, `shell/PreviewPanel.vue`, `e2e/flow4-manual-crop.spec.ts`, `e2e/a11y/{screens,known}/picture.ts` |
| W2 | `components/{naming,language,tracks,chapters,matrix,batch}/**`, `editor/tabs/**` except `DimensionsTab.vue`, `src/styles/**`, `components/base/**`, `e2e/a11y/{gate.ts,page/**,types.ts,steps.ts}`, `e2e/a11y/keyboard-tracks.spec.ts`, `e2e/a11y/{screens,known}/{shell,tracks}.ts` |
| W3 | `components/range/**`, `e2e/flow5-range.spec.ts` |
| lead | `docs/**`, `playwright.config.ts`, `e2e/support/**`, `.github/**`, the stores (`src/stores/**`), anything not listed |

A change in another task's file goes back to the lead in the report (with the diff). A finding
that turns out to be the gate measuring WebKit wrongly is W2's (it owns the gate); W1 shows the
pixels or DOM in its report and the lead routes it.

### Done when (word for word in each brief)

06 §F-17: "Each flow comes with its screens … M10 runs all five in Chromium and WebKit". 0077
Decision items 3–4: each failure fixed in the app, or in the gate when the gate measures WebKit
wrongly (shown, not assumed); a known-list entry only with a reason in 0077; the task's tests
pass twice in a row in WebKit, and stay green in Chromium and Firefox.

### F-17 progress

| Date | What |
|------|------|
| 2026-11-14 | WebKit installed on the host (0077 Context); the `webkit` project added; first run 87 passed, 12 failed (causes A–E). This section and 0077 committed; wave 1 (W1, W2, W3) launched. |
| 2026-11-14 | Merged W3 (92db6db: a chapter pick no longer closes the Range popover, a real defect in Chromium and WebKit), W1 (30ef787: the magnifier canvas `content-box`, flow 4 at any device pixel ratio), W2 (f84d8ce: the language picker under a still pointer; the gate waits a rendering update after each Tab and judges pictures in device pixels) and the gate's own tests (a6ec03a). The lead broke each task's fix once; its test failed each time. Whole e2e suite in Chromium, Firefox and WebKit: 303 passed twice in a row (13.7 and 14.0 min); unit 2150; lint, format, types clean. Review R1 launched. |
| 2026-11-14 | Review R1 (no blocker; 1 major reproduced by the lead: a still pointer on an open PrimeVue list took the arrow keys' option in WebKit; 3 minors, 2 nits). Fix FA merged (d7c006d: one app-wide filter for WebKit's still-pointer moves, `components/base/stillPointer.ts`; the picker's local fix removed; the Range click drop armed per main press and disarmed by the next press; `e2e/still-pointer.spec.ts`), the lead's nit fix (da28a06). The lead's final runs found an intermittent flow 4 failure (Firefox; W1 saw it once in Chromium): a late job update replaced a crop value being typed; fixed with a test that failed before (279a397). Final: e2e 309 passed twice in a row (13.7 min each, three browsers), unit 2158, server 105, lint, format, types and the web build clean. |

#### Where F-17 ended (2026-11-14)

Done on Linux, on `m10-hardening`, not merged into `main`, not pushed. Every worktree and
branch of the run (W1, W2, W3, FA) is removed; R1 worked read-only in the main checkout. Each
task's fix was broken once by the lead after its merge, and its test caught it. The e2e suite runs
in Chromium, Firefox (kept by the owner) and WebKit; on this host WebKit needs the Ubuntu
libraries of 0077 Context (redo the libjxl link after a Playwright upgrade). Recorded, not
changed: PrimeVue's `Select` picks on any button's press, and `Popover` takes any press inside it
as its own (0077 "Review and fix round"). Rest of M10: Q-4, Q-5, the release checklist; S-6's
NVIDIA/Intel checks wait for such a host.

## Q-4: logging and diagnostics (2026-11-14)

The spec is [09 §Q-4](plan/09-quality-and-release.md#q-4-logging-and-diagnostics) and
[0078](decisions/0078-q4-logging-and-diagnostics.md) (Decision items 1–7). Same rules as above
("Rules for every agent"), with 0078 in place of 0072; every agent `model: "opus"`,
`effort: "high"`, a fresh agent, `isolation: "worktree"` on `m10-hardening`
(`git merge --ff-only m10-hardening` first). Commits start with `Q-4: `. Each task fills its own
section of 0078.

### Wave 0 (the lead, the contract)

`AppSettings.diagnostics.log_level` (`LogLevel`: `error` | `warning` | `info` | `debug`,
default `info`) in `reframe.models.settings`; `GET /api/diagnostics` → `DiagnosticsReport
{text: str, logs_dir: str}` in `reframe_server/routers/system.py` (a stub: empty `text`); the
schema snapshots and `frontend/src/api/schema.d.ts`. These names and shapes are binding.

### Tasks and waves

| Wave | Task | What | Ports |
|------|------|------|-------|
| 1 | P | the app log (0078 items 1–5) and the report's text (item 6, the server part) | none (pytest only) |
| 1 | U | Settings → Diagnostics: the log level, the logs folder, Copy diagnostics with the client part (items 4, 6, 7); against the stub, then against P's report after P merges | e2e 8720; the only one to run `npm run test:server` |
| 2 | R1 | review | e2e 8780 |
| lead | | merges, checks, one mutation per task, the docs | e2e 8750 |

### Who owns which files

| Task | Owns |
|------|------|
| P | new modules in `packages/reframe/src/reframe/` for the log and the report; in `service.py` only the log-level reaction to a settings change and the report's facade method; `packages/reframe-server/src/reframe_server/{app.py,__main__.py,routers/system.py}`; their tests; `frontend/src/api/schema.d.ts` (regenerated with `npm run gen:api` when a docstring changes) |
| U | `frontend/src/components/settings/DiagnosticsSection.vue` (new) and its tests, `frontend/src/views/SettingsView.vue` (the section's place), the `settings` messages, `frontend/e2e/a11y/{screens,known}/shell.ts` (the gate's `settings-diagnostics` screen) |
| lead | `docs/**`, `reframe/models/**`, anything not listed |

### Done when (word for word in each brief)

09 §Q-4 (the three bullets) as 0078 Decision items 1–7 say. P: a running server writes
`<data>/logs/reframe.log` as JSON lines at the level of the setting, rotates it at 5 MiB with
three old files, applies a level change without a restart, keeps running when the file cannot
be written; `GET /api/diagnostics` gives the report of item 6 with `~` paths and no token or
password. U: Settings → Diagnostics sets the level (one setting change), shows the logs folder,
and **Copy diagnostics** puts the report and the client part on the clipboard with a
confirmation; keyboard, i18n and the gate as F-16 requires; the whole e2e suite stays green.

### Q-4 progress

| Date | What |
|------|------|
| 2026-11-14 | 0078, this section and wave 0 committed; wave 1 (P, U) launched. |
| 2026-11-14 | P merged (5330b9c: `reframe/applog.py`, `reframe/diagnostics.py`, the level through `Reframe.create(on_log_level=…)`, the route's report), U phase 1 against the stub, then phase 2 against P's report, merged (2de580d: Settings → Diagnostics; `diagnostics.server.test.ts`). The lead broke each task once (the access log let into the file; the client part left out of the copy); its tests caught it. A real server's `reframe.log` and report checked by hand (JSON lines, no token). Review R1 launched. |
| 2026-11-14 | Review R1: 1 blocker (at `debug` the auth token and the session cookie reached `reframe.log` through uvicorn's websockets logging; reproduced by the lead), 4 minors, 5 nits. Fix FP merged (539ab09; the lead's re-run of the leak: `False`; the lead's mutation, `uvicorn.error` back among Reframe's loggers, fails the real-server regression test) and the lead's `server.log` name change (03ccb62). Final: pytest 7899 passed, 2 skipped (five chunks, run alone); e2e 315 passed twice (12.5 and 13.0 min, three browsers); unit 2171; server 107; ruff, format, both mypy runs, the API check, lint, format, types and the web build clean. |

#### Where Q-4 ended (2026-11-14)

Done on Linux, on `m10-hardening`, not merged into `main`, not pushed. Every worktree and
branch of the run (P, U, FP) is removed; R1 worked from a scratch copy. Each task was broken
once by the lead after its merge, and its tests caught it. Owner questions (0078 Consequences):
a `reframe diagnostics` CLI command and a button that opens the logs folder are not built.
Recorded, not changed: the rotation limit counts characters (0078 review item 8). Rest of M10:
Q-5 and the release checklist; S-6's NVIDIA/Intel checks wait for such a host.

## Q-5: the release process (2026-11-14)

The spec is [09 §Q-5](plan/09-quality-and-release.md#q-5-release-process),
[0079](decisions/0079-q5-release-process.md) (Decision items 1–8) and
[0073](decisions/0073-gpl-corresponding-source-per-tool-pin.md). Same rules as above ("Rules
for every agent"), with 0079 in place of 0072, and **commits as conventional commits with the
step as scope** (`feat(Q-5): …`, `fix(Q-5): …`, `docs(Q-5): …`; 0079 item 2). Every agent
`model: "opus"`, `effort: "high"`, a fresh agent, `isolation: "worktree"` on `m10-hardening`
(`git merge --ff-only m10-hardening` first). Each task fills its own section of 0079. Nothing
is pushed: no workflow runs on GitHub; each script a workflow calls is tested locally.

### Contracts (binding; only options with defaults may be added)

| Script (task) | Interface |
|---|---|
| `scripts/stamp-version.py` (V) | No argument: stamps `reframe.__version__` into every other version field and prints it. `--check`: changes nothing, exits 1 and names each field that differs. `--set VERSION`: writes `__version__` first, then stamps. `--print-semver`: prints the SemVer spelling (for Tauri and npm). |
| `scripts/release-notes.py VERSION` (V) | Prints that version's section of `CHANGELOG.md` (without its heading); exits 1 when there is none. |
| `scripts/sources-manifest.py --out FILE [--appimage-libs FILE]` (S) | Writes the source manifest (JSON, stable order) and prints its tag `sources-<first 12 hex of SHA-256>`. `--appimage-libs`: the AppImage's distro library list (how it is made before the notices: S decides and documents). |
| `scripts/sources-fetch.py --manifest FILE --out DIR` (S) | One archive per manifest entry in `DIR`, each checked against its pin, and `DIR/SHA256SUMS`; rerunnable (skips a checked archive). |
| `scripts/third-party-notices.py` (S) | Gains `--sources-url URL` and `--sources-sums FILE` (the notices name the sources release and each archive's SHA-256), and the platforms `docker-linux-x64`, `docker-linux-arm64`. |
| `docker/Dockerfile` (A) | Builds for `linux/amd64` and `linux/arm64` (buildx `TARGETARCH`); copies `docker/notices/THIRD_PARTY_NOTICES` from the build context (the workflow writes it; git-ignored) and writes the runtime image's Debian package list with source links next to it. |
| `scripts/updater-manifest.py --version V --notes FILE --base-url URL --out FILE ARTEFACT…` (W) | Writes Tauri's `latest.json` from the updater artefacts and their `.sig` files. |
| `.github/workflows/release.yml` (W) | On `v*`: the jobs of 0079 item 7, calling the scripts above as they are given here. |

### Tasks and waves

| Wave | Task | What | Owns |
|------|------|------|------|
| 1 | V | 0079 items 1–3: the version stamp and its CI check, the Vite `define` (the version in the UI's diagnostics client part), `cliff.toml` (pinned git-cliff), `CHANGELOG.md` with the first section's frame, `release-notes.py` | `scripts/{stamp-version,release-notes}.py`, `cliff.toml`, `CHANGELOG.md`, the version fields (`packages/reframe-server/pyproject.toml` and its version source, `frontend/package.json`, `desktop/package.json`, `desktop/src-tauri/{tauri.conf.json,Cargo.toml,Cargo.lock}`), `frontend/vite.config.ts`, `frontend/src/components/settings/DiagnosticsSection.vue` (the client part's version line only), `.github/workflows/ci.yml` (the `--check` step only), their tests in `testing/tests/` |
| 1 | S | 0079 items 4, 5 (the sources half): what BtbN pins and how to fetch it (checked against the real repository), the manifest, the fetch, the notices' sources link; measure one real fetch's size | `scripts/{sources-manifest,sources-fetch,third-party-notices}.py`, `desktop/packaging/linux/build.sh` only for the AppImage library list, their tests |
| 1 | A | 0079 items 5 (the image half), 6: the `linuxarm64` pin (checked: checksum, the binary is aarch64, same source commit), `fetch-tools.py`/`bundle-tools.py` platforms, the multi-arch `docker/Dockerfile` with the notices and the Debian package list, S-6's docs | `tools/ffmpeg.toml`, `scripts/{fetch-tools,bundle-tools}.py` (platform lists), `docker/**`, `packages/reframe/src/reframe/tools/fetch.py` if it lists platforms, their tests |
| 1 | W | 0079 item 7: `release.yml`, `updater-manifest.py`, `docs/release.md` (the steps, the secrets, the first-release checks); actionlint clean | `.github/workflows/release.yml`, `scripts/updater-manifest.py`, `docs/release.md`, its tests |
| 2 | R1 | review | |
| lead | | 0079, `CLAUDE.md`, the plan, merges, checks, one mutation per task | `docs/**` except `docs/release.md`, anything not listed |

### Done when (word for word in each brief)

09 §Q-5 as 0079 Decision items 1–8 say, for the task's items; every script's contract above;
tests that fail on the defect a user (or a release manager) would see; ruff, format, both mypy
runs and the touched tests green; the workflow (W) actionlint-clean, with each job's commands
run locally where they can be.

### Q-5 progress

| Date | What |
|------|------|
| 2026-11-14 | Owner answers: conventional commits from now on, Windows signing when the secrets are set, an arm64 pin, no PyPI for v1. 0079, the plan, `CLAUDE.md` and this section committed; wave 1 (V, S, A, W) launched. |
