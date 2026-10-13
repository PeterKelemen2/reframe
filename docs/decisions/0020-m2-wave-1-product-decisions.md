# 0020 — M2 wave 1: sleep inhibit stops only automatic sleep, portrait fit, VAAPI device, audio fallback

- Status: accepted
- Date: 2026-10-13
- Steps: C-4, C-5, C-6, C-14
- Supersedes in part: [0009](0009-dimension-maths-conventions.md) (item 4, "the fit box is not
  turned"), [0011](0011-sleep-inhibit.md) (item 2, `what="sleep:idle"`, `mode="block"`)

## Context

The wave-1 steps of M2 raised product questions that the plan does not answer. The user
decided them on 2026-10-13.

1. **Sleep inhibit** ([0011](0011-sleep-inhibit.md)). The built Linux lock is a logind
   `sleep:idle` *block* lock. It also refuses the user's own Sleep (menu, power button) while a
   job runs, or asks for an administrator password. Windows' `ES_SYSTEM_REQUIRED` only stops
   the idle timer: the user can still sleep the PC. logind has no "automatic suspend only"
   lock, and the desktop's automatic suspend (KDE PowerDevil, GNOME) ignores logind locks.
2. **Portrait sources** ([0009](0009-dimension-maths-conventions.md) item 4). "Fit within
   1920×1080" on a 1080×1920 phone video gives 608×1080, because the box is not turned.
3. **VAAPI device** ([0008](0008-encoder-detection-reasons-and-filters.md)). Detection and
   encodes use `/dev/dri/renderD128`. On a machine with an iGPU and a dGPU the right node can
   be another one.
4. **Audio fallback.** Audio encoders have no fallback chain, so a preset that names
   `libfdk_aac` (not in GPL builds) gets "unavailable" with no fix.

Confirmed without a change (the user's answers, recorded here so they are not asked again):
DVD 16:9 made square stays 854×480 (0009 item 4); a hardware encoder that was not tested
because hardware tests are off gives the warning `encoder.untested` (0008); the file-name
character rules of [0012](0012-output-naming-rules.md) stay (`": "` → `" - "` …).

## Decision

1. **Sleep inhibit stops only automatic sleep.** The user's own Sleep, the power button and
   the lid always work at once; the encode then pauses with the system and continues after
   wake. On Windows this is what `ES_CONTINUOUS | ES_SYSTEM_REQUIRED` already does. On Linux,
   Reframe never takes a logind `sleep` lock in `block` mode. It takes what stops the idle
   timers only: a logind `idle` lock (logind's own `IdleAction=`) and the desktop session's
   inhibit for automatic suspend (for example `org.freedesktop.PowerManagement.Inhibit` or the
   XDG desktop portal's `Inhibit` with the suspend/idle flags, chosen and checked by C-14 on a
   real desktop). If none of these works: the `sleep_inhibit.unavailable` warning, as before.
2. **"Fit within W×H" turns the box for portrait output.** The box takes the orientation of
   the output picture (after cropping, pixel aspect and rotation): a picture that is taller
   than wide fits inside the box with its long side vertical, a wider one with its long side
   horizontal, a square one inside the box as written. So a 1080×1920 phone video stays
   1080×1920 with "Fit within 1080p" (1920×1080). Exact width and exact height are not
   changed.
3. **VAAPI device: automatic, with a setting.** Detection tests the VAAPI encoders on every
   render node (`/dev/dri/renderD*`) and uses, for each encoder, the first node where it works.
   The encoder status records that node, and the command builder uses it. An optional
   Settings → Encoders field (`AppSettings.encoders.vaapi_device`, empty = automatic) forces
   one node.
4. **Audio encoders have a fallback chain** in the definitions, like the video encoders:
   `libfdk_aac → aac`. `closest_available` and the encoder issues (`encoder.unavailable` with
   "Use aac (closest match)") work for audio encoders too.

## Consequences

- Linux behaviour now matches Windows: a long encode is not cut by the idle timer, and the
  user stays in control. A user who sleeps the PC pauses the encode; the queue must handle a
  long gap in progress (ETA, speed) after wake without failing the job.
- C-14 needs a session-bus call next to the system-bus call, and a connection that stays open
  while the inhibit is held (the desktop inhibits end when the caller's connection closes).
- C-5's property "the output is inside the fit box" uses the turned box for portrait output.
- C-4 runs more test encodes on a machine with several render nodes (still 3 at a time).
- `AppSettings.encoders` gets a new optional field (no schema bump: a new field is kept by
  older versions).

## Plan changes

- [03 §Dimensions](../plan/03-features.md#4-output-size): "Fit within" turns for portrait
  output.
- [03 §Queue](../plan/03-features.md#queue): sleep inhibit stops automatic sleep only.
- [03 §Settings](../plan/03-features.md#settings): Encoders gets the VAAPI device field.
- [05 §C-4](../plan/05-core.md#c-4-encoder-capabilities): test every render node;
  `closest_available` covers audio encoders.
- [05 §C-5](../plan/05-core.md#c-5-dimensions-maths): the portrait rule.
- [05 §C-6](../plan/05-core.md#c-6-definitions-encoders-options-filters-containers-languages):
  audio encoders have a fallback chain.
- [05 §C-14](../plan/05-core.md#c-14-platform-services): the Linux lock.
