.PHONY: \
	ci \
	ci-fast \
	lint \
	typecheck \
	arch \
	ci-contracts \
	integration-roslyn \
	tests \
	tests-full \
	package-smoke \
	install-ci-tools \
	install-full-tools

PIP := python -m pip
LINT_IMPORTS := $(shell python -c "import pathlib,sys; print(pathlib.Path(sys.executable).with_name('lint-imports'))")
IMPORTLINTER_CONFIG ?= .github/importlinter.ini
PYTEST_XML ?=
PYTEST_XML_FLAG := $(if $(PYTEST_XML),--junitxml=$(PYTEST_XML),)

install-ci-tools:
	$(PIP) install --upgrade pip
	$(PIP) install -e . pytest mypy ruff import-linter build twine pyyaml

install-full-tools:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[full]" pytest ruff

lint: install-ci-tools
	ruff check . --select E9,F63,F7,F82

typecheck: install-ci-tools
	python -m mypy

arch: install-ci-tools
	@if [ ! -f "$(IMPORTLINTER_CONFIG)" ]; then \
		echo "Missing $(IMPORTLINTER_CONFIG). Add import contracts before running arch gate."; \
		exit 1; \
	fi
	$(LINT_IMPORTS) --config $(IMPORTLINTER_CONFIG)

ci-contracts: install-ci-tools
	pytest -q desloppify/tests/ci/test_ci_contracts.py

integration-roslyn: install-ci-tools
	pytest -q desloppify/tests/lang/csharp/test_csharp_deps.py -k "roslyn"

tests: install-ci-tools
	pytest -q $(PYTEST_XML_FLAG)

tests-full: install-full-tools
	pytest -q $(PYTEST_XML_FLAG)

package-smoke: install-ci-tools
	rm -rf dist .pkg-smoke
	python -m build
	twine check dist/*
	python -m venv .pkg-smoke
	. .pkg-smoke/bin/activate && \
		python -m pip install --upgrade pip && \
		WHEEL=$$(ls -t dist/desloppify-*.whl | head -n 1) && \
		python -m pip install "$$WHEEL" && \
		desloppify --help > /dev/null
	rm -rf .pkg-smoke

ci-fast: lint typecheck arch ci-contracts tests

ci: ci-fast tests-full package-smoke
