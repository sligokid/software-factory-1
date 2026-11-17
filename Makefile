.DEFAULT_GOAL := help
IMAGE_PREFIX ?= software-factory/runner
PY = uv run python -c
VERSION = $(shell $(PY) 'import factory; print(factory.__version__)')
PIN = $(shell $(PY) 'import factory; print(factory.$(1))')

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

RUNNERS = base python node reviewer

images: ## Build runner images: runner-base, runner-python, runner-node, runner-reviewer
	docker build -f runner/base/Dockerfile -t $(IMAGE_PREFIX)-base:$(VERSION) \
	  $(foreach p,CLAUDE_CODE_VERSION SPECKIT_VERSION GITLEAKS_VERSION OSV_SCANNER_VERSION SEMGREP_VERSION,--build-arg $(p)=$(call PIN,$(p))) .
	for r in python node reviewer; do \
	  docker build -t $(IMAGE_PREFIX)-$$r:$(VERSION) --build-arg BASE=$(IMAGE_PREFIX)-base:$(VERSION) \
	    --build-arg PLAYWRIGHT_VERSION=$(call PIN,PLAYWRIGHT_VERSION) runner/$$r || exit 1; \
	done

push: ## Push runner images (set IMAGE_PREFIX, e.g. ghcr.io/<owner>/software-factory/runner)
	for r in $(RUNNERS); do docker push $(IMAGE_PREFIX)-$$r:$(VERSION) || exit 1; done

docker-test: ## Tests against the built images: sandbox, CI scanners, preview
	FACTORY_DOCKER_TESTS=1 uv run pytest -m docker

.PHONY: help install lint format typecheck test all images push docker-test
