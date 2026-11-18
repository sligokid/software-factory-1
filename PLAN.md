# AI Software Factory

## Overview

The factory is a **product-agnostic** delivery pipeline. It can build any app, frontend or backend, in any language, as long as the app's repository follows a small contract (`.factory/factory.yaml`).

A developer turns a Linear issue, or a document they provide, into a Spec Kit spec and task list in one interactive Claude Code session inside the product repo, then hands it to the factory. The factory implements each phase of the task list in a sandboxed, headless Claude Code container, one commit per phase on a feature branch, checks the result with Spec Kit's converge step, and delivers **one pull request** with a live preview. Reviewing and merging that PR is the only human step after handover.

## Factory and products

```
┌──────────────────────── software-factory (this repo) ───────────────────────┐
│ dispatcher        phase loop in GitHub Actions: triggers, limits, status    │
│ runner images     sandboxed Claude Code + Spec Kit, one per toolchain       │
│                   (base, python, node; more as needed)                      │
│ CI workflows      reusable GitHub workflows called by product repos         │
│ reviewer          read-only agent review against the product's constitution │
│ preview           per-feature preview from the product's compose file       │
│ developer kit     /factory-start, /factory-handoff, /factory-replan,        │
│                   `factory init` installer, constitution base               │
└─────────────────────────────────────────────────────────────────────────────┘
                 │ reads .factory/factory.yaml, calls its commands
                 ▼
┌──── product repo A (e.g. backend API) ───┐  ┌──── product repo B (e.g. web app) ────┐
│ .factory/factory.yaml   contract         │  │ .factory/factory.yaml                 │
│ .specify/  constitution (product rules)  │  │ .specify/  constitution               │
│ .claude/   speckit-* + factory-* skills  │  │ .claude/                              │
│ CLAUDE.md  specs/  source  tests         │  │ CLAUDE.md  specs/  source  tests      │
│ compose.preview.yaml                     │  │ compose.preview.yaml                  │
│ .github/workflows/factory.yml (3 lines)  │  │ .github/workflows/factory.yml         │
└──────────────────────────────────────────┘  └───────────────────────────────────────┘
```

The factory knows nothing about a product's language, framework, database or architecture. Everything product-specific lives in the product repo: its constitution, its commands, its extra checks and its preview stack.

## The product contract: `.factory/factory.yaml`

```yaml
version: 1
runner: node            # runner image: base | python | node
commands:
  setup:  pnpm install --frozen-lockfile
  verify: pnpm lint && pnpm typecheck && pnpm test   # must pass before every commit
  checks: pnpm check:architecture                     # optional product-specific rules
preview:
  compose: compose.preview.yaml   # stack for the feature preview
  service: web                    # service the preview URL points at
  port: 3000
  healthcheck: /                  # path that must return 2xx after deploy
  ui: true                        # reviewer also takes Playwright screenshots
egress:                           # extra hosts the agent may reach
  - registry.npmjs.org
limits:
  commit_lines: 300
  exclude: [pnpm-lock.yaml, "specs/**"]
  files:
    CLAUDE.md: 120
    .specify/memory/constitution.md: 250
protected:                        # added to the factory's default protected paths
  - src/generated/**
```

Defaults the factory always applies: agents never push to `main`; never touch `.github/`, `.factory/`, `.specify/` (outside the feature's spec folder), `.claude/` or `CLAUDE.md`; egress always allows the Anthropic API and GitHub.

## Workflow

The factory's unit of work is one **phase** of `tasks.md`. Each phase is implemented in one run and lands as one commit under the size limit.

```
1. DEVELOPER (Claude Code, interactive, in the product repo)
───────────────────────────────────────
Linear issue ENG-123          or    a document (docs/feature.md)
   │  /factory-start ENG-123        /factory-start docs/feature.md [--id name]
   │    creates feature/<ID>, records the source in specs/<dir>/source.yaml
   │    Linear mode: Linear -> In spec   (document mode: no Linear at all)
   ▼
speckit-specify -> speckit-clarify -> speckit-plan -> (speckit-checklist) -> speckit-tasks
   │  /factory-handoff
   │    runs speckit-analyze; checks tasks.md, no open questions, phase sizes;
   │    runs `verify`; pushes the spec, opens a draft PR, adds label factory:ready
   │    Linear mode: Linear -> Ready for agent
   ▼
2. FACTORY (headless, autonomous)
───────────────────────────────────────
Linear -> Agent working; preview started from compose.preview.yaml
   │
   ├─► for each phase, in order:
   │     fresh container (runner from factory.yaml) -> `setup`
   │     speckit-implement phase -> `verify` + `checks` -> commit -> push
   │     CI + reviewer agent on the commit
   │       pass -> next phase
   │       fail -> fix run (max 2), then Agent failed
   │     preview redeploys; Linear comment with phase, commit, run time, usage
   │
   ├─► speckit-converge
   │     gaps -> new phases appended to tasks.md and implemented as more commits,
   │             converge again (max 2 rounds, then Agent failed)
   │
   └─► PR marked ready, Linear -> Awaiting approval
         PR description: phase table, converge result, reviewer summary,
         preview link (and screenshots for UI products)
   ▼
3. REVIEW (you)
───────────────────────────────────────
review the PR and try the preview
   ├─ merge            -> preview removed, Linear -> Done, metrics recorded
   ├─ request changes  -> rework run adds commits, review again (max 2 rounds)
   └─ close            -> Linear -> Needs replan
```

### Exceptions

| Situation | What happens |
|-----------|--------------|
| Phase fails CI or review twice, timeout, turn limit or crash | Container removed. Linear -> Agent failed, with the log tail and a transcript link. `factory replay ISSUE=X PHASE=Y` reproduces it locally. |
| Changes requested, or `@agent` comment on the PR | Rework run reads the comments, adds commits, re-runs CI, converge and the reviewer, then re-requests review. |
| Approach is wrong | Close the PR or comment `@agent replan`. Linear -> Needs replan. Developer runs `/factory-replan ENG-123`, edits the remaining phases and hands over again. |
| Human takeover | Add the `human-takeover` label to pause the factory, push your own commits, remove the label to resume. |
| Feature abandoned | Close the PR and delete the branch. The preview is removed. |

### Feature sources and status

A feature starts from either source. `specs/<dir>/source.yaml` records which one, and every
factory step reads it.

| | Linear mode | Document mode |
|---|---|---|
| Start | `/factory-start ENG-123` | `/factory-start docs/feature.md [--id name]` |
| Feature id and branch | issue key, `feature/ENG-123` | `--id` or a slug of the title, `feature/<id>` |
| Factory trigger | Linear state Ready for agent (and the PR label) | PR label `factory:ready` |
| Status updates | Linear state and comments, plus PR comments | PR labels and comments only |
| Linear used | yes | never |

Linear states: Todo · In spec · Ready for agent · Agent working · Awaiting approval · Needs replan · Agent failed · Done

PR labels (both modes): `factory:ready` · `factory:working` · `factory:awaiting-review` · `factory:needs-replan` · `factory:failed`

In the workflow above, "Linear -> X" applies in Linear mode only; the matching PR label is always set.

### State and metrics

The factory is stateless. Issue state comes from Linear, progress from the checked tasks in `tasks.md` and the branch's commits, review state from the PR. Metrics (lead time, phases, fixes, rework, converge gaps, usage) are emitted as OpenTelemetry metrics to the factory's Grafana.

## Prerequisites

| # | Item | Needed for |
|---|------|-----------|
| P1 | GitHub repo for `software-factory` (this folder), plus a test product repo, attached to the project | Stage 3 |
| P2 | Not needed: stage 4 pushes with the workflow's `GITHUB_TOKEN` and chains runs with `workflow_dispatch`. A GitHub App is only needed if branch protection must block that token. | - |
| P3 | Linear access and the eight states above; Linear MCP in developers' Claude Code (Linear mode only) | Stages 1 and 4 |
| P4 | `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Stages 2 and 4 |
| P5 | Host with Docker for live previews (self-hosted runner). Agent runs and CI use GitHub-hosted runners; local agent runs use a developer machine with Docker. | Stage 3 (previews) |
| P6 | Package mirrors or registries to allow (PyPI, npm) | Stage 2 |
| P7 | ngrok reserved domain for preview URLs (`eng-123.<domain>`), with basic auth or an IP allowlist | Stage 3 |

## Stages

### Stage 1: Factory core and developer kit ✅
- [x] Repo layout: a `factory` Python package (CLI, contract, checks, developer kit); later stages add `runner/`, `.github/workflows/`, `dispatcher` and `reviewer` modules.
- [x] `factory.yaml` JSON schema and a validator (`factory validate`).
- [x] Generic checks driven by `factory.yaml`: commit size, file size limits, protected paths.
- [x] Developer kit: `factory init` (runs `specify init`, installs the `factory-*` skills, writes a starter `factory.yaml`, constitution base and `CLAUDE.md`); `/factory-start`, `/factory-handoff`, `/factory-replan` using the contract's commands.
- [x] Constitution base: workflow, agent boundaries and quality gates shared by every product. Products add their own principles.
- [x] No product code in this repo. Products are created later with `factory init`.

**Done when:** `factory init` turns an empty folder into a valid product skeleton that passes `factory validate`, and the factory's own tests pass.

### Stage 2: Runner images and sandbox ✅
- [x] `runner-base` (Claude Code, Spec Kit, git, gh) plus `runner-python` and `runner-node` layered on it.
- [x] Non-root, no capabilities, no Docker socket, no host mounts, read-only root, CPU, memory and process limits.
- [x] Egress: Anthropic API and GitHub, plus the product's `egress` list.
- [x] Entrypoint refuses `ANTHROPIC_API_KEY`, requires `CLAUDE_CODE_OAUTH_TOKEN`, runs `setup`, then the mode: implement a phase, converge, fix, rework.
- [x] Tool allowlist: git plus the product's `setup`, `verify` and `checks` commands and Spec Kit scripts.
- [x] Transcript saved per run; `factory agent` and `factory replay` for local runs.

**Done when:** a manual run against a test product implements one phase as one commit, other hosts are unreachable, and an API key stops the container.

### Stage 3: CI, reviewer and preview ✅
- [x] Reusable workflow (`uses: <org>/software-factory/.github/workflows/product.yml@v1`) that reads `factory.yaml` and runs `setup`, `verify`, `checks`, the generic checks, SAST, secret scan and dependency scan.
- [x] Read-only reviewer agent against the product's constitution, per commit and on the finished PR; Playwright screenshots when `preview.ui` is true.
- [x] Preview: the product's `compose.preview.yaml` started per feature PR, exposed through ngrok, health-checked, redeployed on push, removed on merge or close.

**Done when:** each check fails on a bad commit and passes on a clean one in a test product, and its preview shows the latest commit.

**Verified with a real Claude agent** (2026-11-18): a two-phase stdlib test product, one commit per phase, `verify` green, egress only to the Anthropic API, no tool denials, about $0.08 per phase; `factory replay` keeps its result under `refs/factory/runs/`. It found that build leftovers (`__pycache__`) were committed, fixed with a system git excludes file in `runner-base`.

**Verified on GitHub** (2026-11-18): `v1` published the runner images to ghcr.io (public). In the test product `sligokid/software-factory-product-1`, the clean feature branch passes every check, and one bad commit per check fails only that step: verify, commit size, agent protected path, secret scan, SAST, dependency scan. It found that `factory init` pointed products at the wrong image prefix when the factory repo is not named `software-factory` (fixed).

The reviewer ran on the ready PR and posted its comment (pass, 2 advisory findings).

**Untested:** the public ngrok preview and its traffic policy (needs a reserved domain and `NGROK_AUTHTOKEN`; only the local preview has run).

### Stage 4: Dispatcher on GitHub Actions
The dispatcher is not a service: it is part of the reusable workflow, and every step runs on GitHub-hosted runners. Each workflow run does one step of the loop and then starts the next run itself, so after `/factory-handoff` nothing is manual until the PR is ready for review. It automates exactly the decisions in `MANUAL-FLOW.md`.

```text
developer: /factory-handoff -> draft PR + label factory:ready
   |
   v  pull_request labeled | workflow_dispatch (from the previous run) | pull_request_review | issue_comment
one run of product.yml, concurrency group per feature branch
   agent    ubuntu-latest (Docker preinstalled): factory agent implement|fix|converge|rework
            in the same sandbox as locally (runner image from ghcr.io); push with GITHUB_TOKEN
   checks   as in stage 3, on the new commit
   review   as in stage 3, on the new commit
   next     reads state from GitHub and decides:
              passed, phases left      -> dispatch implement (next phase)
              failed, fixes left       -> dispatch fix (failure report as feedback)
              all phases [X]           -> dispatch converge
              converge added a phase   -> dispatch implement
              converged                -> PR ready, factory:awaiting-review
              limit hit, timeout, crash -> factory:failed + comment, stop
   |
   v  pull_request ready_for_review -> reviewer on the whole PR (stage 3)
developer: merge | request changes (-> rework) | close (-> factory:needs-replan)
```

Why this works without a server or a GitHub App: pushes made with `GITHUB_TOKEN` do not start workflows, but `workflow_dispatch` is the documented exception, so the run itself runs checks and review as later jobs and then dispatches the next step. State lives only in GitHub: done phases in `tasks.md`, counters in a marker in the PR body, history in PR comments.

- [x] `factory next`: reads `tasks.md`, the PR, its labels and the marker, and the run's job results; prints the next step (mode, phase, feedback) or a final state. Pure decision logic, unit-tested on recorded states.
- [x] Limits, from `factory.yaml` with defaults: 2 fixes per phase, 2 converge rounds, 2 rework rounds, the existing turn limit and wall-clock timeout.
- [x] `product.yml`: `agent` and `next` jobs; `agent` installs the factory CLI from the wheel in the runner image, runs `factory agent` and pushes; `checks` and `review` run after it in the same run; the failure report from `checks` goes to `next` as an artifact.
- [x] Kit `factory.yml`: triggers `workflow_dispatch` (inputs: branch, mode, phase), `pull_request` labeled, `pull_request_review` and `issue_comment` (`@agent`); permissions `contents: write`, `actions: write`, `pull-requests: write`.
- [x] Status: PR labels (`factory:working`, `factory:awaiting-review`, `factory:failed`, `factory:needs-replan`), a comment per run (phase, commit, turns, cost, time, transcript artifact link), the phase table in the PR body. `human-takeover` label pauses the loop.
- [x] Run folders (`run.json`, transcript, runner and egress logs) uploaded as Actions artifacts; `factory replay` accepts a downloaded artifact.
- [ ] Linear mode: a relay from the Linear webhook to `repository_dispatch` (or a scheduled workflow polling Linear), and Linear states and comments when `source.yaml` says `linear`.
- [ ] OTel metrics, or a metrics summary per feature in the final PR comment until a collector exists.

Not on GitHub-hosted runners: a live preview link, because a preview outlives a job. It keeps the self-hosted preview runner (P5) from stage 3. The reviewer's screenshots can instead come from a short-lived stack started inside the review job.

Cost: free on public product repos; private repos use Actions minutes for every agent run. Each run must fit in one job (6 hours; the factory's timeout is 1 hour). Agents run on amd64 images, as CI does.

**Verified on GitHub** (2026-11-18, `sligokid/software-factory-product-1`):
- PR #3 (GREET-3, two phases): label -> implement 1 -> implement 2 -> converge (converged) -> final whole-PR review -> `factory:awaiting-review`, every step chained by `workflow_dispatch`, no manual step; about $0.60 of agent runs. Converting the draft failed (`Resource not accessible by integration`); fixed in 0.4.2 (`contents: write` on `next`, and a comment instead of a crash).
- PR #2 (GREET-2): review failures dispatched two fix runs, then the limit set `factory:failed`. It exposed a reviewer deadlock (a fix removed files a review asked it to remove, the next review called that out of scope), fixed in 0.4.1 with `factory review --addressing`. Closing the PR set `factory:needs-replan`.

**Not verified yet:** a fix run that turns a failed phase green, a forced timeout, rework from a requested change or an `@agent` comment, `human-takeover`, the draft conversion in 0.4.2, `factory replay` from a downloaded `factory-run` artifact. Not built: Linear mode, metrics.

**Done when:** in the test product, a two-phase document-mode feature handed over with `/factory-handoff` ends as one ready PR with no manual step; a forced CI failure is fixed by a fix run; a forced timeout ends in `factory:failed`; a requested change produces a rework commit; closing the PR sets `factory:needs-replan`. Linear mode: the same feature from a Linear issue ends with the correct Linear states and comments.

### Stage 5: Pilot products
- [ ] Pilot products and their specifics (stack, constitution, preview stack) are defined later, outside this repo.

**Done when:** a pilot feature reaches `main` through one Claude Code session and one PR, with no human step after handover other than review and merge.

## Schedule (today, Europe/Dublin)

| Time | Work |
|------|------|
| 12:45 – 14:45 | Stage 1 |
| 14:45 – 17:15 | Stage 2 |
| 17:15 – 19:15 | Stage 3 |
| 19:15 onward | Stages 4 and 5 |

Stages 1 and 2 need no prerequisites. Stages 3 to 5 start as P1 to P7 are ready. Times are estimates.
