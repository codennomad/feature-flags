.PHONY: dev test migrate seed lint format security-scan build docker-up docker-down

# ── Desenvolvimento ───────────────────────────────────────────────────────────
dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# ── Testes ────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-security:
	pytest tests/security/ -v

test-performance:
	pytest tests/performance/ -v

test-consistency:
	pytest tests/consistency/ -v

# ── Migrations ────────────────────────────────────────────────────────────────
migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migrate-new:
	alembic revision --autogenerate -m "$(name)"

# ── Seed ─────────────────────────────────────────────────────────────────────
seed:
	python -m src.scripts.seed

# ── Qualidade de código ───────────────────────────────────────────────────────
lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/

security-scan:
	bandit -r src/ -c pyproject.toml

# ── Docker ────────────────────────────────────────────────────────────────────
docker-up:
	docker compose up -d postgres redis prometheus

docker-down:
	docker compose down

docker-up-full:
	docker compose up -d

# ─── Build ────────────────────────────────────────────────────────────────────
build:
	docker build -t feature-flags:latest .

# ── Setup inicial ─────────────────────────────────────────────────────────────
install:
	pip install -e ".[test,dev]"

install-prod:
	pip install -e .
