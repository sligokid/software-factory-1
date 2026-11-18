# CLAUDE.md

This repository is the **AI software factory** itself: product-agnostic tooling that builds other
products. It must never contain product-specific code, stacks or rules. See `PLAN.md`.

## Layout
- `src/factory/contract.py`, `factory.schema.json`: the product contract (`.factory/factory.yaml`).
- `src/factory/checks/`: generic checks driven by the contract (file size, commit size, protected paths).
- `src/factory/init.py`, `src/factory/kit/`: `factory init` and the developer kit it installs
  into products (factory-* skills, constitution base, CLAUDE.md, contract starter, Linear MCP).
- `src/factory/tasks.py`: parses `tasks.md` phases.
- `src/factory/runner/`: sandboxed runs. `entrypoint.py` (in the container), `proxy.py` (egress
  allowlist), `tools.py` (agent tool allowlist), `sandbox.py` (docker flags), `host.py`
  (`factory agent`, `factory replay`). Images: `runner/{base,python,node}/Dockerfile`.
- `src/factory/ci.py`, `review.py`, `screenshots.py`, `preview.py`: `factory ci`, the read-only
  reviewer, Playwright screenshots and per-feature previews. `.github/workflows/product.yml` is
  the reusable workflow products call (kit: `factory-ci.yml`); `images.yml` publishes images.
- `src/factory/dispatch.py`: `factory next`, the dispatcher's decision after each workflow run
  (state in the PR body, labels, comments). The loop itself is the `agent` and `next` jobs in
  `product.yml`; each run does one step and dispatches the next with `workflow_dispatch`.
- `src/factory/cli.py`: the `factory` command (`init`, `validate`, `check`, `agent`, `replay`,
  `ci`, `review`, `screenshots`, `preview`, `next`).

## Commands
- `make all`: ruff, mypy (strict), pytest. Must pass before every commit.
- `make images`, `make docker-test`: build the runner images and test the sandbox in Docker.
- `uv run factory --help`: the CLI.

## Rules
- Anything a product decides (language, framework, commands, preview, limits) comes from the
  product's `factory.yaml`, never from code here.
- Kit files are copied into products: keep them generic and short.
- Pin tools in one place: the versions in `src/factory/__init__.py`. Bump the package version
  together with `FACTORY_VERSION` in `.github/workflows/product.yml` (a test checks they match).
