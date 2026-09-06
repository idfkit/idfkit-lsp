.DEFAULT_GOAL := help

SERVER_DIR := server
MODEL_SERVER_DIR := model-server

# ── Environment ──────────────────────────────────────────────────────────

.PHONY: install
install: ## Install both runtimes with their dev dependencies
	cd $(SERVER_DIR) && uv sync --extra dev
	cd $(MODEL_SERVER_DIR) && npm install

.PHONY: lock
lock: ## Regenerate the lockfile
	cd $(SERVER_DIR) && uv lock

# ── Quality ──────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Run ruff linter
	cd $(SERVER_DIR) && uv run --frozen --extra dev ruff check src tests ../tools ../tests

.PHONY: format
format: ## Run ruff formatter (check only)
	cd $(SERVER_DIR) && uv run --frozen --extra dev ruff format --check src tests ../tools ../tests

.PHONY: format-fix
format-fix: ## Auto-format code with ruff
	cd $(SERVER_DIR) && uv run --frozen --extra dev ruff format src tests ../tools ../tests

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues with ruff
	cd $(SERVER_DIR) && uv run --frozen --extra dev ruff check --fix src tests ../tools ../tests

.PHONY: typecheck
typecheck: ## Run pyright over the Python trees and tsc over the model server
	cd $(SERVER_DIR) && uv run --frozen --extra dev pyright src ../tools ../tests/protocol
	cd $(MODEL_SERVER_DIR) && npm run typecheck

# ── Declared records ─────────────────────────────────────────────────────

.PHONY: check-declaration
check-declaration: ## capabilities.json agrees with the manifest, the readme, and the servers
	uv run --frozen --extra dev --project $(SERVER_DIR) python -m tools.check_declaration

.PHONY: check-levels
check-levels: ## levels.json agrees with every file that declares a level
	uv run --frozen --extra dev --project $(SERVER_DIR) python -m tools.check_levels

.PHONY: check-knowledge
check-knowledge: ## no schema table, grammar pattern, or model-text offset arithmetic
	uv run --frozen --extra dev --project $(SERVER_DIR) python -m tools.check_knowledge

# ── Testing ──────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run the source server's unit tests
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest tests

.PHONY: test-v
test-v: ## Run the source server's unit tests, verbose
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest tests -v

.PHONY: test-tools
test-tools: ## Run the repository checks' own tests
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest ../tools/tests

.PHONY: test-model
test-model: ## Run the model server's unit tests
	cd $(MODEL_SERVER_DIR) && npm test

.PHONY: test-protocol
test-protocol: ## Drive both servers over the protocol, with no editor
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest ../tests/protocol $(ARGS)

.PHONY: bench-protocol
bench-protocol: ## Measure an answer at a cursor at the protocol boundary
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest ../tests/protocol/test_budget.py -v -s $(ARGS)

# ── Combined ─────────────────────────────────────────────────────────────

.PHONY: check
check: lint format typecheck check-declaration check-levels check-knowledge test test-tools test-model test-protocol ## The one command a change is held to

.PHONY: fix
fix: lint-fix format-fix ## Auto-fix lint and format issues

# ── Build ────────────────────────────────────────────────────────────────

.PHONY: build
build: ## Bundle the client and the model server
	npm run compile
	cd $(MODEL_SERVER_DIR) && npm run build

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
