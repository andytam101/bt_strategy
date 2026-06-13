VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
MYPY = $(VENV)/bin/mypy
RUFF = $(VENV)/bin/ruff
PYTEST = $(VENV)/bin/pytest

$(VENV):
	python3 -m venv $(VENV)

develop: $(VENV)
	$(PIP) install -e ../../../bt_sdk
	$(PIP) install -e ".[dev]"

type-check:
	$(MYPY) .

format:
	$(RUFF) format .
	$(RUFF) check --fix .

test:
	$(PYTEST)	

.PHONY: develop type-check format test clean

clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
