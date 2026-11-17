# AI Software Factory

## Overview

A developer turns a Linear issue into a Spec Kit spec and task list in one interactive Claude Code session, then hands it to the factory. The factory implements every task in a sandboxed, headless Claude Code container, one commit per task on a feature branch, checks the result with Spec Kit's converge step, and delivers **one pull request** to `main` with a live preview. Reviewing and merging that PR is the only human step after handover.

## Workflow

The factory's unit of work is one **phase** of `tasks.md` (Spec Kit groups tasks into phases). Each phase is implemented in one run and lands as one commit under the size limit. "Task" below means a phase.

```
1. DEVELOPER (Claude Code, interactive)
───────────────────────────────────────
Linear issue ENG-123 (Todo)
   │  /factory-start ENG-123
   │    pulls the issue, creates feature/ENG-123, Linear -> In spec
   ▼
speckit-specify -> speckit-clarify -> speckit-plan -> (speckit-checklist) -> speckit-tasks
   │  /factory-handoff
   │    runs speckit-analyze; checks tasks.md, no open questions, task sizes
   │    pushes the spec, opens a draft PR feature/ENG-123 -> main, starts the preview
   │    Linear -> Ready for agent
   ▼
2. FACTORY (headless, autonomous)
───────────────────────────────────────
Linear -> Agent working
   │
   ├─► for each task T1..Tn, in order:
   │     fresh container -> speckit-implement Ti -> make lint test -> commit -> push
   │     CI + reviewer agent on the commit
   │       pass -> next task
   │       fail -> fix run (max 2), then Agent failed
   │     preview redeploys; Linear comment with task, commit, run time, usage
   │
   ├─► speckit-converge
   │     gaps -> gap tasks appended to tasks.md and implemented as more commits,
   │             converge again (max 2 rounds, then Agent failed)
   │
   └─► PR marked ready, Linear -> Awaiting approval
         PR description: task table, converge result, reviewer summary, preview link
   ▼
3. REVIEW (you)
───────────────────────────────────────
review the PR and try the preview
   ├─ merge            -> preview removed, Linear -> Done, metrics logged
   ├─ request changes  -> rework run adds commits, review again (max 2 rounds)
   └─ close            -> Linear -> Needs replan
```

### Exceptions

| Situation | What happens |
|-----------|--------------|
| Task fails CI or review twice, timeout, turn limit or crash | Container removed. Linear -> Agent failed, with the log tail and a transcript link. `make replay ISSUE=X TASK=Y` reproduces it locally. |
| Changes requested, or `@agent` comment on the PR | Rework run reads the comments, adds commits, re-runs CI, converge and the reviewer, then re-requests review. |
| Approach is wrong | Close the PR or comment `@agent replan`. Linear -> Needs replan. Developer runs `/factory-replan ENG-123`, edits the remaining tasks and hands over again. |
| Human takeover | Add the `human-takeover` label to pause the factory, push your own commits, remove the label to resume at the next task. |
| Feature abandoned | Close the PR and delete the branch. The preview is removed. `main` is untouched. |

### Linear states

Todo · In spec · Ready for agent · Agent working · Awaiting approval · Needs replan · Agent failed · Done

### Guarantees

- One open PR per issue. Nothing reaches `main` until you merge it.
- Every task commit passes CI and the reviewer before the next task starts.
- Each task commit stays under about 300 changed lines, so the PR can be reviewed commit by commit.
- Agents never push to `main`, and never touch `.github/`, `.specify/` (outside the feature's spec folder), `.claude/`, `CLAUDE.md` or `factory/`.

## Components

| Component | What it does |
|-----------|--------------|
| Repo and rules | Spec Kit (`.specify/`, constitution), `CLAUDE.md`, `slices/<name>/SLICE.md`, `market_es/`, size limits |
| Developer commands | `/factory-start`, `/factory-handoff`, `/factory-replan` in Claude Code, plus a Linear issue template |
| Local platform | Docker Compose: Postgres, Redpanda, Azurite, Durable Task emulator, OTel collector, Grafana; outbox library and tracing |
| Agent runner | Hardened container running Claude Code headless with Spec Kit; modes: implement, converge, fix, rework |
| CI and reviewer | Tests, lint, types, SAST, secret and dependency scans, architecture and size checks, read-only reviewer agent |
| Preview | One Compose stack per feature PR, exposed through ngrok, redeployed on every push |
| Dispatcher | Watches Linear and GitHub, runs tasks in order, enforces limits, writes back to Linear, records metrics |

## Prerequisites

| # | Item | Needed for |
|---|------|-----------|
| P1 | GitHub repo with this folder pushed, attached to the project, `main` protected (PR and review required) | Stage 4 |
| P2 | GitHub App (contents, pull requests, checks) to mint a token per run | Stage 5 |
| P3 | Linear access and the eight states above; Linear MCP in developers' Claude Code | Stages 1 and 5 |
| P4 | `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Stages 3 and 5 |
| P5 | Host for the dispatcher, agent containers and previews, with Docker | Stages 2 and 5 |
| P6 | Package mirror for the egress allowlist (PyPI or a proxy) | Stage 3 |
| P7 | ngrok reserved domain for preview URLs (`eng-123.<domain>`), with basic auth or an IP allowlist | Stage 4 |
| P8 | ESIOS API token from Red Eléctrica | Stage 6, ESIOS run |

## Stages

### Stage 1: Repo, Spec Kit and developer commands (about 2h)
- `specify init --here` with the Claude Code integration, version pinned.
- Constitution: architecture, slice boundaries, stack, storage, event conventions, Spanish market rules, agent boundaries.
- `CLAUDE.md`, `SLICE.md` template, `market_es/`, `factory/`, `pyproject.toml` (uv), ruff, pytest, type checker, `Makefile`, size limits config.
- `/factory-start`, `/factory-handoff`, `/factory-replan`, and the Linear issue template.

**Done when:** `make lint test` passes, Spec Kit commands work in Claude Code, and the constitution is agreed.

### Stage 2: Local platform (about 2h)
- `docker-compose.yml` with all six services and health checks.
- Outbox library (Postgres to Redpanda) and OTel tracing to Grafana.
- Example slice proving events and traces.

**Done when:** `docker compose up` is healthy and the example slice's event and trace both appear.

### Stage 3: Agent runner (about 2.5h)
- Image: non-root, no capabilities, no Docker socket, no host mounts, read-only root, CPU, memory and process limits, pinned `specify-cli`.
- Egress limited to the Anthropic API, GitHub and the package mirror.
- Entrypoint refuses `ANTHROPIC_API_KEY`, requires `CLAUDE_CODE_OAUTH_TOKEN`, checks out the feature branch rebased on `main`.
- Tool allowlist: git, uv, pytest, ruff, make targets, Spec Kit scripts. File access limited to the checkout and tmp.
- Modes: implement one task as one commit, converge, fix (from CI output), rework (from PR comments).
- Transcript saved per run; `make agent` and `make replay` for local runs.

**Done when:** a manual run implements one task as one commit, other hosts are unreachable, and an API key stops the container.

### Stage 4: CI, reviewer and preview (about 2h)
- Workflows on every push to `feature/*` and on the PR: tests, lint, types, SAST, secret scan, dependency scan.
- Custom checks: commit size, slice isolation, Spanish terms only in `market_es`, protected paths, file size limits, `tasks.md` format.
- Read-only reviewer agent against the constitution and `SLICE.md`, per commit and on the finished PR.
- Preview stack per feature PR via ngrok, redeployed on push, removed on merge or close, nightly cleanup.

**Done when:** each check fails on a bad commit and passes on a clean one, and the preview shows the latest commit.

### Stage 5: Dispatcher and Linear integration (about 2.5h)
- Linear webhook (or 30-second polling) for Ready for agent; GitHub events for reviews, comments, close and labels.
- Runs tasks in order, waits for CI and review per commit, runs fixes, converge, rework and replan with their limits.
- New container and repo-scoped GitHub App token per run; turn limit and wall-clock timeout.
- Linear state changes and comments; metrics for lead time, tasks, fixes, rework, converge gaps and usage.

**Done when:** a two-task issue ends as one ready PR with correct Linear states and comments, a forced timeout lands in Agent failed, and closing the PR lands in Needs replan.

### Stage 6: Acceptance runs
- Run 1: hello world endpoint.
- Run 2: ESIOS daily price slice.

**Done when:** each feature reaches `main` through one Claude Code session and one PR, with no human step after handover other than review and merge.

## Schedule (today, Europe/Dublin)

| Time | Work |
|------|------|
| 12:00 – 14:00 | Stage 1 |
| 14:00 – 16:00 | Stage 2 |
| 16:00 – 18:30 | Stage 3 |
| 18:30 – 20:30 | Stage 4 |
| 20:30 onward | Stages 5 and 6 |

Stages 1 to 3 need no prerequisites. Stages 4 to 6 start as P1 to P8 are ready.
