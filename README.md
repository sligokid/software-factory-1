# AI Software Factory

Product-agnostic delivery pipeline. A developer writes a spec and task list with Claude Code and
GitHub Spec Kit inside a product repo, hands it over, and the factory implements each phase in a
sandboxed headless Claude Code run, delivering one PR per feature with a live preview.

The factory works with any product (frontend or backend, any language) that has a
`.factory/factory.yaml` contract. See `PLAN.md` for the full design.

## Install

```bash
uv tool install specify-cli==1.4.1     # Spec Kit (pinned)
uv tool install --editable .           # the `factory` command
```

## Make a repository a factory product

```bash
cd ~/git/my-product
factory init                 # Spec Kit + factory skills + constitution base + contract starter
# edit .factory/factory.yaml (runner, setup/verify commands, preview, egress)
# fill in the product principles with /speckit-constitution in Claude Code
factory validate
```

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

## Runner and sandbox

`make images` builds `software-factory/runner-{base,python,node}:<version>` (`runner/`). Each run:

- gets an internal Docker network whose only way out is an egress proxy allowing HTTPS to the
  Anthropic API, GitHub and the product's `egress` hosts (`.example.com` allows subdomains);
- runs as uid 10001 with no capabilities, `no-new-privileges`, a read-only root, CPU, memory and
  process limits, no Docker socket and no host mounts (the branch goes in as a git bundle on
  stdin and the result comes back as a bundle on stdout);
- refuses `ANTHROPIC_API_KEY` and requires `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`);
- runs the contract's `setup`, then headless Claude Code limited to git, Spec Kit scripts and the
  contract's commands, then `verify`, `checks` and the factory checks, and squashes the work into
  one commit.

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
