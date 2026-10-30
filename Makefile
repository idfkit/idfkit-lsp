.DEFAULT_GOAL := help

SERVER_DIR := server
MODEL_SERVER_DIR := model-server
CLIENT_DIR := client
VSIX ?= idfkit-lsp.vsix

# ── Environment ──────────────────────────────────────────────────────────

.PHONY: install
install: ## Install both runtimes, the client and the packaging tools, at their locked levels
	cd $(SERVER_DIR) && uv sync --locked --extra dev
	npm ci
	cd $(CLIENT_DIR) && npm ci
	cd $(MODEL_SERVER_DIR) && npm ci

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
test-protocol: export REQUIRE_FULL_SUITE := 1
test-protocol: build-model ## Drive both servers over the protocol, with no editor, skipping neither
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest ../tests/protocol -rs $(ARGS)

.PHONY: bench-protocol
bench-protocol: export REQUIRE_FULL_SUITE := 1
bench-protocol: build-model ## Measure an answer at a cursor at the protocol boundary
	cd $(SERVER_DIR) && uv run --frozen --extra dev pytest ../tests/protocol/test_budget.py -v -s $(ARGS)

# ── Combined ─────────────────────────────────────────────────────────────

.PHONY: check
check: lint format typecheck check-declaration check-levels check-knowledge test test-tools test-model test-protocol ## The one command a change is held to

.PHONY: fix
fix: lint-fix format-fix ## Auto-fix lint and format issues

# ── Build ────────────────────────────────────────────────────────────────

.PHONY: build
build: build-model ## Bundle the client and the model server
	npm run compile

# A target of its own because the gate needs it: the bump workflows run `make check` and install only
# the model server's npm dependencies, so the gate cannot build the client.
.PHONY: build-model
build-model: ## Bundle the model server
	cd $(MODEL_SERVER_DIR) && npm run build

.PHONY: package
package: ## Package the VS Code extension (VSIX=<path> names the output, default idfkit-lsp.vsix)
	npx --no-install vsce package --out "$(VSIX)"

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
