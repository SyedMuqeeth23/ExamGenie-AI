.PHONY: install run compile-diagrams

PYTHON  := .venv/bin/python
STREAMLIT := $(PYTHON) -m streamlit
export DYLD_LIBRARY_PATH := /opt/homebrew/lib$(if $(DYLD_LIBRARY_PATH),:$(DYLD_LIBRARY_PATH),)

install:
	$(PYTHON) -m pip install -r requirements.txt

compile-diagrams:
	bash scripts/compile_diagrams.sh

run: compile-diagrams
	$(STREAMLIT) run app.py
