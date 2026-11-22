# 0087 — No check for an unknown container (`container.unknown` goes)

- Status: accepted
- Date: 2026-11-16
- Steps: Q-6.16 (amends [0014](0014-validation-rules-and-severities.md) "Follow-up (M2 wave 2b)" item 3)

## Context

Decision 0014, "Follow-up (M2 wave 2b)" item 3, made every `PlanError` of `build_plan` a
validation error. One of them was `container.unknown`: a job whose `output.container` has no
container definition. The simplification audit (finding VAL-06 in
[docs/simplify/areas/validation.md](../simplify/areas/validation.md), choice D-10) found that a
job cannot reach this state:

- `JobSettings.output.container` is the `Literal` `Container` (`mkv`, `mp4`, `webm`). A job with
  another value is rejected when it is parsed. A new value needs a `schema_version` bump, so an
  older version rejects a newer file at load.
- `Definitions.containers` is `dict[Container, ContainerDef]`, loaded only from the packaged
  `containers.toml`. The definitions lint fails when a `Container` value has no definition
  (`tests/definitions/test_lint.py`).
- Only tests reached the code, with `setattr(job.output, "container", "avi")` or a
  `# type: ignore`. No client reads the code (`frontend/`, `desktop/`, the server: no match).

The state was guarded in 15 places in validation and in three outside it: `build_plan` and
`planned_audio` raised `PlanError("unknown container ...")`, and the queue's output check
returned "unknown container".

## Decision

- `JobContext.container` and `TemplateContext.container` return a `ContainerDef`, not
  `ContainerDef | None`. The `None` guards in the rules go.
- The rule `known_container` and the issue code `container.unknown` go.
- `build_plan`, `planned_audio` (`command/audio.py`), the queue's `check_output`
  (`queue/verify.py`) and the runner's output check index `definitions.containers[...]`. The
  three "unknown container" refusals go, with their test cases.
- A comment on `Definitions.containers` says that every `Container` has a definition (a
  comment, not a docstring, so the API schema does not change).

The reason of 0014 item 3 stays true: what `build_plan` refuses is a validation error. The
builder refusal goes together with the validation error.

## Consequences

- The issue code `container.unknown` can no longer appear. No HTTP schema changes: issue codes
  are free strings.
- If a future `Container` value has no definition, the definitions lint fails the build, and an
  unlinted run would raise `KeyError` instead of giving an issue.
- `test_switch_container_keeps_every_track_valid` used the unknown container as its vehicle. It
  now uses a WebVTT conversion in MP4: WebM can hold WebVTT, but not the job's x265 video, so
  only "Switch to Matroska" is offered.
- The same package (Q-6.16) changes how a validation message formats a number: an advanced
  option value of 1,000,000 or more is printed in full (`1234567`, not `1.23457e+06`), and a
  float keeps all its digits (`0.1234567`, not `0.123457`). Validation now uses the same
  `value_text` as `describe_condition` (finding VAL-09).
- The same package makes validation use the command builder's HDR test (finding VAL-07,
  decision 0026): a source is HDR when the probe found an HDR format. A hand-built or API-sent
  source with a PQ or HLG transfer and no HDR info gets no HDR warning, because the builder does
  not treat it as HDR either. A probed source is unchanged: the probe sets an HDR format for
  every PQ or HLG stream.

## Plan changes

None: no plan file names `container.unknown`. [0014](0014-validation-rules-and-severities.md)
gets a pointer to this record in its status line.
