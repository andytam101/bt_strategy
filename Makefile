VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
MYPY = $(VENV)/bin/mypy
RUFF = $(VENV)/bin/ruff
PYTEST = $(VENV)/bin/pytest

$(VENV):
	python3 -m venv $(VENV)

develop: $(VENV)
	$(PIP) install -e ../bt_sdk
	$(PIP) install -e ".[dev]"

type-check:
	$(MYPY) backtest.py

format:
	$(RUFF) format .
	$(RUFF) check --fix .

test:
	$(PYTEST)

pipeline: format type-check test

strategy:
	@if [ -z "$(name)" ]; then echo "Usage: make strategy name=my_strategy"; exit 1; fi
	@if [ -d "$(name)" ]; then echo "Error: '$(name)' already exists"; exit 1; fi
	@cp -r _template $(name)
	@mv $(name)/_template $(name)/$(name)
	@PASCAL=$$(echo "$(name)" | sed 's/_\(.\)/\u\1/g; s/^\(.\)/\u\1/'); \
	sed -i "s/_TemplateStrategy/$${PASCAL}Strategy/g" $(name)/$(name)/main.py; \
	sed -i "s/_template/$(name)/g" $(name)/$(name)/__init__.py; \
	sed -i "s/_Template/$${PASCAL}/g" $(name)/$(name)/__init__.py; \
	sed -i "s/_Template/$${PASCAL}/g" $(name)/README.md; \
	sed -i "s/name = \"template\"/name = \"$(name)\"/" $(name)/pyproject.toml
	@echo "✅ Strategy '$(name)' created"
	@echo "   cd $(name) && make develop"

clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

.PHONY: develop type-check format test pipeline clean strategy