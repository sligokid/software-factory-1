# AI Software Factory

Product-agnostic delivery pipeline. A developer writes a spec and task list with Claude Code and
GitHub Spec Kit inside a product repo, hands it over, and the factory implements each phase in a
sandboxed headless Claude Code run, delivering one PR per feature with a live preview.

Everything that executes product code runs in **Docker**: each agent run is a locked-down
container behind an egress-proxy container on a private Docker network, CI jobs run inside the
same runner images, and previews are the product's own Docker Compose stack. Docker (Engine or
Desktop, with Compose v2) is required on any machine that runs `factory agent`, `factory replay`
or `factory preview`. See [How the factory uses Docker](#how-the-factory-uses-docker).

The factory works with any product (frontend or backend, any language) that has a
`.factory/factory.yaml` contract. See `PLAN.md` for the full design.

## Use the factory in your own repo

```bash
mkdir my-product && cd my-product                        # or an existing repo
uv tool install specify-cli==1.4.1                       # Spec Kit (once per machine)
uv tool install --editable /path/to/software-factory     # the `factory` command (once per machine)
factory init                                             # Spec Kit, /factory-* skills, constitution, factory.yaml
claude                                                   # then /factory-setup (fills in and validates .factory/factory.yaml)
```

Fill in the product principles with `/speckit-constitution`. To run agents locally, also run
`make images` in the factory repo and `export CLAUDE_CODE_OAUTH_TOKEN=...` (from `claude setup-token`).

## Commands

| Command | What it does |
|---------|--------------|
| `factory init [path]` | Installs Spec Kit, the `/factory-*` skills, the constitution base, `CLAUDE.md`, the Linear MCP config and a starter `.factory/factory.yaml`. Safe to re-run: kit skills are updated, product files are kept. |
| `factory validate` | Validates `.factory/factory.yaml` against the schema and warns about unfilled placeholders. |
| `factory check [--base REF] [--agent]` | File size limits; with `--base`, commit size; with `--agent`, protected paths. |
| `factory agent <mode> [--phase N]` | One sandboxed agent run on the current `feature/<ID>` branch of a local product checkout (modes: `implement`, `fix`, `converge`, `rework`). Lands one commit on the branch and saves the run under `~/.factory/runs/<run id>`. |
| `factory ci <step...> [--base REF]` | CI steps: `setup`, `verify`, `checks` (the contract's commands), `factory` (sizes, per-commit size, protected paths on agent commits), `secrets` (gitleaks), `sast` (semgrep), `deps` (osv-scanner), or `all`. The scanners are in the runner images. |
| `factory review --base REF [--screenshots DIR]` | Read-only Claude reviewer against the constitution and the feature spec. Blocking findings fail it; `--markdown` writes the PR comment. |
| `factory screenshots URL --out DIR [--commit SHA]` | Playwright desktop and mobile screenshots of `preview.screenshots` paths, after the preview serves the commit. |
| `factory preview up\|down\|status\|url` | Per-feature preview from the product's compose file, on the factory host. |
| `factory replay <run folder>` | Re-runs a recorded run from the same commit, mode, phase, feedback and image; the result is kept under `refs/factory/runs/` and the branch is not moved. |
| `factory next --step S ...` | The dispatcher, in CI: reads the run's agent result, checks and review, `tasks.md` and the PR's counters, records the outcome on the PR (labels, comment, phase table) and prints the next step to dispatch. |

## How the factory uses Docker

The `factory` CLI itself is plain Python on the host. It never runs product code or Claude Code
directly; it drives the `docker` CLI. Docker is used in four places.

### 1. Runner images (`runner/`, `make images`)

| Image | Built from | Adds |
|-------|------------|------|
| `runner-base` | `debian:bookworm-slim` | git, gh, uv, Spec Kit, Claude Code (pinned native build), the factory CLI (`factory-runner` entrypoint, `factory-egress` proxy, `factory ci`), gitleaks, semgrep, osv-scanner, and a non-root `agent` user (uid 10001) |
| `runner-python` | `runner-base` | CPython 3.11-3.13 via uv, downloads disabled at run time |
| `runner-node` | `runner-base` | Node.js LTS, pnpm and yarn via corepack |
| `runner-reviewer` | `runner-base` | Playwright and Chromium for `factory screenshots` |

All tool versions come from `src/factory/__init__.py`. Locally `make images` tags them
`software-factory/runner-*:<version>`; the `images` workflow publishes them to
`ghcr.io/<owner>/<repo>/runner-*`. A product picks its image with `runner:` in `factory.yaml`.

### 2. The agent sandbox (`factory agent`, `factory replay`)

`src/factory/runner/sandbox.py` builds the docker command lines and `host.py` runs them. Each run
creates three Docker objects named `factory-<run id>`, all removed when the run ends:

1. **An internal network** (`docker network create --internal`): containers on it have no route
   to the internet or the host.
2. **An egress proxy container** (`factory-egress`, same image, 0.5 CPU / 256 MB): started on the
   default bridge so it can reach out, then also attached to the internal network under the alias
   `egress`. It only accepts HTTPS `CONNECT` to port 443 of allowlisted hosts (the Anthropic API,
   GitHub and the product's `egress` list) and logs every allow and deny to `egress.log`.
3. **The agent container** (`docker run -i --rm`), on the internal network only, with
   `HTTPS_PROXY=http://egress:3128`, and hardened with:
   - `--user 10001:10001`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--init`;
   - `--read-only` root filesystem; writable space is only a 1 GB `/tmp` tmpfs and two anonymous
     volumes (`/workspace`, `/home/agent`) that are deleted with the container;
   - `--cpus 2 --memory 4g --memory-swap 4g --pids-limit 512` by default, plus a wall-clock
     timeout (`docker kill` after one hour by default);
   - no Docker socket and no bind mounts, so it cannot see the host filesystem or start containers;
   - `CLAUDE_CODE_OAUTH_TOKEN` passed by name (`-e NAME`), never on the command line;
     `ANTHROPIC_API_KEY` is refused.

Code moves in and out through pipes, not mounts: the host writes the branch as a `git bundle` to
the container's stdin, and the container prints the result commit as a bundle in its final
`factory_result` line on stdout. The host fetches that into `refs/factory/runs/<run id>` and,
if the branch is unchanged, fast-forwards it. Inside the container the entrypoint runs the
contract's `setup`, headless Claude Code limited to git, Spec Kit scripts and the contract's
commands, then `verify`, `checks` and the factory checks, and squashes the work into one commit.

Everything is recorded under `~/.factory/runs/<run id>/` (`run.json` with the exact image,
`input.bundle`, `transcript.jsonl`, `runner.log`, `egress.log`, `result.bundle`), which is what
`factory replay` uses to re-run with the same image and inputs.

### 3. CI (`.github/workflows/product.yml`)

The `checks` job runs inside the product's runner image as a GitHub Actions `container:`, so CI
uses the same toolchain and scanners as the agent. The `review` job runs in `runner-reviewer`.

### 4. Previews (`factory preview`)

On the factory host (never inside the sandbox), `factory preview up` exports the commit and runs
the product's own compose file with `docker compose -p factory-preview-<id>`, adds an ngrok
tunnel service at `https://<id>.<domain>`, and health-checks the service with a throwaway
`docker run ... curl` on the stack's network. `down` runs `docker compose down -v --remove-orphans`.

### Requirements

- Docker Engine or Docker Desktop with Compose v2, and a user that can run `docker`.
- `make images` (or access to the published ghcr.io images) before the first `factory agent`.
- `make docker-test` runs the Docker-backed tests (sandbox, scanners, preview); plain `make test`
  skips them unless `FACTORY_DOCKER_TESTS=1`.

## Running an agent locally

Needs Docker and the runner images (see above).

```bash
export CLAUDE_CODE_OAUTH_TOKEN=...      # never ANTHROPIC_API_KEY
cd ~/git/my-product && git switch feature/ENG-123
factory agent implement                 # next open phase of tasks.md
factory agent fix --feedback-file ci.txt
factory replay ~/.factory/runs/<run id>
```

## CI, reviewer and preview

`factory init --factory-repo <owner>/software-factory` installs `.github/workflows/factory.yml`,
which calls this repo's reusable workflow (`.github/workflows/product.yml@v1`):

| Event | Jobs |
|-------|------|
| push to `main` or `feature/**` | `checks` in the product's runner image: every `factory ci` step on the pushed commits |
| push to `feature/**` | `review` of the pushed commits, posted on the PR; `preview` redeploy |
| PR ready for review | `review` of the whole PR (with screenshots when `preview.ui`) |
| PR closed or merged | `preview` removed |

### The agent loop (dispatcher)

After `/factory-handoff` adds the `factory:ready` label, the factory implements the feature on
GitHub-hosted runners with no manual step. Each workflow run does one step:

```text
agent   factory agent <mode> in the sandbox (Docker on ubuntu-latest), push with GITHUB_TOKEN
checks  as above, on the agent's commit
review  as above, on the agent's commit
next    factory next: record the result on the PR, then dispatch the next run
          phase passed      -> implement the next open phase, or converge when none is left
          CI/review failed  -> fix (limits.fixes, default 2), then factory:failed
          converge gaps     -> implement the new phase (limits.converge_rounds)
          converged         -> final: review of the whole PR -> PR ready, factory:awaiting-review
```

| Event | Step |
|-------|------|
| label `factory:ready` | implement the first open phase |
| review with changes requested, or a comment containing `@agent` (owners, members and collaborators only) | rework with the comments (`limits.rework_rounds`) |
| comment `@agent replan`, or PR closed without merging | `factory:needs-replan` |
| label `human-takeover` | the loop pauses at the next step; remove it and add `factory:ready` again to resume |

Status lives on the PR: the labels `factory:working`, `factory:awaiting-review`,
`factory:failed`, `factory:needs-replan`, one comment per run (result, turns, cost, time) and a
phase table plus counters in the PR body. Each run's folder is kept as the `factory-run`
artifact; download it and run `factory replay <folder> --product <checkout>` to reproduce a run.
The agent jobs install the factory CLI from the wheel in the runner image, so they always match
the image version.

Setup: tag a release `v1` (the `images` workflow publishes `ghcr.io/<owner>/<repo>/runner-*`
and the packages must be readable by product repos); secrets `CLAUDE_CODE_OAUTH_TOKEN`,
`FACTORY_PREVIEW_AUTH`, `NGROK_AUTHTOKEN`; variables `FACTORY_PREVIEW_DOMAIN`,
`FACTORY_PREVIEW_RUNNER` (a self-hosted runner on the factory host with Docker and `factory`
installed; previews are off without it) and optionally `FACTORY_PREVIEW_ALLOW_IPS`.

Previews run the product's `compose.preview.yaml` as project `factory-preview-<id>` with an
ngrok tunnel at `https://<id>.<FACTORY_PREVIEW_DOMAIN>` (a reserved wildcard domain). They are
never public: basic auth (`FACTORY_PREVIEW_AUTH`) or an IP allowlist is required, and every
response carries `x-factory-commit: <sha>`. The stack gets `FACTORY_COMMIT` and
`FACTORY_PREVIEW_URL` in its environment. Without a domain, `factory preview up` deploys locally
only.

A run folder holds `run.json` (request, result, usage), `transcript.jsonl` (Claude's
stream-json), `runner.log` and `egress.log` (allowed and denied hosts).

## Developer flow (in a product repo)

```text
/factory-start ENG-123              # from a Linear issue
/factory-start docs/feature.md      # or from a document (no Linear at all)
  -> /speckit-clarify -> /speckit-plan -> /speckit-tasks -> /factory-handoff
```

## Development

```bash
make all          # ruff, mypy --strict, pytest
make images       # runner images
make docker-test  # against the images: sandbox, each CI check bad/clean, preview lifecycle
```
