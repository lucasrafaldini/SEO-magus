# SEO-Magus developer tasks.
#
#   make install        create ./venv and install runtime + test dependencies
#   make test           run the whole test suite
#   make test-<scope>   run one scope (see `make help`)
#
# Extra pytest arguments can be passed with ARGS, e.g.:
#   make test ARGS="-k cheirank -x"

PYTHON ?= python3
VENV   ?= venv
ARGS   ?=

VENV_PYTHON := $(VENV)/bin/python
PYTEST      := $(VENV_PYTHON) -m pytest
STAMP       := $(VENV)/.installed

ENGINE_TESTS := tests/test_engines.py

.DEFAULT_GOAL := help
.PHONY: help install venv test test-engines test-link-graph test-ranking test-cheirank \
        test-weighted-pagerank test-taxonomy test-anchors test-jev test-auxiliary-ai test-gsc \
        test-config test-optimizer test-reporting test-logging test-benchmarks test-reference \
        test-fallback test-crawler test-site-audit test-classifiers test-mock-sites test-docs \
        benchmark benchmark-report serve-mock audit-mock clean distclean

help: ## Show this help
	@echo "Usage: make <target> [ARGS=\"extra pytest args\"]"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-24s %s\n", $$1, $$2}'

# ----------------------------------------------------------------- environment

$(VENV_PYTHON):
	@$(PYTHON) -m venv $(VENV) || { \
		echo "Could not create a virtualenv with '$(PYTHON) -m venv'."; \
		echo "On Debian/Ubuntu install it with: sudo apt install python3-venv"; \
		exit 1; }

# Re-installs only when a requirements file changes.
$(STAMP): $(VENV_PYTHON) requirements.txt requirements-dev.txt
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	@touch $(STAMP)

venv: $(VENV_PYTHON) ## Create the virtualenv only

install: $(STAMP) ## Create ./venv and install runtime + test dependencies

# ---------------------------------------------------------------------- tests

test: $(STAMP) ## Run all tests
	$(PYTEST) $(ARGS)

test-engines: $(STAMP) ## Engine unit tests (graph, taxonomy, Jev, auxiliary AI, GSC)
	$(PYTEST) $(ENGINE_TESTS) $(ARGS)

test-link-graph: $(STAMP) ## LinkGraph core: links, orphans, PageRank, link rules
	$(PYTEST) $(ENGINE_TESTS)::TestLinkGraph $(ARGS)

test-ranking: $(STAMP) ## Shared ranking contract (alpha / max_iter / tol, both backends)
	$(PYTEST) $(ENGINE_TESTS)::TestRankingContract $(ARGS)

test-cheirank: $(STAMP) ## CheiRank (PageRank on the reversed graph)
	$(PYTEST) $(ENGINE_TESTS)::TestCheiRank $(ARGS)

test-weighted-pagerank: $(STAMP) ## Pillar click-depth weighted PageRank
	$(PYTEST) $(ENGINE_TESTS)::TestWeightedPageRank $(ARGS)

test-taxonomy: $(STAMP) ## Pillar / money page taxonomy matching
	$(PYTEST) $(ENGINE_TESTS)::TestSiteTaxonomy $(ARGS)

test-anchors: $(STAMP) ## Text matching, Jev simulation vocabulary, anchor quality
	$(PYTEST) $(ENGINE_TESTS)::TestTextMatching $(ENGINE_TESTS)::TestJevSimulation $(ENGINE_TESTS)::TestAnchorQuality $(ARGS)

test-jev: $(STAMP) ## TypeSafe Jev client
	$(PYTEST) $(ENGINE_TESTS)::TestJevClient $(ARGS)

test-auxiliary-ai: $(STAMP) ## Auxiliary AI anchor insertion
	$(PYTEST) $(ENGINE_TESTS)::TestAuxiliaryAI $(ARGS)

test-gsc: $(STAMP) ## Google Search Console connector
	$(PYTEST) $(ENGINE_TESTS)::TestGSCConnector $(ARGS)

test-config: $(STAMP) ## Config (thresholds, taxonomy, link_rules) wiring into optimizer / GSC / CLI
	$(PYTEST) tests/test_config.py $(ARGS)

test-optimizer: $(STAMP) ## Optimizer flow: best paragraph, Search Console steering, link rules
	$(PYTEST) tests/test_optimizer.py $(ARGS)

test-reporting: $(STAMP) ## Visual reports: ranking analysis, HTML semantic map, terminal leaderboard
	$(PYTEST) tests/test_reporting.py $(ARGS)

test-logging: $(STAMP) ## Logging configuration and workflow log events
	$(PYTEST) tests/test_logging.py $(ARGS)

test-benchmarks: $(STAMP) ## All benchmark sites: invariants, expected links, known gaps
	$(PYTEST) tests/test_benchmarks.py $(ARGS)

test-reference: $(STAMP) ## Sanity check: ground-truth reference site + published PageRank
	$(PYTEST) tests/test_benchmarks.py::TestReferenceGroundTruth tests/test_benchmarks.py::TestRankingKnownAnswer $(ARGS)

test-crawler: $(STAMP) ## Crawler: HTML extraction and real HTTP crawls of the mock sites
	$(PYTEST) tests/test_crawler.py $(ARGS)

test-site-audit: $(STAMP) ## Site audit: technical SEO issues found on the mock sites
	$(PYTEST) tests/test_site_audit.py $(ARGS)

test-classifiers: $(STAMP) ## Pluggable link classifiers (Jev, OpenAI-compatible, Anthropic, local, plugins)
	$(PYTEST) tests/test_classifiers.py $(ARGS)

test-mock-sites: $(STAMP) ## Offline end-to-end scan check: crawl + audit + links on the good/scrambled mock sites
	$(PYTEST) tests/test_crawler.py tests/test_site_audit.py tests/test_benchmarks.py -k "mock or Mock or scrambled or good or crawled" $(ARGS)

test-docs: $(STAMP) ## Documentation matches the code (checks, commands, config keys, links)
	$(PYTEST) tests/test_docs.py $(ARGS)

test-fallback: $(STAMP) ## All tests with networkx blocked (pure-Python graph backend)
	$(VENV_PYTHON) -c "import sys; sys.modules['networkx'] = None; import pytest; sys.exit(pytest.main(sys.argv[1:]))" $(ARGS)

# ----------------------------------------------------------------- benchmarks

SITE ?= all
REPORT_DIR ?= build/benchmark-report
LOG_LEVEL ?= WARNING

benchmark: $(STAMP) ## Terminal benchmark report: verdicts and ranking leaderboards; SITE=<key>, LOG_LEVEL=INFO|DEBUG
	$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) benchmark --site $(SITE)

benchmark-report: $(STAMP) ## Visual HTML benchmark report (semantic map, leaderboard) in build/benchmark-report
	$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) benchmark --site $(SITE) --html $(REPORT_DIR)

MOCK_SITE ?= greenleaf-scrambled
PORT ?= 8000

serve-mock: $(STAMP) ## Serve a mock site on localhost:8000 (MOCK_SITE=greenleaf-good or greenleaf-scrambled, PORT=...)
	$(VENV_PYTHON) -m src.cli serve-mock $(MOCK_SITE) --port $(PORT)

audit-mock: $(STAMP) ## Crawl + audit a mock site through the real CLI, HTML in build/audit-<site>
	@$(VENV_PYTHON) -m src.cli serve-mock $(MOCK_SITE) --port $(PORT) >/dev/null 2>&1 & \
	SERVER=$$!; sleep 1; \
	$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) audit --url http://127.0.0.1:$(PORT)/ \
		--config config/sites/greenleaf.yaml --html build/audit-$(MOCK_SITE); \
	STATUS=$$?; kill $$SERVER; exit $$STATUS

# ---------------------------------------------------------------------- clean

clean: ## Remove Python and pytest caches
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache build

distclean: clean ## Also remove the virtualenv
	rm -rf $(VENV)
