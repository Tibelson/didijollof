.PHONY: help setup db-up db-down db-reset migrate migrate-check dev test logs logs-errors deploy clean

help:
	@echo "Didi Jollof"
	@echo "  make setup     install the Python environment"
	@echo "  make db-up     start local Postgres (Docker)"
	@echo "  make db-reset  drop, recreate and re-seed the local database"
	@echo "  make dev       run the API + PWA on http://localhost:8787"
	@echo "  make test      run the backend test suite"
	@echo "  make migrate   apply pending migrations to \$$DATABASE_URL"
	@echo "  make logs      stream live Worker logs"
	@echo "  make deploy    push the Worker to Cloudflare"
	@echo ""
	@echo "  Something broken? See DEBUGGING.md"

PG = PGPASSWORD=didi psql -h localhost -p 55432 -U didi -d didi -v ON_ERROR_STOP=1 -q
LOCAL_DB = postgresql://didi:didi@localhost:55432/didi

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
	@DATABASE_URL=$(LOCAL_DB) ./.venv/bin/python scripts/migrate.py
	@echo "database reset and seeded"

# Applies to whatever DATABASE_URL points at; defaults to the local container.
migrate:
	@DATABASE_URL=$${DATABASE_URL:-$(LOCAL_DB)} ./.venv/bin/python scripts/migrate.py

migrate-check:
	@DATABASE_URL=$${DATABASE_URL:-$(LOCAL_DB)} ./.venv/bin/python scripts/migrate.py --check

# Live Worker logs. Streams from now — it cannot show you the past; use the
# Cloudflare dashboard for history.
logs:
	cd api && npx --yes wrangler tail --format pretty

logs-errors:
	cd api && npx --yes wrangler tail --format pretty --status error

dev: db-up
	./.venv/bin/python scripts/dev.py

test: db-up
	cd api && ../.venv/bin/python -m pytest -q -W ignore::DeprecationWarning

deploy:
	cd api && uvx --from workers-py pywrangler deploy

clean:
	rm -rf .venv api/**/__pycache__ api/.pytest_cache
