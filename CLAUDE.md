# CLAUDE.md

Operating guide for Claude Code in this repository. The constitution
(`.specify/memory/constitution.md`) overrides this file; read it before any change.

## Layout
- `src/slices/<name>/`: one vertical slice per feature (routes, logic, storage, events, tests, `SLICE.md`).
- `src/core/`: shared infrastructure only. `src/app/`: composes slices via `registry.py`.
- `src/market_es/`: the only place Spanish market terms may appear.
- `specs/NNN-*/`: Spec Kit artifacts (spec, plan, tasks) per feature.
- `factory/`: factory tooling, templates, limits. Do not modify.

## Commands
- `make all`: lint, strict type check, tests, size checks. Must pass before every commit.
- `make new-slice SLICE=<name>`: create a slice from the template.
- `make run`: start the API locally.

## Developer workflow (interactive)
1. `/factory-start <ISSUE>`: pull the Linear issue, create `feature/<ISSUE>`, start the spec.
2. `/speckit-clarify`, `/speckit-plan`, optionally `/speckit-checklist`, then `/speckit-tasks`.
3. `/factory-handoff`: analyze, check, push, open the draft PR, hand over to the factory.
4. `/factory-replan <ISSUE>`: revise remaining phases after the factory stops for a replan.

## Rules of thumb
- One phase of `tasks.md` = one commit, under 300 changed lines, with its tests.
- Slices never import each other; publish events through the outbox instead.
- Type everything; mypy runs in strict mode.
- Never commit to `main`, never commit secrets, never edit protected paths
  (`.github/`, `.specify/`, `.claude/`, `CLAUDE.md`, `factory/`).
