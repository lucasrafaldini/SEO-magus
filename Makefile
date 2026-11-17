# SEO-Magus developer tasks. `make help` lists every target by context.
#
#   make install            create ./venv and install runtime + test dependencies
#   make test-unit          fast feedback while coding (in-process, no network, a few seconds)
#   make test               everything: unit + integration + benchmark tiers
#   make ci                 what CI runs: every tier, both graph backends, coverage gate
#   make benchmark          run the benchmark sites through the real CLI
#   make logs               what the last make runs did (target, time, result, log file)
#
# Extra pytest arguments can be passed with ARGS, e.g.:
#   make test ARGS="-k cheirank -x"
#   make test-integration ARGS="-x --lf"
#
# Every step runs through scripts/make_step.py: its purpose, command and context are printed
# before it, a digest of what happened after it (tests passed, coverage, files written...), its
# full output goes to build/logs/<time>-<target>.log and one line to build/logs/history.jsonl.
# All steps of one `make` invocation share a run id (SEO_MAGUS_RUN_ID), also shown in tool logs.

PYTHON ?= python3
VENV   ?= venv
ARGS   ?=

VENV_PYTHON := $(VENV)/bin/python
PYTEST      := $(VENV_PYTHON) -m pytest
COVERAGE    := $(VENV_PYTHON) -m coverage
STAMP       := $(VENV)/.installed

ENGINE_TESTS := tests/test_engines.py

# Test tiers are pytest markers (registered in pytest.ini, explained in CONTRIBUTING.md#tests).
UNIT_TIER := not integration and not benchmark

# Coverage of src/ (settings in .coveragerc); `make coverage` and `make ci` fail below this.
COVERAGE_MIN ?= 98
COV          := --cov --cov-report=

# Logs of the tools run by make: INFO = milestones (config, crawl, audit, link search progress, results).
LOG_LEVEL      ?= INFO
EVAL_LOG_LEVEL ?= WARNING

ifndef SEO_MAGUS_RUN_ID
SEO_MAGUS_RUN_ID := $(shell date -u +%Y%m%dT%H%M%SZ)-$(shell od -An -N2 -tx2 /dev/urandom | tr -d ' ')
endif
export SEO_MAGUS_RUN_ID

STEP = $(PYTHON) scripts/make_step.py --target $@

.DEFAULT_GOAL := help
.PHONY: help logs last-log install venv \
        test test-unit test-integration test-benchmarks test-fallback ci \
        test-engines test-link-graph test-ranking test-cheirank test-weighted-pagerank test-taxonomy test-anchors \
        test-jev test-auxiliary-ai test-gsc test-config test-optimizer test-reporting test-export test-cli \
        test-logging test-reference test-crawler test-site-audit test-classifiers test-mock-sites test-docs \
        test-evaluation coverage benchmark benchmark-report serve-mock audit-mock fixtures clean distclean \
        eval eval-smoke eval-corpora eval-wikipedia eval-archive eval-stackexchange eval-run eval-crawl eval-scale \
        eval-export eval-compare

##@ Setup

help: ## Show this help
	@echo "Usage: make <target> [ARGS=\"extra pytest args\"]"
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@/ {printf "\n%s\n", substr($$0, 5); next} \
		/^[a-zA-Z_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

logs: ## The last make runs: target, step, duration, result, digest and log file
	@$(PYTHON) scripts/make_step.py history --limit 25

last-log: ## The full log of the last make step (build/logs/)
	@$(PYTHON) scripts/make_step.py last

$(VENV_PYTHON):
	@$(PYTHON) -m venv $(VENV) || { \
		echo "Could not create a virtualenv with '$(PYTHON) -m venv'."; \
		echo "On Debian/Ubuntu install it with: sudo apt install python3-venv"; \
		exit 1; }

# Re-installs only when a requirements file changes.
$(STAMP): $(VENV_PYTHON) requirements.txt requirements-dev.txt
	@$(PYTHON) scripts/make_step.py --target install --step "1/2 upgrade pip" -- $(VENV_PYTHON) -m pip install --upgrade pip
	@$(PYTHON) scripts/make_step.py --target install --step "2/2 requirements-dev.txt" -- \
		$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	@touch $(STAMP)

venv: $(VENV_PYTHON) ## Create the virtualenv only

install: $(STAMP) ## Create ./venv and install runtime + test dependencies
	@echo "Environment ready: $(VENV_PYTHON) (requirements unchanged since the last install are not reinstalled)"

##@ Test tiers (what to run when)

test: $(STAMP) ## All tiers: unit + integration + benchmarks (~40 s)
	@$(STEP) --context "ARGS=$(ARGS)" -- $(PYTEST) $(ARGS)

test-unit: $(STAMP) ## Unit tier: in-process, any socket use fails (--no-network); run it while coding (~10 s)
	@$(STEP) --context "ARGS=$(ARGS)" -- $(PYTEST) -m "$(UNIT_TIER)" --no-network $(ARGS)

test-integration: $(STAMP) ## Integration tier: real HTTP on localhost (mock sites, fake LLM providers, CLI) (~20 s)
	@$(STEP) --context "ARGS=$(ARGS)" -- $(PYTEST) -m integration $(ARGS)

test-benchmarks: $(STAMP) ## Benchmark tier: ground truth + expected links of every benchmark site (~5 s)
	@$(STEP) --context "ARGS=$(ARGS)" -- $(PYTEST) -m benchmark $(ARGS)

test-fallback: $(STAMP) ## All tiers with networkx hidden (pure-Python graph backend)
	@$(STEP) --context "ARGS=$(ARGS)" -- $(PYTEST) --without-networkx $(ARGS)

ci: $(STAMP) ## CI pipeline: unit -> integration -> benchmarks -> fallback, then the coverage gate
	@$(STEP) --step "1/6 unit tier, network blocked" -- $(PYTEST) -m "$(UNIT_TIER)" --no-network $(COV) $(ARGS)
	@$(STEP) --step "2/6 integration tier" -- $(PYTEST) -m integration $(COV) --cov-append $(ARGS)
	@$(STEP) --step "3/6 benchmark tier" -- $(PYTEST) -m benchmark $(COV) --cov-append $(ARGS)
	@$(STEP) --step "4/6 all tiers without networkx" -- $(PYTEST) --without-networkx $(COV) --cov-append $(ARGS)
	@$(STEP) --step "5/6 coverage gate" --context "COVERAGE_MIN=$(COVERAGE_MIN)" -- \
		$(COVERAGE) report --fail-under=$(COVERAGE_MIN)
	@$(STEP) --step "6/6 coverage.xml for CI services" -- $(COVERAGE) xml -o build/coverage.xml

##@ Tests by area

test-engines: $(STAMP) ## Engine unit tests (graph, taxonomy, Jev, auxiliary AI, GSC)
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS) $(ARGS)

test-link-graph: $(STAMP) ## LinkGraph core: links, orphans, PageRank, link rules
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestLinkGraph $(ARGS)

test-ranking: $(STAMP) ## Shared ranking contract (alpha / max_iter / tol, both backends)
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestRankingContract $(ARGS)

test-cheirank: $(STAMP) ## CheiRank (PageRank on the reversed graph)
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestCheiRank $(ARGS)

test-weighted-pagerank: $(STAMP) ## Pillar click-depth weighted PageRank
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestWeightedPageRank $(ARGS)

test-taxonomy: $(STAMP) ## Pillar / money page taxonomy matching
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestSiteTaxonomy $(ARGS)

test-anchors: $(STAMP) ## Text matching, Jev simulation vocabulary, anchor quality
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestTextMatching $(ENGINE_TESTS)::TestJevSimulation \
		$(ENGINE_TESTS)::TestAnchorQuality $(ARGS)

test-jev: $(STAMP) ## TypeSafe Jev client
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestJevClient $(ARGS)

test-auxiliary-ai: $(STAMP) ## Auxiliary AI anchor insertion
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestAuxiliaryAI $(ARGS)

test-gsc: $(STAMP) ## Google Search Console connector
	@$(STEP) -- $(PYTEST) $(ENGINE_TESTS)::TestGSCConnector $(ARGS)

test-config: $(STAMP) ## Config (thresholds, taxonomy, link_rules) wiring into optimizer / GSC / CLI
	@$(STEP) -- $(PYTEST) tests/test_config.py $(ARGS)

test-optimizer: $(STAMP) ## Optimizer flow: best paragraph, Search Console steering, link rules
	@$(STEP) -- $(PYTEST) tests/test_optimizer.py $(ARGS)

test-reporting: $(STAMP) ## Visual reports: ranking analysis, HTML semantic map, terminal leaderboard
	@$(STEP) -- $(PYTEST) tests/test_reporting.py $(ARGS)

test-export: $(STAMP) ## Machine-readable output: JSON / CSV exports and the --fail-on exit code
	@$(STEP) -- $(PYTEST) tests/test_export.py $(ARGS)

test-cli: $(STAMP) ## Command line: every command, HTML output, serve-mock, console encoding
	@$(STEP) -- $(PYTEST) tests/test_cli.py $(ARGS)

test-logging: $(STAMP) ## Logging configuration and workflow log events
	@$(STEP) -- $(PYTEST) tests/test_logging.py $(ARGS)

test-reference: $(STAMP) ## Sanity check: ground-truth reference site + published PageRank
	@$(STEP) -- $(PYTEST) tests/test_benchmarks.py::TestReferenceGroundTruth \
		tests/test_benchmarks.py::TestRankingKnownAnswer $(ARGS)

test-crawler: $(STAMP) ## Crawler: HTML extraction and real HTTP crawls of the mock sites
	@$(STEP) -- $(PYTEST) tests/test_crawler.py $(ARGS)

test-site-audit: $(STAMP) ## Site audit: technical SEO issues found on the mock sites
	@$(STEP) -- $(PYTEST) tests/test_site_audit.py $(ARGS)

test-classifiers: $(STAMP) ## Pluggable link classifiers (Jev, OpenAI-compatible, Anthropic, local, plugins)
	@$(STEP) -- $(PYTEST) tests/test_classifiers.py $(ARGS)

test-mock-sites: $(STAMP) ## Offline end-to-end scan check: crawl + audit + links on the good/scrambled mock sites
	@$(STEP) -- $(PYTEST) tests/test_crawler.py tests/test_site_audit.py tests/test_benchmarks.py tests/test_fixtures.py \
		-k "mock or Mock or scrambled or good or crawled or Saved" $(ARGS)

test-evaluation: $(STAMP) ## Evaluation harness: metrics, statistics, corpus, samplers, systems, tasks, sources, reports
	@$(STEP) -- $(PYTEST) tests/test_evaluation.py tests/test_evaluation_sources.py tests/test_evaluation_reports.py $(ARGS)

test-docs: $(STAMP) ## Documentation matches the code (checks, commands, config keys, links)
	@$(STEP) -- $(PYTEST) tests/test_docs.py $(ARGS)

##@ Coverage

coverage: $(STAMP) ## Coverage of src/ on both graph backends: terminal summary + build/coverage/index.html
	@$(STEP) --step "1/4 all tiers (networkx)" -- $(PYTEST) $(COV) $(ARGS)
	@$(STEP) --step "2/4 all tiers (pure Python graphs)" -- $(PYTEST) --without-networkx $(COV) --cov-append $(ARGS)
	@$(STEP) --step "3/4 report and gate" --context "COVERAGE_MIN=$(COVERAGE_MIN)" -- \
		$(COVERAGE) report --fail-under=$(COVERAGE_MIN)
	@$(STEP) --step "4/4 HTML report" --outputs build/coverage/index.html -- $(COVERAGE) html

##@ Benchmarks (run the tool on the benchmark sites)

SITE ?= all
REPORT_DIR ?= build/benchmark-report

benchmark: $(STAMP) ## Terminal benchmark report: verdicts and ranking leaderboards; SITE=<key>, LOG_LEVEL=INFO|DEBUG
	@$(STEP) --context "SITE=$(SITE)" "LOG_LEVEL=$(LOG_LEVEL)" -- \
		$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) benchmark --site $(SITE)

benchmark-report: $(STAMP) ## Visual HTML benchmark report (semantic map, leaderboard) in build/benchmark-report
	@$(STEP) --context "SITE=$(SITE)" "REPORT_DIR=$(REPORT_DIR)" "LOG_LEVEL=$(LOG_LEVEL)" -- \
		$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) benchmark --site $(SITE) --html $(REPORT_DIR)

##@ Evaluation at scale (methodology: docs/EVALUATION.md)

EVAL_DIR      ?= build/eval
EVAL_CORPORA  ?= $(EVAL_DIR)/corpora
EVAL          := $(VENV_PYTHON) -m src.evaluation --log-level $(EVAL_LOG_LEVEL)
CONTACT       ?=
OFFLINE       ?=
WIKI_LANG     ?= en
WIKI_CATEGORIES ?= Composting "Chess openings" "Cryptographic algorithms" "Jazz standards" "Volcanoes of Iceland" "Programming languages"
IA_COLLECTIONS ?= prelinger gutenberg librivoxaudio
EVAL_LIMIT    ?= 1200
SE_DUMP       ?=
SE_SITE       ?=
SCALE_SIZES   ?= 300 1000 3000 10000
EXPORT        ?= full
REPORTS       ?=
LIVE          = --contact "$(CONTACT)" $(if $(OFFLINE),--offline)

define need_contact
	@test -n "$(CONTACT)$(OFFLINE)" || { echo "Set CONTACT=you@example.com (live sources require a contact in the \
	User-Agent), or OFFLINE=1 to replay the record/replay cache"; exit 2; }
endef

eval-corpora: $(STAMP) ## Build the offline corpora: bundled real corpora + synthetic (3 site styles, 2 languages) + saved mock-site crawl
	@$(STEP) --step "1/6 synthetic encyclopedia, English" -- \
		$(EVAL) synthetic --preset encyclopedia --language en --pages 3000 --topics 20 --out $(EVAL_CORPORA)/synthetic-encyclopedia-en.jsonl.gz
	@$(STEP) --step "2/6 synthetic encyclopedia, Portuguese" -- \
		$(EVAL) synthetic --preset encyclopedia --language pt --pages 2000 --topics 16 --out $(EVAL_CORPORA)/synthetic-encyclopedia-pt.jsonl.gz
	@$(STEP) --step "3/6 synthetic catalog" -- \
		$(EVAL) synthetic --preset catalog --pages 2000 --topics 16 --out $(EVAL_CORPORA)/synthetic-catalog-en.jsonl.gz
	@$(STEP) --step "4/6 synthetic forum" -- \
		$(EVAL) synthetic --preset forum --pages 2000 --topics 16 --out $(EVAL_CORPORA)/synthetic-forum-en.jsonl.gz
	@$(STEP) --step "5/6 saved mock-site crawl" -- \
		$(EVAL) crawl --from-crawl tests/fixtures/greenleaf-good.crawl.json --name greenleaf-good-crawl \
		--out $(EVAL_CORPORA)/greenleaf-good-crawl.jsonl.gz
	@$(STEP) --step "6/6 bundled real-world online corpora (corpora/*.jsonl.gz)" -- \
		sh -c 'mkdir -p $(EVAL_CORPORA) && cp corpora/*.jsonl.gz $(EVAL_CORPORA)/ && $(EVAL) info $(EVAL_CORPORA)/wikipedia-*.jsonl.gz $(EVAL_CORPORA)/internet-archive.jsonl.gz $(EVAL_CORPORA)/stackexchange-*.jsonl.gz'

eval-wikipedia: $(STAMP) ## Fetch a Wikipedia sample (CONTACT=..., WIKI_LANG, WIKI_CATEGORIES, EVAL_LIMIT, OFFLINE=1 replays the cache)
	$(need_contact)
	@$(STEP) --context "WIKI_LANG=$(WIKI_LANG)" "EVAL_LIMIT=$(EVAL_LIMIT)" "OFFLINE=$(OFFLINE)" -- \
		$(EVAL) wikipedia $(LIVE) --lang $(WIKI_LANG) --categories $(WIKI_CATEGORIES) --limit $(EVAL_LIMIT) \
		--out $(EVAL_CORPORA)/wikipedia-$(WIKI_LANG).jsonl.gz

eval-archive: $(STAMP) ## Fetch an Internet Archive sample (CONTACT=..., IA_COLLECTIONS, EVAL_LIMIT, OFFLINE=1 replays the cache)
	$(need_contact)
	@$(STEP) --context "IA_COLLECTIONS=$(IA_COLLECTIONS)" "EVAL_LIMIT=$(EVAL_LIMIT)" "OFFLINE=$(OFFLINE)" -- \
		$(EVAL) archive $(LIVE) --collections $(IA_COLLECTIONS) --limit $(EVAL_LIMIT) \
		--out $(EVAL_CORPORA)/internet-archive.jsonl.gz

eval-stackexchange: $(STAMP) ## Import an extracted Stack Exchange dump (SE_DUMP=dir, SE_SITE=host)
	@test -n "$(SE_DUMP)" -a -n "$(SE_SITE)" || { echo "Set SE_DUMP=<extracted dump dir> SE_SITE=<site host>"; exit 2; }
	@$(STEP) --context "SE_DUMP=$(SE_DUMP)" "SE_SITE=$(SE_SITE)" "EVAL_LIMIT=$(EVAL_LIMIT)" -- \
		$(EVAL) stackexchange --dump $(SE_DUMP) --site $(SE_SITE) --limit $(EVAL_LIMIT) \
		--out $(EVAL_CORPORA)/stackexchange-$(SE_SITE).jsonl.gz

eval-run: $(STAMP) ## Run the pre-registered protocol on every corpus in build/eval/corpora (EXPORT=simple|full)
	@$(STEP) --context "EXPORT=$(EXPORT)" "ARGS=$(ARGS)" -- \
		$(EVAL) run $(EVAL_CORPORA)/*.jsonl.gz --out $(EVAL_DIR) --export $(EXPORT) $(ARGS)

eval-export: $(STAMP) ## Re-write the exports of build/eval/report.json (EXPORT=simple|full): md, csv, jsonl, html
	@$(STEP) --context "EXPORT=$(EXPORT)" -- $(EVAL) export $(EVAL_DIR)/report.json --level $(EXPORT)

eval-compare: $(STAMP) ## Compare reports, first = reference: REPORTS="build/eval-old/report.json build/eval/report.json"
	@test -n "$(REPORTS)" || { echo 'Set REPORTS="<reference report.json> <other report.json> ..."'; exit 2; }
	@$(STEP) --context "REPORTS=$(REPORTS)" -- $(EVAL) compare $(REPORTS) --out $(EVAL_DIR)-compare

eval-crawl: $(STAMP) ## Crawl fidelity: render the synthetic corpora as sites, crawl them over HTTP, compare
	@$(STEP) -- $(EVAL) crawl-fidelity $(EVAL_CORPORA)/synthetic-*.jsonl.gz --out $(EVAL_DIR)

eval-scale: $(STAMP) ## Time and classifier calls against site size (SCALE_SIZES), exhaustive flow checked for equality
	@$(STEP) --context "SCALE_SIZES=$(SCALE_SIZES)" -- $(EVAL) scale --sizes $(SCALE_SIZES) --out $(EVAL_DIR)

eval: eval-corpora eval-run eval-crawl eval-scale ## Everything that runs offline (~30 min); add real sources first for evidence

eval-smoke: $(STAMP) ## Minutes-long sanity run of the whole pipeline on a small synthetic corpus (CI-friendly)
	@$(STEP) --step "1/4 small synthetic corpus" -- \
		$(EVAL) synthetic --pages 300 --topics 6 --out $(EVAL_DIR)/smoke/corpora/synthetic-smoke.jsonl.gz
	@$(STEP) --step "2/4 protocol, 2 samplers x 2 seeds" -- \
		$(EVAL) run $(EVAL_DIR)/smoke/corpora/synthetic-smoke.jsonl.gz --out $(EVAL_DIR)/smoke \
		--samplers random label --seeds 1 2 --sample-size 60
	@$(STEP) --step "3/4 crawl fidelity" -- \
		$(EVAL) crawl-fidelity $(EVAL_DIR)/smoke/corpora/synthetic-smoke.jsonl.gz --out $(EVAL_DIR)/smoke
	@$(STEP) --step "4/4 scale" -- $(EVAL) scale --sizes 100 300 --out $(EVAL_DIR)/smoke

##@ Mock sites and test fixtures

MOCK_SITE ?= greenleaf-scrambled
PORT ?= 8000

serve-mock: $(STAMP) ## Serve a mock site on localhost:8000 (MOCK_SITE=greenleaf-good or greenleaf-scrambled, PORT=...)
	@$(STEP) --context "MOCK_SITE=$(MOCK_SITE)" "PORT=$(PORT)" -- \
		$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) serve-mock $(MOCK_SITE) --port $(PORT)

audit-mock: $(STAMP) ## Crawl + audit a mock site through the real CLI, HTML in build/audit-<site>
	@$(VENV_PYTHON) -m src.cli serve-mock $(MOCK_SITE) --port $(PORT) >/dev/null 2>&1 & \
	SERVER=$$!; sleep 1; \
	$(STEP) --context "MOCK_SITE=$(MOCK_SITE)" "PORT=$(PORT)" "LOG_LEVEL=$(LOG_LEVEL)" \
		--outputs build/audit-$(MOCK_SITE)/audit.html -- \
		$(VENV_PYTHON) -m src.cli --log-level $(LOG_LEVEL) audit --url http://127.0.0.1:$(PORT)/ \
		--config config/sites/greenleaf.yaml --html build/audit-$(MOCK_SITE); \
	STATUS=$$?; kill $$SERVER; exit $$STATUS

fixtures: $(STAMP) ## Re-crawl the mock sites into tests/fixtures/*.crawl.json (after a mock site or crawler change)
	@$(STEP) -- $(VENV_PYTHON) -m tests.fixtures.crawls

##@ Housekeeping

clean: ## Remove Python, pytest and coverage caches and build/ (logs included)
	@$(STEP) --no-log -- sh -c 'find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} + ; \
		rm -rf .pytest_cache .coverage .coverage.* build'

distclean: clean ## Also remove the virtualenv
	@$(STEP) --no-log -- rm -rf $(VENV)
