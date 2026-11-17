# Software Factory Constitution

This constitution governs every spec, plan, task and line of code in this repository, whether
written by a person or by an agent. Spec Kit commands, the factory and the reviewer agent all
check work against it.

## Core Principles

### I. Vertical Slices
Each feature lives in exactly one slice under `src/slices/<name>/`, with its own routes, logic,
storage, events, tests and `SLICE.md`.
- A slice MUST NOT import another slice. Slices interact only through events.
- Shared infrastructure lives in `src/core/` (config, telemetry, outbox, db). `core` MUST NOT
  contain business logic and MUST NOT import slices.
- `src/app/` only composes slices: a slice is active once its router is listed in
  `src/app/registry.py`.
- A new slice is created with `make new-slice SLICE=<name>`.

### II. Market Isolation
All Spanish electricity market vocabulary and rules (ESIOS, REE, OMIE, PVPC, peajes, tariff
periods, Spanish holidays and time zone rules) live in `src/market_es/`. These terms MUST NOT
appear in identifiers, strings or comments anywhere else. Slices import them from `market_es`.

### III. Test-First, Small Steps
- Every behaviour change ships with tests in the same commit. Slice tests live in
  `src/slices/<name>/tests/`.
- `make all` (lint, strict type check, tests, size checks) MUST pass before every commit.
- Each implementation unit stays under the commit size limit in `factory/limits.toml`
  (300 changed lines, excluding lock files and `specs/`).

### IV. Events Through the Outbox
- State changes that other slices care about are published as events. An event is written to
  the outbox table in the same database transaction as the state change, then relayed to Redpanda.
- Event names: `<slice>.<event>.v<major>` (e.g. `prices.daily_published.v1`). Payloads are JSON
  with a documented schema in the slice's `SLICE.md`. Breaking changes need a new major version.
- Consumers MUST be idempotent.

### V. Observable by Default
- Every inbound request, consumed event and scheduled job runs in an OpenTelemetry span that
  reaches the collector (and Grafana).
- Logs are structured (JSON) and carry the trace id. No secrets or personal data in logs.

### VI. Simplicity
- Prefer the standard library and the approved stack. New runtime dependencies need a reason
  in the plan.
- No speculative abstraction: build what the current spec needs.

## Technology Stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.12, fully typed (mypy strict) |
| Packaging and tasks | uv, Makefile |
| HTTP | FastAPI, Uvicorn |
| Database | PostgreSQL |
| Messaging | Redpanda (Kafka API) via the outbox |
| Blob storage | Azure Blob Storage (Azurite locally) |
| Workflows and schedules | Durable Task (emulator locally) |
| Observability | OpenTelemetry, collector, Grafana |
| Quality | ruff (lint and format), pytest, mypy |

Local development uses `docker compose up` for every dependency. Times are stored in UTC;
local-time rules belong to the market package that needs them.

## Spec and Task Rules

These rules make specs safe to hand to the factory.
- A spec handed to the factory has no `[NEEDS CLARIFICATION]` markers left.
- A spec names the one slice it changes (or creates). Features that need two slices are split
  into two specs.
- `tasks.md` is organised into phases (`## Phase N: ...`). **The factory implements one phase
  per run, as one commit**, so every phase MUST be independently testable and fit the commit
  size limit. Split any phase that would not.
- Task descriptions include exact file paths.

## Agent Boundaries

Agents (the factory's implementation, fix, rework and converge runs) MUST:
- Change only the slice named in the spec, `src/app/registry.py` (to register that slice),
  `src/market_es/` when the spec requires it, and the feature's own `specs/` folder.
- Never change `.github/`, `.specify/`, `.claude/`, `CLAUDE.md`, `factory/` or this
  constitution.
- Never push to `main`. Commit only to the feature branch they were given.
- Use only the allowlisted tools: git, uv, pytest, ruff, mypy, make targets, Spec Kit scripts.
- Never read or print secrets.

## Workflow and Quality Gates

1. A developer runs `/factory-start <ISSUE>`, then the Spec Kit commands, then
   `/factory-handoff`, which opens one draft PR `feature/<ISSUE> -> main`.
2. The factory implements each phase as one commit. CI and the reviewer agent must pass on
   every commit before the next phase starts.
3. `speckit-converge` must report converged before the PR is marked ready.
4. A human reviews and merges the PR. Nothing reaches `main` any other way.

## Governance

- This constitution overrides any other guidance in the repository, including `CLAUDE.md`.
- Only humans amend it, through a normal PR that updates the version and dates below.
  Versioning: MAJOR for removed or redefined principles, MINOR for new principles or sections,
  PATCH for wording.
- The reviewer agent cites the principle number for every violation it reports.

**Version**: 1.0.0 | **Ratified**: 2026-11-17 | **Last Amended**: 2026-11-17
