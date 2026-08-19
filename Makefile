PY := .venv/Scripts/python.exe
ifeq ($(OS),)
PY := .venv/bin/python
endif
NPM := npm --prefix web

.PHONY: help dev test test-web test-e2e test-security test-all lint format typecheck check \
        bench bench-mechanisms optimality control-cost reproduce web-data api worker \
        migrate docker-build docker-up docker-down clean

help:
	@echo "dev            run the API and the dashboard locally (two processes)"
	@echo "test           Python unit + property + differential tests"
	@echo "test-web       vitest"
	@echo "test-e2e       Playwright browser tests, including the axe accessibility scan"
	@echo "test-security  authz, rate limit, injection and CSRF tests (needs PostgreSQL)"
	@echo "test-all       every suite above"
	@echo "lint           ruff, black --check, eslint, tsc"
	@echo "typecheck      mypy (strict on orbit/)"
	@echo "check          lint + typecheck + test"
	@echo "bench          the committed A8 experiment grid"
	@echo "bench-mechanisms  the A11 grid: does M1/M3/M4 ever matter"
	@echo "optimality     sweep the LP optimality gap (F22)"
	@echo "control-cost   uncontended control-plane cost against size (N4)"
	@echo "reproduce      regenerate every figure and table from raw results"
	@echo "docker-build   build both container images"
	@echo "docker-up      docker compose up (needs SESSION_SECRET)"

# Two long-running processes, so this backgrounds the API and leaves Vite in the foreground;
# Ctrl-C stops Vite and the trap takes the API with it.
dev:
	@$(PY) -m uvicorn api.main:app --reload & \
	trap 'kill $$!' EXIT; \
	$(NPM) run dev

test:
	$(PY) -m pytest

test-web:
	$(NPM) run test

test-e2e:
	$(NPM) run e2e

# Named separately because it is the suite that must not be skipped when auth changes.
# It needs a reachable PostgreSQL; without one every test in it skips rather than fails,
# which is why it is worth running deliberately rather than only as part of `test`.
test-security:
	$(PY) -m pytest tests/api -v

test-all: test test-web test-e2e

lint:
	$(PY) -m ruff check orbit tests experiments api
	$(PY) -m black --check orbit tests experiments api
	$(NPM) run lint
	$(NPM) run typecheck

format:
	$(PY) -m black orbit tests experiments api
	$(PY) -m ruff check --fix orbit tests experiments api

typecheck:
	$(PY) -m mypy

check: lint typecheck test

bench:
	$(PY) -m experiments.run_a8 --workers 8

bench-mechanisms:
	$(PY) -m experiments.run_a8 --workers 8 --only mechanisms

optimality:
	$(PY) -m experiments.optimality --workers 8

# Deliberately single-threaded: contention inflates wall-clock control timings roughly
# tenfold, so this must not be parallelised (see the module docstring).
control-cost:
	$(PY) -m experiments.control_cost

reproduce:
	$(PY) -m experiments.figures

web-data:
	$(PY) -m experiments.export_web

api:
	$(PY) -m uvicorn api.main:app --reload

worker:
	$(PY) -m api.worker

migrate:
	$(PY) -m alembic upgrade head

docker-build:
	docker build -f deploy/Dockerfile.api -t orbit-api:local .
	docker build -f deploy/Dockerfile.web -t orbit-web:local .

docker-up:
	docker compose up -d

docker-down:
	docker compose down -v

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis
