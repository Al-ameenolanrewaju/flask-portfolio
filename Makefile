PYTHON ?= python
RUFF_SELECT = E4,E7,E9,F

.PHONY: check
check:
	$(PYTHON) -m ruff check --isolated --select $(RUFF_SELECT) .
	$(PYTHON) -m pytest -q
