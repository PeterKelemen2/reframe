# 0026 — Builder and validation agree: a chapter range end is clamped, an unknown advanced option is an error

- Status: accepted
- Date: 2026-10-14
- Steps: C-7, C-8

## Context

The C-8 follow-up (M2 wave 2b) added a test that every case where the command builder refuses
a job (`PlanError`) is a validation error, and that every C-7 plan-snapshot job validates
without errors (`tests/validation/test_command_agreement.py`). Two cases disagreed:

1. **A chapter range that ends after the last chapter** (chapters 4 to 5 on a file with 4
   chapters). Validation gives the warning `range.end_beyond`
   ([0014](0014-validation-rules-and-severities.md): "the encode stops at the end of the
   source anyway"), so the job is queued. `build_plan` raises `PlanError`
   (`command/metadata.py`, `chapter_range`). For a time or frame range it clamps the end
   instead.
2. **An advanced option the encoder does not have.** Validation gives the error
   `encoder.option_unknown`. The builder skips such an option
   ([0013](0013-command-builder-details.md), Consequences: "C-8 … may warn about what the
   builder skips"). The C-7 snapshot job `x264_advanced_and_custom_params` sets one on
   purpose, to show the skip, so it does not validate.

## Decision

1. **The builder clamps the end of a chapter range to the last chapter**, as for time and
   frame ranges. `range.end_beyond` stays a warning. A chapter range that *starts* after the
   last chapter stays a `PlanError` and the validation error `range.outside`.
2. **`encoder.option_unknown` stays an error.** An option that the user typed is never
   dropped without a word, and the fix removes it. The builder keeps skipping such an option
   as a defence, tested by a unit test. The snapshot job no longer sets it, so every snapshot
   job validates without errors.

## Consequences

- A job with chapters 4 to 5 on a 4-chapter file encodes chapter 4 to the end, with a warning.
- The agreement test has no known exceptions left.

## Plan changes

- None: 05 §C-7 and §C-8 do not describe these cases. 0013 (`PlanError` list: "an empty
  range") and 0014 (`range.end_beyond`) are unchanged.
