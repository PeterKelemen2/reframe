# 0091 — A test-trimming step (Q-7) in M10

- Status: accepted; audit done 2026-11-17, steps Q-7.1 to Q-7.13 done 2026-11-18
- Date: 2026-11-17
- Steps: Q-7 (new: Q-7.1 to Q-7.13), Q-2; M10

## Context

The Python suite has about 8,600 tests and 80,800 test code lines. Since
[0084](0084-parallel-test-runs-with-pytest-xdist.md) every run is parallel: a full run takes about
6 minutes on the owner's machine and about 12 on the Windows test VM. The owner asked for an audit
that finds tests whose guarantee another test already gives, so that the suite gets smaller without
losing a guarantee, with speed as a secondary goal.

An audit at commit `38cf3eb` (branch `m10-hardening`) split the tests into 11 areas. One agent per
area read every test with a per-test coverage map, the decision records, `docs/status.md`, the
reports of the earlier test trim (`docs/test-trim-reports/`, 2026-10-17) and the history of each
test it proposed to touch; one more agent measured speed levers. Twelve fresh agents then tried to
prove each finding wrong, most of them by applying the change, running the tests and mutating the
product code. The result is in [docs/test-audit/](../test-audit/README.md):

- 110 findings (102 in the areas, 8 on speed). Verify confirmed 87, adjusted 20, rejected 3.
- Tier A (58 findings): about -71 tests and -520 code lines, and the speed levers: a full run
  373 s → 295 s on the owner's machine (measured twice on an idle machine), every test kept.
- Tier B (41 findings): about -393 tests and -540 code lines; a per-test timeout.
- Tier C (11 findings, not planned): guards that a record or plan names, rejected findings, and two
  speed ideas that are not faster or change the product.

The suite was already lean after the earlier trim and Q-6; the large gain is speed. The audit also
found that `-n auto` starts one worker per **physical** core (6 on the owner's machine, 12 logical),
not 12 as 0084 assumed, and that most of the lost wall time was the tail of `--dist load`.

The audit ran unattended. The choices it made in place of the owner are in
[docs/test-audit/decisions-taken.md](../test-audit/decisions-taken.md).

## Decision

1. M10 gets a step **Q-7 Test trimming**, with one step `Q-7.n` per work package of
   [docs/test-audit/plan.md](../test-audit/plan.md): Q-7.1 to Q-7.7 for Tier A, Q-7.8 to Q-7.13
   for Tier B.
2. Q-7 changes only tests and test configuration; it does not block the release
   ([decisions-taken.md](../test-audit/decisions-taken.md) D-18). The Tier A steps are recommended
   before v1.
3. Every package keeps every guarantee: a merge keeps every input and every assertion, and the
   name a document cites. Its "Done when" includes a whole-run coverage comparison (`coverage run`
   with `patch = ["subprocess"]`, [plan.md](../test-audit/plan.md) "Coverage comparison"): no
   covered line of `reframe` or `reframe_server` is lost, or the commit names the line and the test
   that still pins it.
4. A package that removes or renames a test that a decision record names changes that test-name
   reference in the same commit. The decision itself does not change; where a finding would need a
   decision changed, it is Tier C.
5. The speed levers change how the suite runs: `--dist worksteal` in `addopts` (Q-7.7) and, in
   Tier B, `pytest-timeout` (600 s, thread method) with `faulthandler_timeout` (Q-7.13). Q-7.7 adds an
   "Amended" note to 0084 (its `xdist_group` / `--dist loadgroup` advice does not apply under
   worksteal); Q-7.13 adds the timeout to `CLAUDE.md` Commands.
6. Tier C findings are not planned. They stay in the area files with the reason, so that the next
   audit does not report them again.
7. Each package is one conventional commit `test(Q-7.n): …` (`build(Q-7.13): …` for the dependency).
   The changelog reads them as tests and build changes (decision 0079).

## Consequences

- About 464 tests and 1,060 test code lines fewer after Tier A and B (5.4 % and 1.3 %); a full run
  about 24 % shorter on Linux, and an expected 1–2 minutes less of the VM's 12 (not measured).
- A test hang ends after 10 minutes with a stack dump instead of blocking a run until the CI job's
  30-minute limit (Q-7.13).
- The Windows half of SPD-04 (the fake tools' `.cmd` launcher) needs the Windows test VM; without
  it that part of Q-7.13 stays open and nothing depends on it.
- The gaps the audit found (not redundancy) are listed in
  [docs/test-audit/README.md](../test-audit/README.md) "What is missing or weak"; they are not
  part of Q-7.
- The owner should check [decisions-taken.md](../test-audit/decisions-taken.md) before the Tier B
  steps start; most of its entries only move a finding between Tier B and Tier C.

## Plan changes

- `docs/plan/09-quality-and-release.md`: new section "Q-7 Test trimming" with steps Q-7.1 to
  Q-7.13 and their "Done when"; Q-2's note on parallel runs says one worker per physical core.
- `docs/plan/08-roadmap.md`: M10 lists `Q-7`.
- `docs/status.md`: Q-7.1 to Q-7.13 as "Not started"; the M10 row and an entry in "Questions for
  the user that are still open".
