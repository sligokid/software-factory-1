# CLAUDE.md

This repository is the **AI software factory** itself: product-agnostic tooling that builds other
products. It must never contain product-specific code, stacks or rules. See `PLAN.md`.

## Layout
- `src/factory/contract.py`, `factory.schema.json`: the product contract (`.factory/factory.yaml`).
- `src/factory/checks/`: generic checks driven by the contract (file size, commit size, protected paths).
- `src/factory/init.py`, `src/factory/kit/`: `factory init` and the developer kit it installs
  into products (factory-* skills, constitution base, CLAUDE.md, contract starter, Linear MCP).
- `src/factory/cli.py`: the `factory` command (`init`, `validate`, `check`).
- Later stages add the runner images, reusable CI workflows, reviewer and dispatcher.

## Commands
- `make all`: ruff, mypy (strict), pytest. Must pass before every commit.
- `uv run factory --help`: the CLI.

## Rules
- Anything a product decides (language, framework, commands, preview, limits) comes from the
  product's `factory.yaml`, never from code here.
- Kit files are copied into products: keep them generic and short.
- Pin Spec Kit in one place: `SPECKIT_VERSION` in `src/factory/__init__.py`.
