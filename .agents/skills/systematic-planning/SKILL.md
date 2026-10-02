---
name: systematic-planning
description: Formulate crisp, executable multi-phase implementation plans for non-trivial features, refactors, and architectural migrations. Use before writing code on any task with multiple files, uncertain requirements, or breaking changes.
license: MIT
---

# Systematic Planning

A methodology for engineering rigorous, executable plans for complex features, bug fixes, refactors, and migrations.

## When to Create a Plan

Create a systematic plan whenever a task involves:
- Changes spanning $>2$ files or across package boundaries
- Introducing or altering service definitions, APIs, or data schemas
- High risk of regression or complex state management
- Ambiguous requirements requiring decision alignment

---

## Plan Structure Standard

An implementation plan should be structured as follows:

```markdown
# [Feature / Bug / Refactor Title]

## 1. Problem Statement & Objectives
- Current behavior and pain points.
- Concrete target end state.

## 2. Assumptions & Constraints
- Explicitly stated technical assumptions.
- Performance, security, and backwards-compatibility boundaries.

## 3. Architecture & Impact Analysis
- Core capability seams / plugins involved.
- Breaking vs non-breaking changes.
- Invariants that must be preserved.

## 4. Proposed File Changes
- `[NEW]` `path/to/new_file.ts` — purpose and exported interfaces.
- `[MODIFY]` `path/to/existing.ts` — exact changes, signatures, and logic updates.
- `[DELETE]` `path/to/deprecated.ts` — safe deletion rationale.

## 5. Step-by-Step Implementation Sequence
1. Phase 1: Core contracts, schemas, and types.
2. Phase 2: Implementation / provider logic.
3. Phase 3: Consumer integration and UI components.
4. Phase 4: Unit, integration, and e2e test suites.

## 6. Verification Plan
- **Automated Tests**: exact command(s) to run (e.g., `pnpm run test`, `pnpm run typecheck`).
- **Manual / Scenario Validation**: step-by-step reproduction or verification instructions.
```

---

## Best Practices

1. **Topological Ordering**: Order changes by dependency (core types/interfaces first $\rightarrow$ service providers $\rightarrow$ consumers $\rightarrow$ documentation/tests).
2. **Deterministic Verification**: Every phase must declare a concrete check (a test or command) proving that phase succeeded before moving to the next.
3. **Rollback Resilience**: Keep steps granular so that unexpected blockers allow clean rollbacks without leaving broken intermediate states.
