.DEFAULT_GOAL := help

SERVER_DIR := server

# ── Environment ──────────────────────────────────────────────────────────

.PHONY: install
install: ## Install the project with dev dependencies using uv
	cd $(SERVER_DIR) && uv sync --extra dev

.PHONY: lock
lock: ## Regenerate the lockfile
	cd $(SERVER_DIR) && uv lock

# ── Quality ──────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Run ruff linter
	cd $(SERVER_DIR) && uv run ruff check src tests

.PHONY: format
format: ## Run ruff formatter (check only)
	cd $(SERVER_DIR) && uv run ruff format --check src tests

.PHONY: format-fix
format-fix: ## Auto-format code with ruff
	cd $(SERVER_DIR) && uv run ruff format src tests

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues with ruff
	cd $(SERVER_DIR) && uv run ruff check --fix src tests

.PHONY: typecheck
typecheck: ## Run pyright type checker
	cd $(SERVER_DIR) && uv run pyright src

# ── Testing ──────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run tests with pytest
	cd $(SERVER_DIR) && uv run pytest

.PHONY: test-v
test-v: ## Run tests with verbose output
	cd $(SERVER_DIR) && uv run pytest -v

# ── Combined ─────────────────────────────────────────────────────────────

.PHONY: check
check: lint format typecheck test ## Run all checks (lint, format, typecheck, test)

.PHONY: fix
fix: lint-fix format-fix ## Auto-fix lint and format issues

# ── Pre-commit ───────────────────────────────────────────────────────────

.PHONY: pre-commit-install
pre-commit-install: ## Install pre-commit hooks
	cd $(SERVER_DIR) && uv run pre-commit install

.PHONY: pre-commit-run
pre-commit-run: ## Run pre-commit on all files
	cd $(SERVER_DIR) && uv run pre-commit run --all-files

# ── Help ─────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
