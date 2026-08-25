.DEFAULT_GOAL := help
UV ?= uv
RUN := $(UV) run

.PHONY: help
help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: sync
sync:  ## Install the locked environment
	$(UV) sync --frozen --extra dev

.PHONY: lock
lock:  ## Re-resolve and write uv.lock
	$(UV) lock

.PHONY: lint
lint:  ## Ruff lint + format check
	$(RUN) ruff check src tests scripts
	$(RUN) ruff format --check src tests scripts

.PHONY: fmt
fmt:  ## Apply Ruff formatting and autofixes
	$(RUN) ruff check --fix src tests scripts
	$(RUN) ruff format src tests scripts

.PHONY: typecheck
typecheck:  ## Static type check
	$(RUN) mypy

.PHONY: test
test:  ## Run the test suite (network tests excluded)
	$(RUN) pytest -m "not network"

.PHONY: test-cov
test-cov:  ## Test suite with coverage
	$(RUN) pytest -m "not network" --cov=pramaanx --cov-report=term-missing

.PHONY: check
check: lint typecheck test  ## Everything CI runs

.PHONY: demo
demo:  ## End-to-end M0 demo on the synthetic world (no network, no credentials)
	$(RUN) python scripts/bootstrap_data.py --world demo
	$(RUN) pramaanx snapshot build --cutoff 2026-01-15T00:00:00Z
	$(RUN) pramaanx backtest --experiment configs/experiments/e2e_v1.yaml

.PHONY: clean
clean:  ## Remove caches and run outputs (bronze/silver/gold are kept)
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf runs/
