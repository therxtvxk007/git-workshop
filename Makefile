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

COVERAGE_FLOOR ?= 88

.PHONY: test
test:  ## Run the test suite (network tests excluded)
	$(RUN) pytest -m "not network"

.PHONY: test-cov
test-cov:  ## Test suite with an enforced coverage floor
	$(RUN) pytest -m "not network" --cov=pramaanx --cov-report=term-missing \
		--cov-fail-under=$(COVERAGE_FLOOR)

.PHONY: check
check: lint typecheck test-cov  ## Everything CI runs

# The ingestion window must reach past the final cutoff plus the forecast
# horizon plus the reporting delay, or the last folds are right-censored and the
# backtest refuses to score them. e2e_v1 ends 2026-03-04 with a 30-day horizon,
# so evidence has to run to at least 2026-04-06.
DEMO_FROM ?= 2025-01-01T00:00:00Z
DEMO_UNTIL ?= 2026-05-01T00:00:00Z
DEMO_CUTOFF ?= 2026-01-15T00:00:00Z
DEMO_EXPERIMENT ?= configs/experiments/e2e_v1.yaml

.PHONY: demo
demo:  ## End-to-end M0 demo on the synthetic world (no network, no credentials)
	$(RUN) python scripts/bootstrap_data.py --from $(DEMO_FROM) --until $(DEMO_UNTIL)
	$(RUN) pramaanx snapshot build --cutoff $(DEMO_CUTOFF)
	$(RUN) pramaanx audit leakage --cutoff $(DEMO_CUTOFF)
	$(RUN) pramaanx backtest --experiment $(DEMO_EXPERIMENT)

.PHONY: clean
clean:  ## Remove caches and run outputs (bronze/silver/gold are kept)
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf runs/
