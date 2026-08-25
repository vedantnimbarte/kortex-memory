.PHONY: help install dev up down logs migrate seed lint type test test-unit test-integration clean \n	local-build local-run local-stop minimal-up minimal-down

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
	@echo ""
	@echo "  local-build       - build the all-in-one evaluation image"
	@echo "  local-run         - run it (API :8000, MCP :8765)"
	@echo "  local-stop        - stop and remove it"
	@echo "  minimal-up        - 3-container stack (postgres + redis + app)"
	@echo "  minimal-down      - stop the 3-container stack"

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

local-build:
	docker build -f docker/local.Dockerfile -t kortex/kortex:local .

local-run:
	docker run -d --name kortex-local 		-p 8000:8000 -p 8765:8765 		-v kortex-data:/data 		kortex/kortex:local
	@echo "API http://localhost:8000  MCP http://localhost:8765/sse"
	@echo "First run downloads the embedding model; watch: docker logs -f kortex-local"

local-stop:
	-docker rm -f kortex-local

minimal-up:
	docker compose -f docker/compose.minimal.yaml up -d --build

minimal-down:
	docker compose -f docker/compose.minimal.yaml down

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
