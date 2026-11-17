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
make docker-test  # sandbox tests against the images (egress, API key refusal, hardening)
```
