# Building errand, and sending it out.
#
# None of this is needed to USE errand: it runs from a checkout, with no install
# at all and nothing to install. This is for the two other things -- putting it
# on the PATH of an environment, and publishing it.
#
# The release order. Every step is repeatable except the last, which is not:
#
#   make test            the suite ( written with errand ) must pass
#   make build           sdist + wheel, from an emptied dist/
#   make check           twine's reading of the metadata, strictly
#   make testpypi        upload to TestPyPI, then install it from there and run it
#   make tag             git tag v$(VERSION)
#   make pypi            THE one that cannot be undone: a version number on PyPI
#                        is spent forever, deleting the file does not free it
#
# So the version is bumped in ONE place -- errand/__init__.py -- and everything
# else, the metadata included, reads it from there.

PY      ?= python3
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' errand/__init__.py)
DIST    := errand-run
VENV    ?= .venv

# The tools that build and upload live in a virtual environment of their own,
# built on demand. Publishing must not depend on what happens to be installed
# on the machine doing it -- and on a system python, pip will rightly refuse.
TOOLS   := .venv-release
TOOLSPY := $(TOOLS)/bin/python

.PHONY: help dev venv test build check testpypi pypi tag clean site site-build

help:
	@echo "errand $(VERSION)   ( distribution: $(DIST) )"
	@echo
	@echo "  make venv        a virtual environment with errand installed in it, editable"
	@echo "  make dev         pip install -e .  into the interpreter you are using now"
	@echo "  make test        run the suite         ( make test ARGS='test_queue' )"
	@echo
	@echo "  make site        the website, live reloading   ( docs/, VitePress )"
	@echo "  make site-build  the website into docs/.vitepress/dist"
	@echo
	@echo "  make build       sdist + wheel into dist/"
	@echo "  make check       twine check --strict"
	@echo "  make testpypi    upload to TestPyPI"
	@echo "  make tag         git tag v$(VERSION)"
	@echo "  make pypi        upload to PyPI -- irreversible"
	@echo "  make clean       dist/, build artefacts, __pycache__"

# ── using it ────────────────────────────────────────────────────────────────

# Editable, because the interesting install is the one where the checkout IS
# the package: `errand` on the PATH, and an edit to errand/cli.py takes effect
# on the next command without reinstalling anything.
dev:
	$(PY) -m pip install -e .

venv:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --quiet --upgrade pip
	$(VENV)/bin/python -m pip install -e .
	@echo
	@echo "  . $(VENV)/bin/activate    then: errand --tui"

# PYTHONPATH so this works from a bare checkout too -- the suite is the first
# thing to run, and having to install something first would be the wrong order.
test:
	cd tests && PYTHONPATH=$(CURDIR) $(PY) -m errand $(ARGS)

# ── the website ─────────────────────────────────────────────────────────────
#
# Everything web lives under docs/, including its package.json, so the project
# root stays a Python package root. `npm install` is idempotent and quick once
# the modules are there, so there is no separate step to remember.

site: docs/node_modules
	cd docs && npm run dev

site-build: docs/node_modules
	cd docs && npm run build

docs/node_modules: docs/package.json
	cd docs && npm install
	@touch $@

# ── publishing ──────────────────────────────────────────────────────────────

$(TOOLSPY):
	$(PY) -m venv $(TOOLS)
	$(TOOLSPY) -m pip install --quiet --upgrade pip build twine

build: $(TOOLSPY)
	rm -rf dist
	$(TOOLSPY) -m build

check: build
	$(TOOLSPY) -m twine check --strict dist/*

# Credentials: a PyPI API token, in ~/.pypirc or in TWINE_USERNAME=__token__ /
# TWINE_PASSWORD=pypi-… . Never in this file.
testpypi: check
	$(TOOLSPY) -m twine upload --repository testpypi dist/*
	@echo
	@echo "  check it came out whole:"
	@echo "  pip install -i https://test.pypi.org/simple/ $(DIST)==$(VERSION)"

pypi: check
	@test -z "$$(git status --porcelain)" || { echo "  the tree is not clean -- commit first"; exit 1; }
	@case "$(VERSION)" in *dev*|*a*|*b*|*rc*) \
	  echo "  $(VERSION) is a pre-release; say FORCE=1 if that is what you mean"; \
	  [ -n "$(FORCE)" ] || exit 1 ;; esac
	$(TOOLSPY) -m twine upload dist/*
	@echo "  don't forget: make tag"

tag:
	git tag -a v$(VERSION) -m "errand $(VERSION)"
	@echo "  git push origin v$(VERSION)"

clean:
	rm -rf dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
