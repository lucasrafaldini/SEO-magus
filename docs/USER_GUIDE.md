# User Guide

Everything you need to run SEO-Magus on a site and read its results. For the configuration file see
[CONFIGURATION.md](CONFIGURATION.md).

- [Installation](#installation)
- [Commands](#commands)
- [Typical workflows](#typical-workflows)
- [Reading the results](#reading-the-results)
- [Logging](#logging)
- [Terminal output](#terminal-output)
- [FAQ](#faq)

---

## Installation

Requires Python 3.10+.

```bash
make install                 # creates ./venv and installs requirements-dev.txt (runtime + pytest)
source venv/bin/activate     # optional; `make` targets use ./venv directly
```

Without `make` (e.g. Windows): `python -m venv venv`, activate it, then `pip install -r requirements-dev.txt`.
All commands below are run from the repository root as `python -m src.cli <command>`.

---

## Commands

Global options go **before** the command:

| Option | Effect |
| :--- | :--- |
| `-v` / `-vv` (`--verbose`) | Log workflow milestones (INFO) / every decision (DEBUG) to stderr |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` (default) or `ERROR` (env: `SEO_MAGUS_LOG_LEVEL`) |
| `--log-file FILE` | Also write the logs to a file |
| `--unicode` | Box-drawing characters and glyphs in tables (default: plain ASCII; env: `SEO_MAGUS_UNICODE=1`) |
| `--no-color` | No colours (also honoured: `NO_COLOR`, `TERM=dumb`) |

Settings precedence for every command: **command-line flag > `--config` file > built-in default**.

### `crawl` – crawl + site audit

```bash
python -m src.cli crawl --url https://example.com/ [--config FILE] [--issues N] [crawler options]
```
Crawls the site and prints the site health and its issues. Makes **no classifier calls**, so it is free and fast
even when a paid classifier is configured.

| Option | Effect |
| :--- | :--- |
| `--url URL` | Start URL to crawl (required) |
| `--config FILE` | Site config (crawler settings and audit thresholds are used) |
| `--issues N` | Issues shown in the terminal (default 25) |

Plus the [crawler options](#crawler-options-crawl-and-audit) and the
[machine-readable output options](#machine-readable-output-crawl-and-audit).

### `audit` – crawl + site audit + link proposals + ranking

```bash
python -m src.cli audit --url https://example.com/ --config config/config.yaml --html build/report
python -m src.cli audit --from-crawl build/crawl.json --config config/config.yaml
python -m src.cli audit                                   # demo site (4 pages, site audit included), no network
```

| Option | Effect |
| :--- | :--- |
| `--url URL` | Start URL to crawl (without it, and without `--from-crawl`, a small demo dataset is used) |
| `--demo` | use the demo dataset (the default when neither `--url` nor `--from-crawl` is given) |
| `--from-crawl FILE` | Audit a crawl saved with `--save-crawl` instead of crawling |
| `--config FILE` | Site config: roles, clusters, thresholds, crawler, classifier |
| `--html DIR` | Write the visual HTML report (`DIR/audit.html`) |
| `--min-score`, `--min-conf` | Override the classifier gate thresholds |
| `--top N` | Pages shown in the terminal ranking (default 10) |

Plus the [crawler options](#crawler-options-crawl-and-audit) and the
[machine-readable output options](#machine-readable-output-crawl-and-audit).

### Machine-readable output (`crawl` and `audit`)

Both commands can write their result as data and fail a CI job when the audit finds issues.

| Option | Effect |
| :--- | :--- |
| `--json FILE` | Write the whole run as one JSON document (site health, issues, page ranking, proposed links) |
| `--csv DIR` | Write `issues.csv`, `pages.csv` and `links.csv` into `DIR` (a `crawl` run only has issues) |
| `--fail-on error` | Exit with status **1** when the audit found any `error` issue |
| `--fail-on warning` | Exit with status **1** when the audit found any `error` or `warning` issue |

Exit statuses: `0` success, `1` the `--fail-on` quality gate failed, `2` a bad configuration or missing file.
The exports are written before the gate is evaluated, so the files exist even when the command fails.
Severities are listed per check in [CRAWLER.md](CRAWLER.md#site-audit-checks); notices never fail the build.

```bash
# Typical CI step: crawl the site, keep the report as a build artefact, fail on errors
python -m src.cli crawl --url https://example.com/ --json build/audit.json --fail-on error
```

The JSON document (UTF-8, `schema: seo-magus/audit`, `schema_version: 1`) looks like this:

```json
{
  "schema": "seo-magus/audit",
  "schema_version": 1,
  "generated_at": "2026-01-31T10:24:05Z",
  "site": { "key": "audit", "name": "https://example.com/", "url": "https://example.com/" },
  "site_audit": {
    "start_url": "https://example.com/", "max_click_depth": 3, "health": 0.8,
    "pages": 10, "healthy_pages": 8, "unhealthy_pages": 2, "non_indexable_pages": 1, "issues": 3,
    "counts_by_severity": { "error": 1, "warning": 1, "notice": 1 },
    "counts_by_code": { "orphan_page": 1, "deep_page": 1, "missing_meta_description": 1 }
  },
  "optimization": { "links_proposed": 12, "classifier": "heuristic", "classifier_calls": 90, "…": "…" },
  "issues": [
    { "severity": "error", "code": "orphan_page", "url": "https://example.com/blog/post/",
      "detail": "no internal page links here (only reachable via the sitemap)",
      "affected_pages": ["https://example.com/blog/post/"] }
  ],
  "pages": [ { "rank_after": 1, "url": "https://example.com/guides/x/", "pagerank_after": 0.23, "…": "…" } ],
  "links": [ { "source_url": "…", "target_url": "…", "anchor_text": "…", "updated_sentence": "…" } ]
}
```

`site_audit` is `null` and `issues` empty only when nothing was crawled (the demo site includes a site audit); `optimization`, `pages`
and `links` are empty for `crawl`, which makes no classifier calls. The same rows are written by `--csv`
(`issues.csv`, `pages.csv`, `links.csv`; list cells such as `affected_pages` are space separated).
The exporters are also importable: `from src.reporting import export_document, write_json, write_csv, failing_issues`.

### Crawler options (`crawl` and `audit`)

They override the `crawler` section of the config (see [CRAWLER.md](CRAWLER.md)).

| Option | Effect |
| :--- | :--- |
| `--sitemap URL` | Sitemap to read (default: `Sitemap:` lines of robots.txt, else `/sitemap.xml`) |
| `--max-pages N` | Maximum HTML pages (default 500) |
| `--max-depth N` | Maximum link-following depth from the start page (sitemap URLs are still crawled) |
| `--concurrency N` | Parallel requests (default 4) |
| `--delay SECONDS` | Minimum time between requests (robots.txt `Crawl-delay` wins if larger) |
| `--include REGEX` / `--exclude REGEX` | Only crawl / skip URL paths matching the regex (repeatable) |
| `--check-external` | Also request external link targets to report broken outbound links |
| `--ignore-robots` | Ignore robots.txt – only for sites you own |
| `--save-crawl FILE` | Save the crawl as JSON (re-audit later with `audit --from-crawl FILE`) |

### `benchmark` – benchmark sites and sanity checks

```bash
python -m src.cli benchmark [--site all|reference|greenleaf-good|greenleaf-scrambled|mailchimp|...] [--html DIR] [--top N]
```
Runs each benchmark site with its own config (`config/sites/*.yaml`) and prints whether the expected links were
found, why missing ones were refused, the site health of crawled sites and the ranking. See [BENCHMARKS.md](BENCHMARKS.md).

### `boost-page2` – SERP page 2 opportunities

```bash
python -m src.cli boost-page2 [--config FILE] [--min-pos 11] [--max-pos 20] [--min-impressions 50]
```
Lists queries ranking on positions 11–20 with enough impressions. Currently runs on the built-in sample Search
Console dataset (importing your own export is not implemented yet).

| Option | Effect |
| :--- | :--- |
| `--min-pos`, `--max-pos` | SERP window (default 11–20, or `thresholds.page2_*_position`) |
| `--min-impressions` | minimum impressions (default 50, or `thresholds.min_impressions`) |
| `--config FILE` | site config whose `thresholds` are used |

### `serve-mock` – serve a mock site locally

```bash
python -m src.cli serve-mock greenleaf-scrambled --port 8000     # then open http://127.0.0.1:8000/
```
Serves one of the mock sites in `mock_sites/` (`greenleaf-good` or `greenleaf-scrambled`) so you can browse it or
crawl it with `audit --url`. `--port PORT` chooses the port (default 8000).

### Make shortcuts

| Target | Equivalent |
| :--- | :--- |
| `make audit-mock [MOCK_SITE=greenleaf-good]` | serve a mock site and run `audit --url` on it, HTML in `build/audit-<site>/` |
| `make serve-mock [MOCK_SITE=...] [PORT=8000]` | `serve-mock` |
| `make benchmark [SITE=...] [LOG_LEVEL=INFO]` | `benchmark` |
| `make benchmark-report` | `benchmark --html build/benchmark-report` |

Developer targets (test tiers, coverage, fixtures) are described in
[CONTRIBUTING.md](../CONTRIBUTING.md#what-to-run-when), the quality evaluation at scale (`make eval`, Wikipedia, Internet
Archive, Stack Exchange) in [EVALUATION.md](EVALUATION.md); `make help` lists everything by context.

---

## Typical workflows

**First look at a site (free):**
```bash
python -m src.cli crawl --url https://example.com/ --save-crawl build/crawl.json
```

**Full audit with link proposals, re-using that crawl:**
```bash
python -m src.cli audit --from-crawl build/crawl.json --config config/config.yaml --html build/report
```

**Audit in CI (fail the build on regressions):**
```bash
python -m src.cli crawl --url https://example.com/ --json build/audit.json --csv build/audit --fail-on error
# status 1 -> at least one error-severity issue; build/audit.json and build/audit/issues.csv are still written
```
Use `--fail-on warning` for a stricter gate, and keep `build/audit.json` as a build artefact to diff runs
(see [machine-readable output](#machine-readable-output-crawl-and-audit)).

**Large site:** limit the scope and be polite.
```bash
python -m src.cli crawl --url https://example.com/ --max-pages 2000 --exclude '^/tag/' --exclude '^/page/\d+' --delay 0.5
```

**Try a different classifier:** set `classifier.provider` in your config (e.g. `ollama`) – see [CLASSIFIERS.md](CLASSIFIERS.md).

---

## Reading the results

### Terminal

1. **Crawl summary** – pages crawled, URLs requested, broken, redirects, robots.txt blocks.
2. **Site health** – share of indexable pages without errors or warnings, and the issue table
   (all checks are described in [CRAWLER.md](CRAWLER.md#site-audit-checks)).
3. **Proposed links** – `source -> target [anchor]`, the classifier score and confidence, which classifier judged it,
   and the rewritten sentence with the link in Markdown.
4. **Ranking** – pages by internal PageRank after applying the proposals:
   `chg` places gained, `hub` CheiRank, `depth` clicks from the nearest pillar, `in` contextual inbound links
   before->after, flags (`page2`, `orphan`, `noindex`, `uncrawled`).

### HTML report (`--html DIR`)

A self-contained page (no external assets) with:

* **Summary cards** and **site health** (issue list).
* **Semantic map** – one lane per topic cluster, pages ordered best-first; circle size = internal PageRank,
  colour = role, new links in orange, page 2 pages ringed, orphans dashed. Hover a page for all its metrics.
* **Ranking leaderboard** – PageRank before/after, rank change, CheiRank, pillar-weighted PageRank, click depth,
  inbound links, Search Console query and position.
* **Authorities and hubs** – PageRank × CheiRank plane.
* **Approved links** – the rewritten sentences with the anchor highlighted.
* **Decision funnel** – where each candidate source → target pair stopped (cluster boundary, role rule,
  classifier gate, no anchor, not indexable...).

"Ranks best" means **internal link equity** (PageRank of your own link graph), not Google rankings; the Search
Console column shows real positions next to it when available.

### JSON / CSV (`--json FILE`, `--csv DIR`)

The same run as data for dashboards, spreadsheets and CI: `issues` (severity, code, url, detail, affected pages),
`pages` (the ranking leaderboard, one row per page) and `links` (the proposed links with their rewritten sentence),
plus the site health and run counters. The shape is described in
[machine-readable output](#machine-readable-output-crawl-and-audit).

---

## Logging

```bash
python -m src.cli -v audit --url https://example.com/          # milestones
python -m src.cli -vv --log-file build/run.log audit --url ...  # every fetch, classifier call and decision
```

| Level | You see |
| :--- | :--- |
| `WARNING` (default) | degraded operation: provider fallbacks, unusable config, unreachable sitemaps, truncated crawls |
| `INFO` | config in effect, crawl progress and summary, site audit summary, link search progress (about every 10% of the pages), run summary |
| `DEBUG` | every HTTP fetch and redirect, each classifier answer, each pair decision and anchor choice, each approved link |

All loggers live under `seo_magus.*`; Python warnings (e.g. taxonomy entries matching no page) go to the same stream.
When `SEO_MAGUS_RUN_ID` is set - every `make` step sets it - the first line names it
(`Command: audit (make run <id>)`), so the logs of one run can be followed across commands and log files; `make` targets log at INFO by default (`LOG_LEVEL=...` to change it) and
keep every step's output in `build/logs/` (`make logs`, see [CONTRIBUTING.md](../CONTRIBUTING.md#logs-of-make-runs)).

---

## Terminal output

Output is plain ASCII by default so it renders correctly in every terminal, Windows console and log file. Tables
follow the terminal width: long cells are truncated with `...` and optional columns are dropped on narrow terminals.
Use `--unicode` for box drawing and `--no-color` (or `NO_COLOR=1`) to disable colours.

---

## FAQ

**Do I need an API key?** No. Without keys, links are judged by an offline heuristic classifier. With
`TYPESAFE_API_KEY` set, TypeSafe Jev is used automatically. Any other provider can be configured.

**Does it change my site?** No. It proposes edits (the rewritten sentences); you apply them.

**How good is it on large, real sites?** That is measured by a separate evaluation against human ground truth
(Wikipedia editors' links, archive collections, forum tags, pageviews) - see [EVALUATION.md](EVALUATION.md), including
what has and has not been established yet. It can also score your own site: `python -m src.evaluation crawl --url ...`.

**Why is a page missing from the crawl?** Check robots.txt blocks and `--include/--exclude` (run with `-vv`), the
`--max-pages` limit, and whether the page is linked or listed in the sitemap. JavaScript-injected links are not seen.

**Why was a link I expected not proposed?** Run with `-vv`: every pair decision is logged with its reason
(cluster boundary, role rule, classifier gate, no descriptive anchor, not indexable, existing link). Pairs where the
source never names the target's topic are refused by the classifier gate's pre-check, before any classifier call (the
detail says "classifier not called") - see [ALGORITHMS.md](ALGORITHMS.md#link-decision-flow-srcworkflowslinking_optimizerpy).
