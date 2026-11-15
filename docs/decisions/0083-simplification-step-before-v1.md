# 0083 — A simplification step (Q-6) in M10, before the release checklist

- Status: accepted; audit done 2026-11-15, the steps are not started
- Date: 2026-11-15
- Steps: Q-6 (new: Q-6.1 to Q-6.19); M10

## Context

The core and the server grew over ten milestones, with reviews and fix rounds after each one.
Before v1 the owner asked for a step that removes code that is more complex than the plan and the
decision records need: dead code, duplicates inside and across areas, layers that add nothing,
options that no caller uses. The plan had no such step.

An audit at commit `85d9dcb` (branch `m10-hardening`) looked at all of `packages/reframe` (41.8k
code lines, 63.1k test lines) and `packages/reframe-server` (3.8k, 8.0k). Ten agents audited one
area each and ten fresh agents tried to show each finding wrong. The result is in
[docs/simplify/](../simplify/README.md):

- 131 findings and 10 cross-area ones. Verify confirmed 34, adjusted 96, rejected 1.
- Tier A (low risk, behaviour unchanged): 51 findings, about -1,100 source and -1,100 test lines.
- Tier B (medium risk, a contract or a decision text touched, or a Windows-only path): 35
  findings, about -1,080 source and -680 test lines.
- Tier C (not planned): 36 findings, mostly `decision-change` findings whose record's reason still
  applies.

The audit ran unattended. The choices it made in place of the owner are in
[docs/simplify/decisions-taken.md](../simplify/decisions-taken.md).

## Decision

1. M10 gets a step **Q-6 Simplification**, with one step `Q-6.n` per work package of
   [docs/simplify/plan.md](../simplify/plan.md): Q-6.1 to Q-6.10 for Tier A, Q-6.11 to Q-6.19
   for Tier B.
2. The Tier A steps come after the Windows testing phase and C-18 to C-20, and before the release
   checklist. The release checklist gets the item "the Tier A steps of Q-6 are done".
3. The Tier B steps follow if there is time. A Tier B step that is not done before the release
   moves to after v1; it does not block the release.
4. Tier C findings are not planned. They stay in the area files with the condition that would
   make them worth doing.
5. A work package makes only the changes its findings describe. A package that removes something a
   decision record or a plan file names (marked "decision record" in the plan) writes a new record
   and the plan edit in the same commit, as `CLAUDE.md` asks. This record does not change any
   earlier decision by itself.
6. Each package is one conventional commit `refactor(Q-6.n): …`. The changelog reads them as
   refactors (decision 0079).

## Consequences

- No behaviour a user sees changes in Tier A. Tier B has a few visible changes, each listed in its
  finding and in `decisions-taken.md` (for example `probe_hash` is `null` in `reframe probe
  --json`, better codec labels in batch rows, one number format).
- Q-6.12 (Windows-only paths) needs the Windows test VM of decision 0070. Without it, Q-6.12
  stays open; nothing depends on it.
- Line numbers in the findings refer to `85d9dcb`. Each package finds its places by symbol name
  and checks that the code still matches before it changes it.
- The owner should check the choices in `decisions-taken.md` before the Tier B steps start; most
  of them only move a finding between Tier B and Tier C.

## Plan changes

- `docs/plan/09-quality-and-release.md`: new section "Q-6 Simplification" with steps Q-6.1 to
  Q-6.19 and their "Done when".
- `docs/plan/08-roadmap.md`: M10 lists `Q-6`; a new subsection "Simplification" before the release
  checklist; the release checklist gets the Tier A item.
- `docs/status.md`: Q-6.1 to Q-6.19 as "Not started"; an entry in "Questions for the user that are
  still open".
