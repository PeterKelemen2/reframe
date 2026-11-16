# 0071 — The server's start, and the desktop cold start on Windows

- Status: accepted; item 2 (the shipped language list) and its Consequences bullet superseded in part by [0089](0089-folder-probe-and-language-list-removed.md)
- Date: 2026-11-10
- Steps: Q-3, C-16, S-2, D-2

## Context

Q-3 sets "Desktop cold start to interactive UI < 2 s on SSD". On Linux the release build takes
1.07 s ([0069](0069-m5-desktop-shell.md)). On the Windows 10 VM of the testing phase it took a
median of 5.11 s ([0070](0070-windows-testing-phase.md) "The checks that need no GPU"): the
sidecar is ready about 4.1 s after the app starts, then the page's first requests take about
1 s more. The page shows the workspace only after those requests: it needs the definitions,
settings, presets and queue to draw it.

What the server does before the page can show (Linux, the laptop's i5-8250U, `-X importtime`,
cProfile, and timed requests against a new server):

- **Imports: 1.24 s of the 1.35–1.39 s to the ready line.** Pydantic model classes
  (`reframe.models` 242 ms), the route modules (202 ms: FastAPI builds each route's state when
  it is declared) and FastAPI itself (126 ms, of it `fastapi.openapi.models` 84 ms) are the
  largest parts. guessit with rebulk and babelfish took 58 ms; the server needs it only to
  parse a name. On the VM the imports take 2.86 s. Modules with little code are 3–5 times
  slower there than on Linux, large ones 1.5–1.9 times.
- **The first authenticated request: 170–220 ms**, also 2 s after the ready line. FastAPI
  0.159 builds every route's state again, in its "effective context", when the first request
  is matched (`effective_candidates` → `_EffectiveRouteContext.from_api_route` for all 84
  routes). The same work is needed before or after the ready line.
- **The first `GET /api/languages`: 277 ms.** It builds the 429 entries from langcodes
  (135 ms) and loads `language_data.name_data` (71 ms). The result depends only on Reframe's
  code and the language packages.
- The page sends its nine requests at once; the first round took 455 ms (each request waited
  for the two costs above), the second 50 ms.
- Encoder detection runs again at every start, also with a cached result (05 §C-4: the cached
  result is used at once and checked again in the background). Its FFmpeg runs overlap the
  first requests.

## Decision

1. **guessit is imported when a name is first parsed** (`reframe.naming.parse.guess_matches`),
   not when the core is imported. A test checks that starting the server does not import it.
2. **The language list ships rendered** with the server package
   (`reframe_server/data/languages.json`, the exact response body). The route reads it once.
   A test compares it with the list built from `language_list()` and names the command that
   writes it again (`uv run python -m reframe_server.routers.languages`). The frozen sidecar
   collects the file.
3. **No workspace before the backend is ready.** The workspace without the server's documents
   would show controls that do nothing until the server answers, so it would not make the UI
   interactive sooner.
4. **FastAPI's second build of the routes and encoder detection stay as they are.** The first
   is inside FastAPI. The second follows the plan; a delayed re-check would keep stale statuses
   `encoder.checking` for longer and was not shown to help.
5. **The Windows cold start over 2 s is a known limit** of the Windows VM. Q-3's budget
   still applies, and it holds on Linux.

Results (old build against new, measured in turns):

- Linux, the venv server: the first round of the page's requests 455 → about 225 ms, the
  ready line 1.35–1.39 → 1.25–1.35 s.
- Windows, the frozen sidecar alone: ready 2.37–2.94 → 2.18–2.86 s, the first round
  530–652 → 439–484 ms.
- Windows, the release app (6 runs a block, new / old / new, the first run of a block not
  counted): median about 4.7–4.85 s against 5.15 s. The first run after the sidecar's files
  were replaced took about 7 s with either build: the first start after an install or update
  is slower.

## Consequences

- A change of the language list or of the langcodes / language_data packages fails
  `test_the_shipped_list_is_the_built_one` until the file is written again.
- The first name parse in a process pays guessit's import (about 60 ms on Linux).
- The Windows cold start is still more than twice the budget on the VM. The rest is the
  server's imports, FastAPI's second route build, and WebView2 starting on the same
  processors (the sidecar alone is ready about 1.2 s sooner than in the app). Revisit on a
  real Windows machine (D-9's smoke tests): if it also misses 2 s, the next steps are fewer
  imports before the ready line (route modules and core services loaded on first use) and an
  upstream report of FastAPI's second route build.

## Plan changes

- `09-quality-and-release.md` §Q-3: a note under the budget table on the Windows figure.

## Follow-up (2026-11-12): measured again on a faster VM — the budget is met

The same measurement ([0070](0070-windows-testing-phase.md) "The checks that need no GPU": from
the start of the release `Reframe.exe` with WebView2's DevTools port to the workspace with the
event connection open and **Open files…** enabled, polled every 5 ms over CDP, a clean quit
before each run, 11 runs, the first not counted) on the desktop VM: libvirt on an AMD Ryzen 5
5600, Windows 10 Pro 22H2 (19045), 6 logical processors, 8 GB, no GPU, Defender's real-time
scan on with no exclusions; the release build of `m10-hardening` 096836f with its frozen
sidecar (the build of this record's changes).

- **Median 1.38 s, best 1.35 s, worst 1.43 s** (10 runs). Budget: 2 s. The page target exists
  about 0.51 s after the start.
- The first run after the build (the sidecar's files new): 2.66 s. The first start after an
  install or update is slower, as before (about 7 s on the laptop VM).
- The frozen sidecar alone, from its spawn to the ready line: 0.96–1.03 s (6 runs), against
  2.18–2.86 s on the laptop VM.
- Each run started its own sidecar (11 ready lines and 11 shutdown requests in `sidecar.log`),
  and no Reframe process was left after a quit.

So the 4.7 s of the laptop VM (an i5-8250U laptop, Windows 10 2004 with no updates, 4 virtual
processors sharing the host with its desktop) came from that machine, not from Windows: the
server's start and WebView2 fit in the budget on a desktop-class CPU. The known limit is
narrowed to slow machines: on a laptop-class CPU in a VM the cold start can take more than
twice the budget. The next steps of this record's Consequences stay the remedy if a real Windows
machine misses it.
