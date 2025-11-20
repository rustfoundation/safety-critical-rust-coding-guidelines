PYTHON_FILES = \
	scripts/markdown_to_github_issue.py \
	scripts/tests/*.py \

all: check test

check: check_python

check_python: check_ruff check_pyright

check_ruff:
	uv run ruff check $(PYTHON_FILES)

check_pyright:
	uv run pyright $(PYTHON_FILES)

test: test_python

test_python:
	uv run pytest scripts/tests/*.py

.PHONY: all check check_python check_mypy test test_python
