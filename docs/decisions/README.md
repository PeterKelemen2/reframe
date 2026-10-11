# Decision records

A decision record explains a choice that the plan (`docs/plan/`) did not make, or a place
where the plan was wrong or could not be done.

## Rules

- One file per decision: `NNNN-short-kebab-title.md`, numbered in order, never reused.
- `0001-desktop-shell.md` (step `D-0`) and `0002-bundled-ffmpeg.md` (step `D-7`) are reserved
  by the plan. New records start at `0003`.
- A record that changes the plan updates the affected plan file **in the same commit**.
- Do not edit an accepted record to change its decision. Write a new record that supersedes it.

## Template

```markdown
# NNNN — Title

- Status: accepted | superseded by NNNN
- Date: YYYY-MM-DD
- Steps: C-x, F-y

## Context
What the plan says, and what we found (with the command and output that shows it).

## Decision
What we do instead.

## Consequences
What changes, what we lose, what to revisit.

## Plan changes
The plan files and sections updated in this commit.
```
