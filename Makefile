CONTAINER_TAG ?= backlogger-test
CONTAINER_FILE ?= container/Containerfile
CONTAINER_CONTEXT ?= container/

.PHONY: help
help: ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: all
all: help

.PHONY: test
test: check-ruff ## Run ruff checks, then unit tests with pytest
	python3 -m pytest

.PHONY: check-ruff
check-ruff: ## Run ruff lint and format checks
	ruff check
	ruff format --check

.PHONY: tidy
tidy: ## Format code and autofix lint issues
	ruff format
	ruff check --fix

.PHONY: container-build
container-build: ## Build the container image from container/Containerfile
	podman build -t $(CONTAINER_TAG) -f $(CONTAINER_FILE) $(CONTAINER_CONTEXT)

.PHONY: container-run
container-run: ## Run entrypoint.py in the container against the repo workspace
	podman run --rm --workdir /github/workspace -v $(CURDIR):/github/workspace $(CONTAINER_TAG) /github/workspace/entrypoint.py || true
	@test -s gh-pages/index.html -a -s gh-pages/preview.png && echo "OK: rendered index.html + preview.png" || { echo "FAIL: no rendered output"; exit 1; }

.PHONY: container-test
container-test: container-build container-run ## Build the image, then run entrypoint.py locally
