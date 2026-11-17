# AI Software Factory

## Overview

The factory is a **product-agnostic** delivery pipeline. It can build any app, frontend or backend, in any language, as long as the app's repository follows a small contract (`.factory/factory.yaml`).

A developer turns a Linear issue, or a document they provide, into a Spec Kit spec and task list in one interactive Claude Code session inside the product repo, then hands it to the factory. The factory implements each phase of the task list in a sandboxed, headless Claude Code container, one commit per phase on a feature branch, checks the result with Spec Kit's converge step, and delivers **one pull request** with a live preview. Reviewing and merging that PR is the only human step after handover.

## Factory and products

```
┌──────────────────────── software-factory (this repo) ───────────────────────┐
│ dispatcher        Linear + GitHub watcher, phase loop, limits, metrics      │
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
| P2 | GitHub App (contents, pull requests, checks) installed on product repos, to mint a token per run | Stage 4 |
| P3 | Linear access and the eight states above; Linear MCP in developers' Claude Code (Linear mode only) | Stages 1 and 4 |
| P4 | `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Stages 2 and 4 |
| P5 | Host for the dispatcher, agent containers and previews, with Docker | Stages 2 to 4 |
| P6 | Package mirrors or registries to allow (PyPI, npm) | Stage 2 |
| P7 | ngrok reserved domain for preview URLs (`eng-123.<domain>`), with basic auth or an IP allowlist | Stage 3 |

## Stages

### Stage 1: Factory core and developer kit
- Repo layout: a `factory` Python package (CLI, contract, checks, developer kit); later stages add `runner/`, `.github/workflows/`, `dispatcher` and `reviewer` modules.
- `factory.yaml` JSON schema and a validator (`factory validate`).
- Generic checks driven by `factory.yaml`: commit size, file size limits, protected paths.
- Developer kit: `factory init` (runs `specify init`, installs the `factory-*` skills, writes a starter `factory.yaml`, constitution base and `CLAUDE.md`); `/factory-start`, `/factory-handoff`, `/factory-replan` using the contract's commands.
- Constitution base: workflow, agent boundaries and quality gates shared by every product. Products add their own principles.
- No product code in this repo. Products are created later with `factory init`.

**Done when:** `factory init` turns an empty folder into a valid product skeleton that passes `factory validate`, and the factory's own tests pass.

### Stage 2: Runner images and sandbox
- `runner-base` (Claude Code, Spec Kit, git, gh) plus `runner-python` and `runner-node` layered on it.
- Non-root, no capabilities, no Docker socket, no host mounts, read-only root, CPU, memory and process limits.
- Egress: Anthropic API and GitHub, plus the product's `egress` list.
- Entrypoint refuses `ANTHROPIC_API_KEY`, requires `CLAUDE_CODE_OAUTH_TOKEN`, runs `setup`, then the mode: implement a phase, converge, fix, rework.
- Tool allowlist: git plus the product's `setup`, `verify` and `checks` commands and Spec Kit scripts.
- Transcript saved per run; `factory agent` and `factory replay` for local runs.

**Done when:** a manual run against a test product implements one phase as one commit, other hosts are unreachable, and an API key stops the container.

### Stage 3: CI, reviewer and preview
- Reusable workflow (`uses: <org>/software-factory/.github/workflows/product.yml@v1`) that reads `factory.yaml` and runs `setup`, `verify`, `checks`, the generic checks, SAST, secret scan and dependency scan.
- Read-only reviewer agent against the product's constitution, per commit and on the finished PR; Playwright screenshots when `preview.ui` is true.
- Preview: the product's `compose.preview.yaml` started per feature PR, exposed through ngrok, health-checked, redeployed on push, removed on merge or close.

**Done when:** each check fails on a bad commit and passes on a clean one in a test product, and its preview shows the latest commit.

### Stage 4: Dispatcher and Linear integration
- Triggers: Linear webhook (or 30-second polling) for Ready for agent, mapping each Linear team or project to a product repo; and the `factory:ready` PR label for document-mode features. GitHub events for reviews, comments, close and labels.
- Phase loop, fixes, converge, rework and replan with their limits; runner chosen from `factory.yaml`.
- New container and repo-scoped GitHub App token per run; turn limit and wall-clock timeout.
- Status: PR labels and comments always; Linear state changes and comments only when `source.yaml` says `linear`. OTel metrics.

**Done when:** a two-phase issue in a test product ends as one ready PR with correct Linear states and comments; a forced timeout lands in Agent failed; closing the PR lands in Needs replan.

### Stage 5: Pilot products
- Pilot products and their specifics (stack, constitution, preview stack) are defined later, outside this repo.

**Done when:** a pilot feature reaches `main` through one Claude Code session and one PR, with no human step after handover other than review and merge.

## Schedule (today, Europe/Dublin)

| Time | Work |
|------|------|
| 12:45 – 14:45 | Stage 1 |
| 14:45 – 17:15 | Stage 2 |
| 17:15 – 19:15 | Stage 3 |
| 19:15 onward | Stages 4 and 5 |

Stages 1 and 2 need no prerequisites. Stages 3 to 5 start as P1 to P7 are ready. Times are estimates.
