.PHONY: help setup db-up db-down db-reset dev test shots deploy clean

help:
	@echo "Didi Jollof"
	@echo "  make setup     install the Python environment"
	@echo "  make db-up     start local Postgres (Docker)"
	@echo "  make db-reset  drop, recreate and re-seed the local database"
	@echo "  make dev       run the API + PWA on http://localhost:8787"
	@echo "  make test      run the backend test suite"
	@echo "  make deploy    push the Worker to Cloudflare"

PG = PGPASSWORD=didi psql -h localhost -p 55432 -U didi -d didi -v ON_ERROR_STOP=1 -q

setup:
	python3 -m venv .venv
	./.venv/bin/pip install -q --upgrade pip
	./.venv/bin/pip install -q fastapi 'pydantic[email]' asyncpg pytest pytest-asyncio httpx uvicorn

db-up:
	docker compose up -d
	@until docker compose exec -T db pg_isready -U didi -d didi >/dev/null 2>&1; do sleep 1; done
	@echo "postgres ready on localhost:55432"

db-down:
	docker compose down

db-reset: db-up
	@$(PG) -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	@$(PG) -f migrations/0001_init.sql
	@$(PG) -f migrations/0002_seed.sql
	@echo "database reset and seeded"

dev: db-up
	./.venv/bin/python scripts/dev.py

test: db-up
	cd api && ../.venv/bin/python -m pytest -q -W ignore::DeprecationWarning

deploy:
	cd api && uvx --from workers-py pywrangler deploy

clean:
	rm -rf .venv api/**/__pycache__ api/.pytest_cache
