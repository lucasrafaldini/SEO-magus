# Contributing to SEO-Magus

Thank you for your interest in contributing! 🚀 Bug fixes, new audit checks, classifier providers, benchmark sites,
CMS connectors and documentation are all welcome. Please follow our [Code of Conduct](CODE_OF_CONDUCT.md).

- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Tests](#tests)
- [How to add...](#how-to-add)
- [Conventions](#conventions)
- [Making a pull request](#making-a-pull-request)

---

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/SEO-magus.git && cd SEO-magus
make install          # ./venv with requirements-dev.txt (runtime dependencies, pytest, pytest-cov)
make test-unit        # fast feedback while coding, ~10 s
make test             # the whole suite, offline, ~40 s
make help             # every target, grouped by context
```
Without `make` (e.g. Windows): `python -m venv venv`, activate it, `pip install -r requirements-dev.txt`, then
`python -m pytest` (all tiers), `python -m pytest -m "not integration and not benchmark" --no-network` (unit tier),
`python -m pytest -m integration` or `python -m pytest -m benchmark`.

## Project layout

```
src/
  cli.py                      command line (audit, crawl, benchmark, boost-page2, serve-mock)
  config.py                   site config: thresholds, link_rules, SiteConfig loader (strict)
  log.py                      logging setup (seo_magus.* loggers)
  connectors/
    sitemap_crawler.py        public crawler API (re-exports crawling/)
    crawling/                 urls.py, html_extract.py, fetcher.py, crawler.py
    gsc_connector.py          Search Console rows and SERP page 2 filter
  engines/
    link_graph.py             link graph: PageRank, CheiRank, pillar-weighted PageRank, link rules
    taxonomy.py               page roles and topic clusters from config
    text.py                   shared tokenizer, stopwords and topic matching
    auxiliary_ai.py           anchor selection and sentence rewriting
    classifiers/              pluggable link classifiers (heuristic, jev, llm, factory)
    clustering.py             topic clustering without configuration (TF-IDF k-means, link label propagation)
    jev_client.py             TypeSafe Jev API client
  workflows/
    linking_optimizer.py      the link decision flow
    site_audit.py             technical SEO checks on a crawl
  reporting/                  ranking analysis, HTML report, terminal tables, JSON/CSV export
  benchmarks/                 benchmark registry, reference ground truth, mock site server + ground truth
  evaluation/                 quality at scale: corpora, sources (Wikipedia, Internet Archive, Stack Exchange,
                              crawl, synthetic), samplers, systems and baselines, tasks, protocol; results (tidy
                              rows), stats + analysis (ranks, agreement, sensitivity, meta-analysis), compare
                              (between reports), report / html_report / narrative (exports)
config/                       config.example.yaml, sites/<benchmark>.yaml
mock_sites/                   static good / scrambled versions of a site, crawled by the tests
tests/                        one file per area (see below); conftest.py defines the tiers
  fixtures/                   saved mock-site crawls (make fixtures) and helpers to use them offline
docs/                         user and design documentation
scripts/                      make_step.py: context, digest and logs of every make step
```

The methodology is described in [docs/ALGORITHMS.md](docs/ALGORITHMS.md); the original design rationale in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

All tests are offline: sites are served by local HTTP servers, LLM providers by fake local servers, and no test
ever contacts the internet.

### What to run when

| When | Run | Takes |
| :--- | :--- | :--- |
| While coding, after every change | `make test-unit` | ~10 s |
| Touched the crawler, HTTP providers, mock sites or CLI | `make test-integration` | ~20 s |
| Touched link decisions, anchors, ranking or audit checks | `make test-benchmarks` | ~5 s |
| Before pushing | `make test` (all tiers) | ~40 s |
| Before opening a pull request (= what CI runs) | `make ci` | ~80 s |
| Changed link decisions, anchors, clustering or ranking: how does quality move at scale? | `make eval-smoke`, then `make eval` ([EVALUATION.md](docs/EVALUATION.md)) | minutes |
| To see what is not tested yet | `make coverage`, then open `build/coverage/index.html` | ~60 s |

### Logs of make runs

Every target runs through `scripts/make_step.py`, so every `make` run explains itself:

```
==> make test-unit  (run 20261117T141003Z-ca8b)
    purpose : Unit tier: in-process, any socket use fails (--no-network); run it while coding (~10 s)
    section : Test tiers (what to run when)
    command : venv/bin/python -m pytest -m "not integration and not benchmark" --no-network
    context : git 9c6f8b7 + 12 changed files | python 3.12.3 (/.../venv)
    log     : build/logs/20261117T141003Z-test-unit.log
... the command's own output ...
<== make test-unit: OK in 12.4s
    tests           : 313 passed, 79 deselected in 11.02s
    full log        : build/logs/20261117T141003Z-test-unit.log
```

* **before** a step: its purpose and section (read from the `## description` of the target in the Makefile - document
  a new target there and the wrapper shows it), the exact command, the git revision, the interpreter and the make
  variables that matter for it (`settings:`);
* **after** it: a digest of what happened - tests passed, coverage, quality gate, site health, links proposed,
  benchmark verdicts, scale growth, corpora and files written - the duration and, on failure, the lines that explain
  it plus a hint (rerun failures with `ARGS="--lf"`, mark a networked test `integration`, `make fixtures`,
  `OFFLINE=1`...). The exit code is the command's, so make stops on failures as before;
* the full output of each step is in `build/logs/<time>-<target>[-<step>].log` and one JSON line per step in
  `build/logs/history.jsonl`: `make logs` lists the last runs, `make last-log` prints the last log;
* all steps of one `make` invocation share a run id (`SEO_MAGUS_RUN_ID`), shown in each step's frame, log file and
  history line, and in the first log line of the tools (`Command: benchmark (make run 20261117T141003Z-ca8b)`); the
  log line format itself never changes;
* pytest states what it runs: the tier, the network guard and the graph backend under its banner, and the outcome per
  tier at the end;
* tools run by make log at `LOG_LEVEL=INFO` (milestones: config, crawl, audit, link search progress about every 10%,
  results), the evaluation at `EVAL_LOG_LEVEL=WARNING` (its own progress lines say what runs); use
  `LOG_LEVEL=DEBUG` for every decision.

### Test tiers

Every test belongs to exactly one tier, declared with a pytest marker (registered in `pytest.ini`;
`--strict-markers` rejects typos):

| Tier | Marker | What it may do | Make target |
| :--- | :--- | :--- | :--- |
| **unit** | none (the default) | run in-process only: no sockets, no servers | `make test-unit` |
| **integration** | `@pytest.mark.integration` | real HTTP on `127.0.0.1` (mock sites, `RouteServer`, fake LLM providers), the CLI driving them | `make test-integration` |
| **benchmark** | `@pytest.mark.benchmark` (module-level in `test_benchmarks.py`, `test_famous_sites.py`) | benchmark sites and ground-truth sanity checks | `make test-benchmarks` |

The unit tier is enforced: `make test-unit` runs with `--no-network` (see `tests/conftest.py`), so a test that opens
a socket fails with `NetworkAccessInUnitTest` and a hint to mark it `integration`. Mark a whole class
(`@pytest.mark.integration` above `class ...`) or a single method. Unit tests that need a *real crawl* use the saved
crawls below instead of a server; crawler logic can be driven without HTTP through `SitemapCrawler(fetcher=...)`
(see `FakeFetcher` in `tests/test_crawler.py`).

Two more pytest options come from `tests/conftest.py`: `--without-networkx` hides networkx so the pure-Python graph
backend is tested (`make test-fallback`), and any pytest argument can be added with `ARGS`, e.g.
`make test-unit ARGS="-k redirect -x"` or `make test-integration ARGS="--lf"`.

### Saved crawls (test fixtures)

`tests/fixtures/greenleaf-good.crawl.json` and `greenleaf-scrambled.crawl.json` are real crawls of the mock sites,
saved with their timings zeroed so they are reproducible byte for byte. Unit tests load them with
`tests.fixtures.crawls.load_crawl(site)`, `offline_benchmark(site)` or `offline_analysis(site)` (a full audit + links +
ranking run without HTTP). After changing a mock site or the crawler, run `make fixtures` and commit the result:
`tests/test_fixtures.py` fails in the integration tier when a saved crawl no longer matches a live crawl.

### Coverage

`make coverage` runs the whole suite on both graph backends (networkx and pure Python) and prints the lines and
branches of `src/` that no test executes; `build/coverage/index.html` shows them in context. Settings live in
`.coveragerc` (branch coverage; threads are traced, so code running in crawler workers counts). `make ci` applies the
same measurement tier by tier, fails below `COVERAGE_MIN` (98 %, e.g. `make ci COVERAGE_MIN=99`) and writes
`build/coverage.xml` for CI services. Coverage is a map of untested code, not a goal: a test should assert behaviour,
not just execute lines.

### Tests by area

| Target | Scope |
| :--- | :--- |
| `make test-engines` | graph, taxonomy, text matching, anchors, Jev client (`tests/test_engines.py`) |
| `make test-cheirank`, `make test-weighted-pagerank`, `make test-ranking` | ranking algorithms and their shared contract |
| `make test-crawler` | HTML extraction, crawler features, real HTTP crawls of the mock sites |
| `make test-site-audit` | audit checks against the mock sites' ground truth |
| `make test-classifiers` | classifier providers, plugins, fallback |
| `make test-optimizer` | link decision flow |
| `make test-config` | config loading and CLI wiring |
| `make test-cli` | every command end to end: HTML output, `serve-mock`, console encoding (`tests/test_cli.py`) |
| `make test-reference` / `make test-mock-sites` | ground-truth references / the crawled mock sites only |
| `make test-reporting`, `make test-logging` | reports, terminal output, logging |
| `make test-export` | JSON / CSV exports and the `--fail-on` exit code (`tests/test_export.py`) |
| `make test-evaluation` | evaluation harness: metrics and statistics vs published values, corpus, samplers, systems, tasks, sources replayed offline, reports, exports and comparisons |
| `make test-docs` | documentation matches the code (checks, commands, config keys, links) |

`make help` lists every target grouped by context.

## How to add...

**An audit check** – add the code and its severity to `ISSUE_SEVERITY` and the check to `audit_site()` in
`src/workflows/site_audit.py`; plant the problem in `mock_sites/greenleaf-scrambled/`, add it to `EXPECTED_ISSUES`
in `src/benchmarks/mock_sites.py` (the good site must stay clean) and document it in
[docs/CRAWLER.md](docs/CRAWLER.md#site-audit-checks) – `make test-docs` checks that.

**A crawler feature** – `src/connectors/crawling/`; test parsing and crawl logic as unit tests (`parse_html_page`,
`FakeFetcher`), and real HTTP behaviour against a small `RouteServer` in `tests/test_crawler.py` (any HTTP behaviour
can be scripted; integration tier). Keep results independent of `concurrency`.

**A classifier provider** – see [docs/CLASSIFIERS.md](docs/CLASSIFIERS.md#adding-a-built-in-provider).

**A benchmark site** – see [docs/BENCHMARKS.md](docs/BENCHMARKS.md#adding-a-benchmark-site). Never add site-specific
rules to `src/engines/` or `src/workflows/`: everything site-specific belongs in `config/sites/<site>.yaml`.

**A mock site change** – keep the good and scrambled versions' article text identical (the scrambled site must be
repairable into the good one), update the expected scan, issues and links in `src/benchmarks/mock_sites.py` and
refresh the saved crawls with `make fixtures`.

**A config option** – add it to the relevant dataclass (strict: unknown keys are errors), to
`config/config.example.yaml` and to [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

**A field in the JSON/CSV export** – add it to `ISSUE_FIELDS`, `PAGE_FIELDS` or `LINK_FIELDS` in
`src/reporting/export.py` (the row builders follow those tuples), cover it in `tests/test_export.py` and update the
document shape in [docs/USER_GUIDE.md](docs/USER_GUIDE.md#machine-readable-output-crawl-and-audit). Bump
`SCHEMA_VERSION` when an existing field changes meaning or disappears.

## Conventions

* **Logging** – `logger = get_logger(__name__)` from `src/log.py`. `DEBUG` per-item decisions, `INFO` milestones and
  counts, `WARNING` degraded operation (fallbacks, config problems), `ERROR` failures that abort. Library code never
  configures handlers.
* **No silent fallbacks** – unknown config keys raise; fallbacks are logged and counted.
* **Ground truth first** – when adding a benchmark expectation, write it from the design before running the code; if
  the code disagrees, investigate the code before touching the expectation.
* **Terminal output** is ASCII by default (`src/reporting/terminal.py`); glyphs only behind `--unicode`.
* **Dependencies** – crawler, classifiers and reports use the standard library; keep it that way where possible.

## Making a pull request

1. Branch naming: `feature/...`, `fix/...`, `docs/...`.
2. Descriptive commit messages, e.g. `feat(crawler): honour hreflang alternates`.
3. `make ci` passes (every tier, both graph backends, coverage gate).
4. New behaviour comes with tests in the right tier (and docs when user-visible).

Questions? Open an issue or a discussion.
