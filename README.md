# 🔮 SEO-Magus

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Crawl a website, find its technical SEO problems and get ready-to-paste internal links that fix its structure.**

SEO-Magus crawls your site, audits it (orphan pages, buried pages, broken links, redirect chains, titles, canonicals…),
then proposes contextual internal links: for every pair of pages a fast classifier decides whether the source paragraph
gives readers a real reason to click, and the exact sentence is rewritten with a descriptive anchor. The result is a
terminal summary and a visual HTML report showing which pages rank best in your internal link graph and why.

> Inspired by **Borja (@borjafat)**, **TypeSafe Jev** and **Distribb**: rebuilding internal link maps is a
> classification and graph problem, not creative writing.

---

## Quick start (5 minutes)

```bash
git clone https://github.com/lucasrafaldini/SEO-magus.git && cd SEO-magus
make install                      # creates ./venv with everything (Python 3.10+)
source venv/bin/activate          # optional: `make` targets use ./venv directly

# 1. Try it offline on the built-in mock site (no API key, no internet)
make audit-mock                   # crawls a deliberately broken site and writes build/audit-greenleaf-scrambled/

# 2. Audit your own site
cp config/config.example.yaml config/config.yaml     # then list your pillar and money pages
python -m src.cli audit --url https://your-site.com/ --config config/config.yaml --html build/report
```

Open `build/report/audit.html`: site health, proposed links with the rewritten sentences, a semantic map of your topic
clusters and a ranking leaderboard. No configuration or API key is required to start; see the
[User Guide](docs/USER_GUIDE.md) for every command.

| Command | What it does |
| :--- | :--- |
| `crawl --url URL` | Crawl + site audit only (fast, free, no classifier calls) |
| `audit --url URL` | Crawl + site audit + link proposals + ranking (`--html DIR` for the visual report) |
| `audit --from-crawl FILE` | Same, on a crawl saved with `--save-crawl` (no network) |
| `crawl/audit --json FILE --fail-on error` | Machine-readable report + CI exit code 1 when errors are found |
| `benchmark` | Run the benchmark sites, including the ground-truth sanity checks |
| `serve-mock SITE` | Serve a mock site on localhost to explore or audit it |

## What you get

* **Crawler** – robots.txt and Crawl-delay, sitemaps (indexes, `.xml.gz`), concurrent and polite, retries, redirect
  chains, canonical/noindex awareness, include/exclude filters, saved crawls. Standard library only. → [Crawler](docs/CRAWLER.md)
* **Site audit** – 23 checks (orphans, click depth, broken/redirected links, redirect chains, titles, H1s, canonicals,
  noindex pages in the sitemap, generic anchors…) with a site health score. → [Crawler](docs/CRAWLER.md#site-audit-checks)
* **Link proposals** – topic clusters and page roles from your config, a pluggable classifier, descriptive non-nested
  anchors, SERP page 2 steering with Search Console data. → [Algorithms](docs/ALGORITHMS.md)
* **No vendor lock-in** – TypeSafe Jev is used when `TYPESAFE_API_KEY` is set; otherwise an offline heuristic. Any
  OpenAI-compatible or Anthropic model, local models (Ollama, LM Studio) or your own Python class can be configured.
  → [Classifiers](docs/CLASSIFIERS.md)
* **Ranking** – internal PageRank, CheiRank (hub pages) and pillar click-depth weighted PageRank, before and after the
  proposed links. → [Algorithms](docs/ALGORITHMS.md)
* **Reports & logs** – ASCII-safe terminal tables, self-contained HTML reports, `-v`/`-vv` logging of every decision.
* **Automation ready** – `--json FILE` / `--csv DIR` export the issues, the page ranking and the proposed links, and
  `--fail-on error|warning` exits with status 1 so a CI job fails on SEO regressions. → [User Guide](docs/USER_GUIDE.md#machine-readable-output-crawl-and-audit)

## Documentation

| I want to… | Read |
| :--- | :--- |
| Use every command, read the reports, follow logs | [User Guide](docs/USER_GUIDE.md) |
| Configure thresholds, roles, clusters, crawler, classifier | [Configuration](docs/CONFIGURATION.md) · [example config](config/config.example.yaml) |
| Understand the crawler and the audit checks | [Crawler & Site Audit](docs/CRAWLER.md) |
| Use another model (OpenAI, Claude, Ollama, my own) | [Classifiers](docs/CLASSIFIERS.md) |
| Understand the ranking and linking methodology | [Algorithms](docs/ALGORITHMS.md) · [Playbook](docs/PLAYBOOK_GUIDE.md) |
| Check that results are correct | [Benchmarks & sanity checks](docs/BENCHMARKS.md) |
| Measure quality at scale (Wikipedia, Internet Archive, Stack Exchange, any site) | [Evaluation methodology](docs/EVALUATION.md) |
| Contribute | [Contributing](CONTRIBUTING.md) · [Architecture & design rationale](docs/ARCHITECTURE.md) |

## Contributing

```bash
make install && make test          # ~370 tests in three tiers (unit, integration, benchmark), offline, ~40 s
make test-unit                     # fast feedback while coding, ~10 s
make ci                            # what CI runs: every tier, both graph backends, coverage gate
make help                          # every target, grouped by context
make logs                          # what the last make runs did: step, duration, result, log file
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the project layout, conventions and step-by-step guides (new audit check,
classifier provider, benchmark site).

## Current limitations

* Quality at scale is measurable (`make eval`, [methodology](docs/EVALUATION.md)) but has only been run on synthetic
  corpora so far: no real-world quality claim is established until the real-source runs are done.

* Pages are not JavaScript-rendered: content injected client-side is invisible to the crawler.
* Search Console data is only used from the built-in sample dataset; importing your own export is not implemented yet.
* Sentence rewriting uses the offline anchor engine; LLM-based rewriting ("System 2") is not implemented yet.

## License

[MIT](LICENSE)
