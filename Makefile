.PHONY: setup compile-deps lint format typecheck test docker-up docker-down

# ──────────────────────────────────────────────
# Development environment setup
# ──────────────────────────────────────────────

## Install all packages in editable mode, dev tools, and pre-commit hooks.
## Use this when setting up without conda, or after conda env create.
setup:
	pip install pip-tools pre-commit
	pip install -e services/shared
	pip install -e "services/api[dev]"
	pip install -e "services/collector[dev]"
	pip install -e "services/frontend[dev]"
	pre-commit install

# ──────────────────────────────────────────────
# Dependency management (pip-tools)
# ──────────────────────────────────────────────

## Compile pinned requirements.txt from pyproject.toml for all packages.
## Commit the generated files -- Docker builds use them.
compile-deps:
	pip-compile --output-file=services/shared/requirements.txt services/shared/pyproject.toml
	pip-compile --output-file=services/api/requirements.txt services/api/pyproject.toml
	pip-compile --extra dev --output-file=services/api/requirements-dev.txt services/api/pyproject.toml
	pip-compile --output-file=services/collector/requirements.txt services/collector/pyproject.toml
	pip-compile --extra dev --output-file=services/collector/requirements-dev.txt services/collector/pyproject.toml
	pip-compile --output-file=services/frontend/requirements.txt services/frontend/pyproject.toml
	pip-compile --extra dev --output-file=services/frontend/requirements-dev.txt services/frontend/pyproject.toml

## Upgrade all pinned dependencies to their latest allowed versions.
upgrade-deps:
	pip-compile --upgrade --output-file=services/shared/requirements.txt services/shared/pyproject.toml
	pip-compile --upgrade --output-file=services/api/requirements.txt services/api/pyproject.toml
	pip-compile --upgrade --extra dev --output-file=services/api/requirements-dev.txt services/api/pyproject.toml
	pip-compile --upgrade --output-file=services/collector/requirements.txt services/collector/pyproject.toml
	pip-compile --upgrade --extra dev --output-file=services/collector/requirements-dev.txt services/collector/pyproject.toml
	pip-compile --upgrade --output-file=services/frontend/requirements.txt services/frontend/pyproject.toml
	pip-compile --upgrade --extra dev --output-file=services/frontend/requirements-dev.txt services/frontend/pyproject.toml

# ──────────────────────────────────────────────
# Code quality
# ──────────────────────────────────────────────

## Run ruff linter and format checker (no changes).
lint:
	ruff check .
	ruff format --check .

## Auto-fix lint issues and reformat.
format:
	ruff check --fix .
	ruff format .

## Run mypy type checking across all packages.
typecheck:
	mypy services/shared/src services/api/src services/collector/src services/frontend/src

# ──────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────

## Run all tests.
test:
	pytest

## Run tests with coverage report.
test-cov:
	pytest --cov=services --cov-report=html

# ──────────────────────────────────────────────
# Docker
# ──────────────────────────────────────────────

## Build and start all services.
docker-up:
	docker-compose up --build -d

## Stop all services.
docker-down:
	docker-compose down
