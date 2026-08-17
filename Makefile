PY := .venv/Scripts/python.exe
ifeq ($(OS),)
PY := .venv/bin/python
endif

.PHONY: help test lint format typecheck check bench reproduce clean

help:
	@echo "test       unit + property + differential tests"
	@echo "lint       ruff + black --check"
	@echo "typecheck  mypy (strict on orbit/)"
	@echo "check      lint + typecheck + test"
	@echo "bench      run the committed A8 experiment grid"
	@echo "reproduce  regenerate every figure and table from raw results"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check orbit tests experiments api
	$(PY) -m black --check orbit tests experiments api

format:
	$(PY) -m black orbit tests experiments api
	$(PY) -m ruff check --fix orbit tests experiments api

typecheck:
	$(PY) -m mypy

check: lint typecheck test

bench:
	$(PY) -m experiments.run_a8 --workers 8

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

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis
