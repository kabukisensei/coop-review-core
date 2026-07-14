# coop-review-core dev/release helpers. POSIX make; on Windows run the
# underlying commands with .venv\Scripts\python instead of .venv/bin/python.
# See AGENTS.md for expected outputs and the release runbook.

PY   := .venv/bin/python
RUFF := .venv/bin/ruff

.PHONY: setup test lint build release-check

setup: ## create .venv + editable install with dev extras
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	$(PY) -c "import coop_review_core as c; print('coop-review-core', c.__version__)"

test: ## run the test suite (every test must pass)
	$(PY) -m pytest -q

lint: ## ruff lint + formatting check (both must exit 0)
	$(RUFF) check .
	$(RUFF) format --check .

build: ## build sdist + wheel into dist/ (mirrors publish.yml's build step)
	rm -rf dist
	$(PY) -m pip install -q build
	$(PY) -m build
	ls -l dist

# Mirrors publish.yml's "Verify tag matches package version" gate.
# Usage:
#   make release-check              # pre-tag: fails if v<__version__> already exists
#   make release-check TAG=vX.Y.Z   # exact gate: fails unless TAG matches __version__
release-check: ## version-vs-tag sanity check; run after bumping, before tagging
	@PKG=$$($(PY) -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/coop_review_core/__init__.py').read_text()).group(1))"); \
	if [ -n "$(TAG)" ]; then \
	  T="$(TAG)"; T="$${T#v}"; \
	  echo "tag=$$T package=$$PKG"; \
	  if [ "$$T" != "$$PKG" ]; then \
	    echo "FAIL: tag v$$T does not match package version $$PKG - bump src/coop_review_core/__init__.py first"; exit 1; \
	  fi; \
	else \
	  echo "package=$$PKG (no TAG given: checking v$$PKG is not already tagged)"; \
	  if git rev-parse -q --verify "refs/tags/v$$PKG" >/dev/null; then \
	    echo "FAIL: tag v$$PKG already exists - bump __version__ in src/coop_review_core/__init__.py before releasing"; exit 1; \
	  fi; \
	fi; \
	if [ -n "$$(git status --porcelain)" ]; then \
	  echo "WARN: working tree not clean - a tag made now would not match what you tested"; \
	fi; \
	if ! grep -q "^## \[$$PKG\]" CHANGELOG.md; then \
	  echo "WARN: CHANGELOG.md has no '## [$$PKG]' heading - rotate [Unreleased] before tagging (see AGENTS.md release steps)"; \
	fi; \
	echo "OK: version $$PKG is release-ready"
