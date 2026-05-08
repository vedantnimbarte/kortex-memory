.PHONY: help install dev up down logs migrate seed lint type test test-unit test-integration clean

help:
	@echo "Targets:"
	@echo "  install           - uv sync workspace"
	@echo "  dev               - start docker compose stack"
	@echo "  down              - stop docker compose stack"
	@echo "  logs              - tail compose logs"
	@echo "  migrate           - run alembic upgrade head"
	@echo "  seed              - seed dev org/workspace/project/api-key"
	@echo "  lint              - ruff check + format"
	@echo "  type              - mypy"
	@echo "  test              - pytest (all)"
	@echo "  test-unit         - pytest unit only"
	@echo "  test-integration  - pytest integration only"

install:
	uv sync --all-packages

dev:
	docker compose -f docker/compose.yaml up -d

down:
	docker compose -f docker/compose.yaml down

logs:
	docker compose -f docker/compose.yaml logs -f --tail=200

migrate:
	uv run alembic upgrade head

seed:
	uv run python scripts/seed_dev.py

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run mypy packages

test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-integration:
	uv run pytest -m integration

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
	find . -type d -name __pycache__ -exec rm -rf {} +
