# 0088 — Tool runner options no caller uses, and a little-endian D-Bus client

- Status: accepted
- Date: 2026-11-16
- Steps: C-1, C-14, Q-6.17

## Context
The C-1 sketch in `05-core.md` names `run_streaming(argv, *, on_stdout_line, on_stderr_line,
cancel, timeout=None)`. The Q-6 audit (finding TP-03 in `docs/simplify/areas/tools-platform.md`)
counted the 16 production calls of `run` and `run_streaming`: none passes `stdin` to `run`, and
none passes `timeout`, `max_output` or `cwd` to `run_streaming`. Only `tests/tools/test_runner.py`
used them. Every production streaming run (the encode, the analysis passes, the preview clip)
has no time limit and is stopped with its `CancelToken`.

The D-Bus client of the sleep inhibit (decision 0011) could write and read both byte orders
(finding TP-06). The client always sends little-endian, and the bus daemon writes in its host's
byte order. All target platforms (`linux-x64`, `linux-arm64`, `windows-x64`) are
little-endian, so only one test sent a big-endian message. The D-Bus specification says a
receiver must accept both byte orders.

## Decision
- `run` has no `stdin` parameter: a child's stdin is always the null device. `run` keeps
  `timeout`, `cancel`, `max_output`, `cwd` and `extra_env`.
- `run_streaming` has no `timeout`, `max_output` or `cwd`. It keeps `cancel`, `extra_env` and
  `on_start`; the result keeps the last `DEFAULT_STREAMING_TAIL` bytes of each stream. The C-1
  rules hold: `run` still has the timeout, the cancel, the output limit and the tree kill;
  `run_streaming` keeps the cancel, its tail limit and the tree kill.
- The D-Bus client is little-endian only, a deliberate narrowing of the specification: a
  message with the big-endian flag `B` is a `DBusProtocolError`, as any bad flag already was.
  The reader also drops the types `i` and `y`, which no reply carries (a body with them is
  skipped, like other unknown types). It keeps `b`: the real-bus tests read the boolean replies
  of `HasInhibit` and `HasInhibition` with this client, and without `b` they skip silently.

## Consequences
- A big-endian host would get no session or logind sleep inhibit (the backend fails as data
  and the `sleep_inhibit.unavailable` warning shows). No target platform is big-endian.
- A future caller that needs stdin input, a streaming timeout or a streaming working folder
  adds the option back with its test.
- The streaming tests guard against a hang with `asyncio.timeout` around the call.

## Plan changes
- `05-core.md`, C-1: the `run_streaming` sketch has no `timeout`.
- `status.md`, C-14: the notification hook is the `notification` event that
  `reframe.queue.whendone` publishes (the `reframe.platform.notify` module is removed, TP-09).
