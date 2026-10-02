---
name: executing-plans
description: Execute approved multi-step implementation plans systematically with deterministic verification loops, checkpoint reporting, and error containment.
license: MIT
---

# Executing Plans

A disciplined framework for carrying out approved implementation plans safely, incrementally, and verifiably.

## Core Rules of Plan Execution

1. **Strict Adherence**: Follow the agreed-upon plan sequence. Do not jump ahead or take unapproved shortcuts.
2. **Phase-by-Phase Validation**: Never proceed to Phase $N+1$ until Phase $N$ passes all declared verification steps (unit tests, typecheck, lint).
3. **Surgical Modifications**: Touch only what is required by the current step. Avoid tangential cleanup.
4. **Immediate Halting on Anomalies**: If a change produces unexpected failures, breakages, or revealed design flaws, STOP immediately. Re-evaluate and surface the divergence before continuing.

---

## Execution Loop

```markdown
For each Phase in Plan:
  1. Announce current Phase and targeted files.
  2. Apply code modifications surgically.
  3. Run declared unit tests & type checks for that phase.
  4. Fix any local regressions immediately.
  5. Check off phase milestone and proceed.
```

---

## Handling Divergence & Unforeseen Issues

- **Minor Divergence** (e.g. slight signature adjustment, missing import): Correct locally and note in phase completion summary.
- **Major Divergence** (e.g. underlying architecture incompatibility, broken third-party contract):
  1. Pause execution immediately.
  2. Document the issue clearly: What happened vs what was planned.
  3. Propose a revised sub-plan or patch.
  4. Await user confirmation before resuming.

---

## Final Validation & Walkthrough

Once all phases have completed:
1. Run repo-wide gates (e.g. `pnpm run test`, `pnpm run typecheck`, `pnpm run build`).
2. Generate or update a comprehensive walkthrough summarizing:
   - Changes implemented across all files.
   - Test results and commands run.
   - Verification evidence.
