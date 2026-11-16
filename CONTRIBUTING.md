# Contributing to SEO-Magus

Thank you for your interest in contributing! 🚀 Bug fixes, new audit checks, classifier providers, benchmark sites,
CMS connectors and documentation are all welcome. Please follow our [Code of Conduct](CODE_OF_CONDUCT.md).

- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Tests](#tests)
- [How to add...](#how-to-add)
- [Conventions](#conventions)
- [Making a pull request](#making-a-pull-request)
- [Hacktoberfest issues](#hacktoberfest-issues)

---

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/SEO-magus.git && cd SEO-magus
make install          # ./venv with requirements-dev.txt (runtime dependencies + pytest)
make test             # the whole suite, offline, ~15 s
make help             # every target
```
Without `make` (e.g. Windows): `python -m venv venv`, activate it, `pip install -r requirements-dev.txt`, then
`python -m pytest`.

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
    jev_client.py             TypeSafe Jev API client
  workflows/
    linking_optimizer.py      the link decision flow
    site_audit.py             technical SEO checks on a crawl
  reporting/                  ranking analysis, HTML report, terminal tables
  benchmarks/                 benchmark registry, reference ground truth, mock site server + ground truth
config/                       config.example.yaml, sites/<benchmark>.yaml
mock_sites/                   static good / scrambled versions of a site, crawled by the tests
tests/                        one file per area (see below)
docs/                         user and design documentation
```

The methodology is described in [docs/ALGORITHMS.md](docs/ALGORITHMS.md); the original design rationale in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

All tests are offline: sites are served by local HTTP servers, LLM providers by fake local servers.

| Target | Scope |
| :--- | :--- |
| `make test` | everything |
| `make test-engines` | graph, taxonomy, text matching, anchors, Jev client (`tests/test_engines.py`) |
| `make test-cheirank`, `make test-weighted-pagerank`, `make test-ranking` | ranking algorithms and their shared contract |
| `make test-crawler` | HTML extraction, crawler features, real HTTP crawls of the mock sites |
| `make test-site-audit` | audit checks against the mock sites' ground truth |
| `make test-classifiers` | classifier providers, plugins, fallback |
| `make test-optimizer` | link decision flow |
| `make test-config` | config loading and CLI wiring |
| `make test-benchmarks` / `make test-reference` / `make test-mock-sites` | benchmark sites and ground-truth sanity checks |
| `make test-reporting`, `make test-logging` | reports, terminal output, logging |
| `make test-docs` | documentation matches the code (checks, commands, config keys, links) |
| `make test-fallback` | everything with networkx blocked (pure-Python graph backend) |

Pass extra pytest arguments with `ARGS`, e.g. `make test ARGS="-k redirect -x"`.

## How to add...

**An audit check** – add the code and its severity to `ISSUE_SEVERITY` and the check to `audit_site()` in
`src/workflows/site_audit.py`; plant the problem in `mock_sites/greenleaf-scrambled/`, add it to `EXPECTED_ISSUES`
in `src/benchmarks/mock_sites.py` (the good site must stay clean) and document it in
[docs/CRAWLER.md](docs/CRAWLER.md#site-audit-checks) – `make test-docs` checks that.

**A crawler feature** – `src/connectors/crawling/`; test it against a small `RouteServer` in `tests/test_crawler.py`
(any HTTP behaviour can be scripted) and keep results independent of `concurrency`.

**A classifier provider** – see [docs/CLASSIFIERS.md](docs/CLASSIFIERS.md#adding-a-built-in-provider).

**A benchmark site** – see [docs/BENCHMARKS.md](docs/BENCHMARKS.md#adding-a-benchmark-site). Never add site-specific
rules to `src/engines/` or `src/workflows/`: everything site-specific belongs in `config/sites/<site>.yaml`.

**A mock site change** – keep the good and scrambled versions' article text identical (the scrambled site must be
repairable into the good one) and update the expected scan, issues and links in `src/benchmarks/mock_sites.py`.

**A config option** – add it to the relevant dataclass (strict: unknown keys are errors), to
`config/config.example.yaml` and to [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

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
3. `make test` and `make test-fallback` pass.
4. New behaviour comes with tests (and docs when user-visible).

## Hacktoberfest issues

SEO-Magus participates in **Hacktoberfest**. Claim an issue by commenting on it; spam PRs (whitespace, trivial edits,
bot-generated changes) are labelled `spam`/`invalid`.

| # | Issue | Status |
| :---: | :--- | :--- |
| 1 | WordPress REST API connector to apply the proposed links | open |
| 2 | Next.js & Vercel documentation site benchmark | open |
| 3 | Ghost CMS Admin API connector & webhook listener | open |
| 4 | Weighted internal PageRank with click depth & CheiRank | done (`compute_weighted_pagerank`, `compute_cheirank`) |
| 5 | Local LLM fallback (Ollama / llama.cpp) for System 1 decisions | done (`classifier.provider: ollama` / `openai_compatible`) |
| 6 | Interactive force-directed link graph visualizer (D3.js) | open (a static semantic map exists in the HTML report) |
| 7 | GitHub Action auditing Markdown PRs for broken link silos | open |

Also welcome: importing Search Console exports, JavaScript rendering for the crawler, LLM-based sentence rewriting.

Questions? Open an issue or a discussion. Happy hacking! 🎃
