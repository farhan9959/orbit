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
	$(PY) -m ruff check orbit tests experiments
	$(PY) -m black --check orbit tests experiments

format:
	$(PY) -m black orbit tests experiments
	$(PY) -m ruff check --fix orbit tests experiments

typecheck:
	$(PY) -m mypy

check: lint typecheck test

bench:
	$(PY) -m experiments.run_a8 --workers 8

reproduce:
	$(PY) -m experiments.figures

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis
