.DEFAULT_GOAL := help
IMAGE_PREFIX ?= software-factory/runner
PY = uv run python -c
VERSION = $(shell $(PY) 'import factory; print(factory.__version__)')
CLAUDE_CODE_VERSION = $(shell $(PY) 'import factory; print(factory.CLAUDE_CODE_VERSION)')
SPECKIT_VERSION = $(shell $(PY) 'import factory; print(factory.SPECKIT_VERSION)')

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

test: ## Run tests (Docker sandbox tests are skipped unless FACTORY_DOCKER_TESTS=1)
	uv run pytest

all: lint typecheck test ## Everything CI runs locally

images: ## Build runner images: runner-base, runner-python, runner-node
	docker build -f runner/base/Dockerfile -t $(IMAGE_PREFIX)-base:$(VERSION) \
	  --build-arg CLAUDE_CODE_VERSION=$(CLAUDE_CODE_VERSION) \
	  --build-arg SPECKIT_VERSION=$(SPECKIT_VERSION) .
	docker build -t $(IMAGE_PREFIX)-python:$(VERSION) \
	  --build-arg BASE=$(IMAGE_PREFIX)-base:$(VERSION) runner/python
	docker build -t $(IMAGE_PREFIX)-node:$(VERSION) \
	  --build-arg BASE=$(IMAGE_PREFIX)-base:$(VERSION) runner/node

docker-test: ## Sandbox tests against the built images (egress, API key refusal, hardening)
	FACTORY_DOCKER_TESTS=1 uv run pytest tests/test_sandbox_docker.py

.PHONY: help install lint format typecheck test all images docker-test
