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
	sync-docs \
	package-smoke \
	install-hooks \
	install-ci-tools \
	install-full-tools

PIP := python -m pip
LINT_IMPORTS := $(shell python -c "import pathlib,sys; print(pathlib.Path(sys.executable).with_name('lint-imports'))")
IMPORTLINTER_CONFIG ?= .github/importlinter.ini
PYTEST_XML ?=
PYTEST_XML_FLAG := $(if $(PYTEST_XML),--junitxml=$(PYTEST_XML),)

sync-docs:
	mkdir -p desloppify/data/global
	find desloppify/data/global -maxdepth 1 -type f -name '*.md' -delete
	cp docs/*.md desloppify/data/global/

install-hooks:
	mkdir -p .git/hooks
	cp .githooks/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "Git hooks installed."

install-ci-tools: install-hooks
	$(PIP) install --upgrade pip
	$(PIP) install -e . pytest mypy ruff import-linter build twine pyyaml

install-full-tools: install-hooks
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
	pytest -q desloppify/tests/commands/test_lifecycle_transitions.py -k "assessment_then_score_when_no_review_followup"

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
		python -m pip install "$$WHEEL[full]" && \
		python -c "from importlib.resources import files; from pathlib import Path; docs=Path('docs'); bundled=files('desloppify.data.global'); names=sorted(p.name for p in docs.glob('*.md')); assert names; missing=[name for name in names if not bundled.joinpath(name).is_file()]; assert not missing, f'missing bundled docs: {missing}'; mismatched=[name for name in names if bundled.joinpath(name).read_text(encoding='utf-8') != (docs / name).read_text(encoding='utf-8')]; assert not mismatched, f'mismatched bundled docs: {mismatched}'" && \
		python -c "import importlib.metadata as m,sys; extras=set(m.metadata('desloppify').get_all('Provides-Extra') or []); required={'full','treesitter','python-security','scorecard'}; missing=required-extras; print('missing extras metadata:', sorted(missing)) if missing else None; sys.exit(1 if missing else 0)" && \
		desloppify --help > /dev/null
	rm -rf .pkg-smoke

ci-fast: lint typecheck arch ci-contracts tests

ci: ci-fast tests-full package-smoke
