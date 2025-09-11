PYTHON_FILES = \
	scripts/markdown_to_github_issue.py \
	scripts/tests/*.py \

all: check test

check: check_python

check_python: check_ruff check_mypy

check_ruff:
	ruff check $(PYTHON_FILES)

check_mypy:
	mypy $(PYTHON_FILES)

test: test_python

test_python:
	pytest scripts/tests/*.py

.PHONY: all check check_python check_mypy test test_python
