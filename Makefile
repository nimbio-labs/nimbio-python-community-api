# Developer shortcuts. Run `make help` to list targets.
# These assume an activated virtualenv (python -m venv .venv && source .venv/bin/activate).

.DEFAULT_GOAL := help
.PHONY: help install test cov lint format typecheck check build clean tox

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package with dev dependencies (editable)
	pip install -e '.[dev]'

test:  ## Run the test suite
	pytest -q

cov:  ## Run tests with a coverage report
	pytest -q --cov=nimbio_community_api --cov-report=term-missing

lint:  ## Lint with ruff
	ruff check .

format:  ## Auto-fix lint issues with ruff
	ruff check --fix .

typecheck:  ## Type-check with mypy
	mypy

check: lint typecheck cov  ## Run lint + types + coverage (what CI runs)

build:  ## Build the sdist and wheel into dist/
	python -m build

tox:  ## Run the test matrix across all installed Python versions
	tox

clean:  ## Remove build artifacts and caches
	rm -rf dist build *.egg-info src/*.egg-info .pytest_cache .ruff_cache \
		.mypy_cache .tox .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
