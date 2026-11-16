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

Plus the [crawler options](#crawler-options-crawl-and-audit).

### `audit` – crawl + site audit + link proposals + ranking

```bash
python -m src.cli audit --url https://example.com/ --config config/config.yaml --html build/report
python -m src.cli audit --from-crawl build/crawl.json --config config/config.yaml
python -m src.cli audit                                   # demo dataset, no network
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

---

## Logging

```bash
python -m src.cli -v audit --url https://example.com/          # milestones
python -m src.cli -vv --log-file build/run.log audit --url ...  # every fetch, classifier call and decision
```

| Level | You see |
| :--- | :--- |
| `WARNING` (default) | degraded operation: provider fallbacks, unusable config, unreachable sitemaps, truncated crawls |
| `INFO` | config in effect, crawl progress and summary, site audit summary, each approved link, run summary |
| `DEBUG` | every HTTP fetch and redirect, each classifier answer, each pair decision and anchor choice |

All loggers live under `seo_magus.*`; Python warnings (e.g. taxonomy entries matching no page) go to the same stream.

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

**Why is a page missing from the crawl?** Check robots.txt blocks and `--include/--exclude` (run with `-vv`), the
`--max-pages` limit, and whether the page is linked or listed in the sitemap. JavaScript-injected links are not seen.

**Why was a link I expected not proposed?** Run with `-vv`: every pair decision is logged with its reason
(cluster boundary, role rule, classifier gate, no descriptive anchor, not indexable, existing link).
