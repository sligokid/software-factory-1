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

## Developer flow (in a product repo)

```text
/factory-start ENG-123              # from a Linear issue
/factory-start docs/feature.md      # or from a document (no Linear at all)
  -> /speckit-clarify -> /speckit-plan -> /speckit-tasks -> /factory-handoff
```

## Development

```bash
make all    # ruff, mypy --strict, pytest
```
