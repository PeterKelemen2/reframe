# 0021 — libplacebo needs a run test, not only the filter list

- Status: accepted
- Date: 2026-10-13
- Steps: C-4, C-6, C-7

## Context

03 §Filters: tone mapping uses "`libplacebo` if available, else `zscale,tonemap`".
[0008](0008-encoder-detection-reasons-and-filters.md) added the build's filter list
(`ffmpeg -hide_banner -filters`) to C-4's snapshot, so that C-7 can make that choice. C-6
found that the list is not enough: `libplacebo` is listed in both FFmpeg n9.0.2 builds, but it
fails at run time without a working Vulkan device. C-4 checked it on the capture machine
(AMD RX 7600, Mesa RADV), with the pinned build and the Arch build:

```sh
ffmpeg -hide_banner -nostdin -f lavfi -i color=size=640x360 -frames:v 1 -vf libplacebo -f null -
# exit 0, about 0.18 s
VK_ICD_FILENAMES=/nonexistent/icd.json ffmpeg … (the same)
# exit 187: [libplacebo @ 0x…] Failed creating instance: VK_ERROR_INCOMPATIBLE_DRIVER
```

## Decision

- Encoder detection (C-4) also runs one frame through `-vf libplacebo` when the build lists
  it, with the same timeout, cancel handling and 3-at-a-time limit as the hardware test
  encodes. A failure is mapped like an encoder failure ("No working Vulkan driver
  (VK_ERROR_INCOMPATIBLE_DRIVER)").
- `CapabilitySnapshot.usable_filter(name)` is what the consumers ask: `False` when the filter
  is not in the build or its run test failed, `None` while not known, `True` otherwise.
  `has_filter` keeps its meaning ("in the build"). C-7 uses `libplacebo` only when
  `usable_filter("libplacebo")` is `True`, else `zscale,tonemap`.
- With hardware tests off (Settings → Encoders), the libplacebo test does not run either: it
  uses the GPU like the test encodes, and that setting is how a user keeps Reframe away from a
  troublesome GPU driver. `usable_filter("libplacebo")` is then `None`, and the CPU path
  (`zscale,tonemap`) is used.

## Consequences

- One more process per detection (about 0.2 s, in parallel with the test encodes).
- An HDR → SDR job on a machine without Vulkan gets the CPU tone mapper instead of a failed
  encode.

## Plan changes

- [05 §C-4](../plan/05-core.md#c-4-encoder-capabilities): the filter-list bullet names the
  libplacebo run test and `usable_filter`.
