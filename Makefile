.PHONY: setup lock lock-check validate-uv uv-contract agent-contract lint format typecheck precommit \
	test test-shared test-api test-collector test-frontend test-explorer test-cov \
	compile-deps upgrade-deps docker-lock-check compose-config check docker-up docker-down

# uv 0.12.3 is pinned by pyproject.toml. Keep command lines explicit so local
# aliases and CI consume the same lock and fail on metadata drift.

setup:
	uv sync --locked --all-packages --all-extras --all-groups
	uv run --locked pre-commit install

lock:
	uv lock

lock-check:
	uv lock --check

validate-uv:
	uv run --locked python scripts/validate_uv_workflow.py

uv-contract:
	uv run --locked python -m unittest discover -s tests/contracts -p "test_*.py"

# Compatibility entry point for the canonical agent contract.
agent-contract: uv-contract

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .

typecheck:
	uv run --locked mypy services/shared/src services/api/src services/collector/src services/frontend/src services/explorer/src

precommit:
	uv run --locked pre-commit run --all-files

test-shared:
	uv run --locked pytest services/shared/tests/

test-api:
	uv run --locked pytest services/api/tests/

test-collector:
	uv run --locked pytest services/collector/tests/

test-frontend:
	uv run --locked pytest services/frontend/tests/

test-explorer:
	uv run --locked pytest services/explorer/tests/

test: test-shared test-api test-collector test-frontend test-explorer

test-cov:
	uv run --locked pytest --cov=services --cov-report=html

# Temporary SPM-4 boundary: Docker still consumes the committed pip-tools
# requirements. These commands run pip-tools from uv.lock; they do not switch
# Docker to uv.lock or widen a build context.
compile-deps:
	uv run --locked python scripts/compile_docker_requirements.py

upgrade-deps:
	uv run --locked python scripts/compile_docker_requirements.py --upgrade

docker-lock-check:
	uv run --locked python scripts/compile_docker_requirements.py --check

compose-config:
	uv run --locked python scripts/validate_compose.py

check: lock-check validate-uv uv-contract lint typecheck precommit test docker-lock-check compose-config

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down
