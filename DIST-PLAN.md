# Factory Distribution Plan (GitHub-based)

## Three distribution channels

| Artefact | Where it lives | How products consume it |
|---|---|---|
| **Python package** `software-factory` | GitHub repo, tagged releases | `uv tool install git+https://github.com/OWNER/software-factory@v1.2.3` |
| **Docker images** `runner-base/python/node/reviewer` | GitHub Container Registry (`ghcr.io`) | Dispatcher pulls by tag; products declare `runner: python` in `factory.yaml` |
| **GitHub Actions reusable workflow** `.github/workflows/product.yml` | This repo, referenced by tag | Products call `uses: OWNER/software-factory/.github/workflows/product.yml@v1` |

No external registry. Everything flows through GitHub.

---

## Setting up a new product

```bash
# 1. Install the factory CLI from GitHub
uv tool install git+https://github.com/OWNER/software-factory@v1.2.3

# Or editable install from a local clone while developing the factory itself
uv tool install --editable /path/to/software-factory

# 2. Inside an empty (or existing) product repo
factory init --name my-product --factory-repo OWNER/software-factory

# factory init does all of this:
#   - runs specify init (Spec Kit)
#   - writes .factory/factory.yaml  (contract starter)
#   - writes .specify/memory/constitution.md  (base + product placeholder)
#   - writes .claude/skills/factory-{start,handoff,replan}/SKILL.md
#   - writes CLAUDE.md, .mcp.json, .factory/linear-issue-template.md
#   - writes .github/workflows/factory.yml  (3-line caller of the reusable workflow)

# 3. Fill in the product-specific bits
#   - Set runner, verify, setup in .factory/factory.yaml
#   - Run /speckit-constitution to add product principles
#   - factory validate
```

---

## Releasing a factory update

```bash
# 1. Bump version in pyproject.toml, commit and push
# 2. Tag the release — this is the ref products and the CLI install use
git tag v1.2.3
git push origin v1.2.3

# 3. Build & push Docker images to ghcr.io
make images   # builds runner-base, python, node, reviewer tagged with the version
make push     # IMAGE_PREFIX=ghcr.io/OWNER/software-factory/runner

# 4. GitHub Actions CI runs automatically on the tag push
```

Products pinning `@v1` in their workflow caller get CI pipeline updates automatically.
Products pinning `@v1.2.3` stay frozen until they explicitly update the ref.

---

## Update lifecycle for existing products

| What changed | Action in product repo |
|---|---|
| Skills (factory-start, handoff, replan) | Re-run `factory init` — always overwrites skills |
| Constitution base template | Re-run `factory init` — only updates if `[PROJECT_NAME]` placeholder still present |
| Runner images / CI pipeline | Automatic — dispatcher pulls by tag; workflow uses git ref |
| `factory.yaml` schema (breaking) | Manual: bump `version:` in product's `.factory/factory.yaml` per migration guide |
| Developer CLI (`factory validate`, etc.) | `uv tool install --reinstall git+https://github.com/OWNER/software-factory@v1.2.3` |

---

## Key files

- `pyproject.toml` — single source of version; CLI entry points (`factory`, `factory-runner`, `factory-egress`)
- `src/factory/__init__.py` — pinned tool versions (Claude Code, Spec Kit, scanners); Makefile reads these at build time
- `src/factory/kit/` — everything `factory init` installs into products
- `src/factory/kit/factory-ci.yml` — the 3-line CI workflow caller written to `.github/workflows/factory.yml` in products
- `.github/workflows/product.yml` — the reusable workflow products call
- `Makefile` targets: `images`, `push` (set `IMAGE_PREFIX=ghcr.io/OWNER/software-factory/runner`)
