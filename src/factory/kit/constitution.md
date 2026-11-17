# [PRODUCT_NAME] Constitution

This constitution governs every spec, plan, task and line of code in this repository, whether
written by a person or by an agent. Spec Kit commands, the factory and the reviewer agent all
check work against it.

The **Product Principles** section belongs to this product: fill it in with
`/speckit-constitution` (architecture, stack, conventions, domain rules). The **Factory** sections
below are shared by every product built with the factory; change them only by upgrading the
factory kit.

## Product Principles

<!-- FACTORY: replace this comment with the product's principles, technology stack and
     conventions, e.g. by running /speckit-constitution. -->

## Factory: Spec and Task Rules

- A spec handed to the factory has no `[NEEDS CLARIFICATION]` markers left.
- `tasks.md` is organised into phases (`## Phase N: ...`). **The factory implements one phase
  per run, as one commit**, so every phase MUST be independently testable and fit the commit
  size limit in `.factory/factory.yaml` (default 300 changed lines, excluding `specs/` and the
  configured exclusions). Split any phase that would not.
- Task descriptions include exact file paths.
- Every behaviour change ships with its tests in the same commit.

## Factory: Agent Boundaries

Agents (the factory's implement, fix, rework and converge runs) MUST:
- Change only what the current phase requires, plus the feature's own `specs/` folder.
- Never change `.github/`, `.factory/`, `.specify/`, `.claude/`, `.mcp.json`, `CLAUDE.md`,
  this constitution, or any path listed under `protected` in `.factory/factory.yaml`.
- Never push to `main`. Commit only to the feature branch they were given.
- Run only git, Spec Kit scripts and the commands in `.factory/factory.yaml`.
- Never read, print or commit secrets.

## Factory: Workflow and Quality Gates

1. A developer runs `/factory-start <ISSUE>`, the Spec Kit commands, then `/factory-handoff`,
   which opens one draft PR `feature/<ISSUE> -> main`.
2. The factory implements each phase as one commit. `commands.verify` and `commands.checks`
   MUST pass before every commit; CI and the reviewer agent must pass before the next phase.
3. `speckit-converge` must report converged before the PR is marked ready.
4. A human reviews and merges the PR. Nothing reaches `main` any other way.

## Governance

- This constitution overrides any other guidance in the repository, including `CLAUDE.md`.
- Only humans amend it, through a normal PR that updates the version and dates below.
  Versioning: MAJOR for removed or redefined principles, MINOR for new principles or sections,
  PATCH for wording.
- The reviewer agent cites the section for every violation it reports.

**Version**: 0.1.0 | **Ratified**: [RATIFICATION_DATE] | **Last Amended**: [RATIFICATION_DATE]
