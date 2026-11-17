# Benchmarks & Sanity Checks

How do we know SEO-Magus is right? Real sites cannot tell us the correct output (nobody knows their "true" link
plan and rankings change daily), so the project is checked against references whose answers are known.

These benchmarks are small on purpose: every expected link is written down, so they catch any change of behaviour
exactly. They say nothing about quality at scale or on real-world content; that is measured separately, against
Wikipedia, the Internet Archive, Stack Exchange, crawled sites and large synthetic corpora, with the methodology in
[EVALUATION.md](EVALUATION.md).

## Running the benchmarks

There are two ways to run them: **look** at the results through the real CLI, or **assert** them as tests.

```bash
# Look: the tool's own output for every benchmark site (SITE=<key> for one, LOG_LEVEL=INFO|DEBUG for the why)
make benchmark                 # terminal: verdict, site health and ranking for every benchmark site
make benchmark-report          # HTML: build/benchmark-report/index.html
make benchmark SITE=stripe LOG_LEVEL=DEBUG

# Assert: the benchmark test tier (pytest marker `benchmark`, ~5 s)
make test-benchmarks           # every site: invariants, expected links, known gaps, audit ground truth
make test-reference            # only the ground-truth references
make test-mock-sites           # only the crawled mock sites (crawler, audit, links, saved crawls)
```

Run `make test-benchmarks` after any change to link decisions, anchors, ranking or audit checks: it is the tier that
catches a quality regression even when every unit test still passes. It is part of `make test` and `make ci`; the
other tiers (unit, integration) are described in [CONTRIBUTING.md](../CONTRIBUTING.md#test-tiers).

## Benchmark sites

Every benchmark is an ordinary site run through the normal flow with its own config in `config/sites/`.

| Key | Pages | What it checks | Expected results come from |
| :--- | :--- | :--- | :--- |
| `reference` | fixture (`src/benchmarks/reference.py`) | the whole link flow | ground truth by construction – **exhaustive** |
| `greenleaf-good` | crawled over HTTP (`mock_sites/`) | crawler + audit + links on a well-optimized site | ground truth: 0 issues, 0 new links – **exhaustive** |
| `greenleaf-scrambled` | crawled over HTTP (`mock_sites/`) | crawler + audit + links on a broken site | ground truth: exactly its planted issues and links – **exhaustive** |
| `mailchimp`, `stripe`, `shopify`, `github` | fixture (`src/benchmarks/famous_sites.py`) | pillar → support → money topologies | key links of each topology |
| `canivete` | fixture | Portuguese tools site, 4 clusters with affinities | links approved in [its case study](../reports/canivete_cc_audit_report.md) |
| `zazazine` | fixture | Portuguese magazine, 3 editorial clusters | links approved in [its case study](../reports/zazazine_audit_report.md) |

For **exhaustive** benchmarks any link outside the expectations is a false positive, so precision and recall are
both measured. For the others only recall is meaningful.

### Known gaps

Expected links the flow does not produce are recorded as *known gaps* with the rule that refuses them
(`known_gaps` in `src/benchmarks/__init__.py`). Tests assert them exactly: a fix and a regression both fail until the
record is updated. Today: `stripe` and `shopify`, whose source articles never mention the target page, so no
contextual link is possible (a correct refusal by the classifier gate's pre-check; the fixture text does not support the
expected link).

## Reference site (`reference`)

A fictional invoicing/payroll SaaS whose correct output was written before running the flow:

* 7 expected links, each with the anchor that names the target and the paragraph that names it best;
* 5 traps, each topically tempting but blocked by exactly one rule (cluster boundary, one-way affinity, money →
  support rule, existing link, a single shared word that cannot make an anchor) – the test checks the *reason*
  of each refusal;
* SERP page 2 rows on the exact window boundaries, pillar click depths and the only expected orphan.

The ranking math is pinned to an external result: Wikipedia's PageRank example graph (nodes A–K) must reproduce
its published scores (A 3.3 %, B 38.4 %, C 34.3 %, ...) on both graph backends.

## Mock sites

`mock_sites/` contains two versions of the same fictional site (GreenLeaf Gardening, production host
`https://greenleaf.example`), served over real HTTP on localhost and scanned by the real crawler:

| | `greenleaf-good` | `greenleaf-scrambled` |
| :--- | :--- | :--- |
| Content | same articles | same articles |
| Links | descriptive contextual links, hub and spoke | most links removed, "click here", broken and redirecting links |
| Structure | every page ≤ 2 clicks from home | orphan page, pillar 4 clicks deep, pages unreachable from home |
| Sitemap | complete | a 404 entry, a redirecting entry (2-hop chain), a noindex page, a page missing |
| On-page | unique titles, one H1, meta descriptions | missing/duplicate titles, missing/multiple H1s, missing meta descriptions |
| Other | canonical to self | canonicalized print duplicate, nofollow and utm-tagged internal links |
| Parser traps | – | upper-case tags, unclosed `<p>`, H1 inside `<header>`, `#fragments`, external links, robots.txt-blocked page |

Expected results (`src/benchmarks/mock_sites.py`):

* **scan** – title, H1s, meta description, paragraphs, content and navigation links of every page;
* **audit** – good site: no issue; scrambled site: exactly its 26 issues (4 errors, 16 warnings, 6 notices);
* **links** – good site: no new link; scrambled site: exactly the 16 contextual links of the good site that it lacks,
  i.e. SEO-Magus rebuilds the good site's link structure from the scrambled one;
* **crawler behaviour** – the robots.txt-blocked page and external URLs are never requested, responses are gzipped.

Browse or audit them yourself: `make serve-mock MOCK_SITE=greenleaf-good`, `make audit-mock`.

Unit tests use **saved crawls** of both sites (`tests/fixtures/*.crawl.json`) so they get the same pages without
starting a server. After changing a mock site (or the crawler) run `make fixtures`; the integration tier fails while a
saved crawl differs from a live crawl.

## Adding a benchmark site

1. Add the pages: a module in `src/benchmarks/` returning `ParsedPage`s, or a new directory in `mock_sites/` served
   and crawled over HTTP (`build_crawl`).
2. Add `config/sites/<key>.yaml` (thresholds, taxonomy, link rules, classifier).
3. Register a `BenchmarkSite` in `src/benchmarks/__init__.py` with its expected links and where they come from.
4. Run `make test-benchmarks`: every site must satisfy the invariants (descriptive anchors, cluster and role rules,
   thresholds, no nested or duplicate links) and missing expected links must be recorded as known gaps.
