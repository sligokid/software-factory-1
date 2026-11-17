.DEFAULT_GOAL := help
SLICE ?=

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff formatting and fixes
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Mypy (strict)
	uv run mypy

test: ## Run tests
	uv run pytest

check: ## Factory rules: file size limits
	uv run python -m factory.checks.sizes

all: lint typecheck test check ## Everything CI runs locally

new-slice: ## Create a slice from the template: make new-slice SLICE=name
	@test -n "$(SLICE)" || (echo "usage: make new-slice SLICE=name" && exit 1)
	uv run python -m factory.new_slice $(SLICE)

run: ## Run the API locally
	uv run uvicorn app.main:app --reload --app-dir src

.PHONY: help install lint format typecheck test check all new-slice run
