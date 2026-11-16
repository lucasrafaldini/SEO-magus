# Crawler & Site Audit

## Crawler

`python -m src.cli crawl --url https://example.com/` (or `audit --url`) crawls a live site with the standard library
only – no browser, no third-party HTTP client. Settings: the `crawler` section of the config
([CONFIGURATION.md](CONFIGURATION.md#crawler)) or the command-line flags ([USER_GUIDE.md](USER_GUIDE.md#crawler-options-crawl-and-audit)).

### What it does

1. **robots.txt** – reads the rules for its User-Agent, `Crawl-delay` and `Sitemap:` declarations. Disallowed URLs
   are never requested (reported as blocked).
2. **Sitemaps** – the declared sitemaps (or `/sitemap.xml`), including sitemap indexes and gzipped `.xml.gz` files.
3. **Breadth-first discovery from the start page** – level by level, so every page gets its true click depth. Every
   internal link target is requested (content and navigation links), so broken links and redirects are known.
4. **Sitemap-only pages** – sitemap URLs not reachable by links are crawled afterwards (their click depth is unknown:
   the audit reports them as orphan or unreachable).
5. **Optional external check** – with `check_external`, external link targets are requested (HEAD, then GET) to find
   broken outbound links. Otherwise external URLs are never requested.

### Behaviour details

| Topic | Behaviour |
| :--- | :--- |
| Politeness | one shared rate limiter: `delay` or robots.txt `Crawl-delay`, whichever is larger; honest User-Agent |
| Concurrency | `concurrency` parallel requests per level; results are processed in discovery order, so the output is identical for any concurrency |
| Retries | HTTP 429/5xx, timeouts and connection errors are retried (`retries`, exponential backoff, `Retry-After` up to 10 s) |
| Redirects | followed hop by hop and recorded (chains, loops); redirects leaving the site are recorded, not followed |
| URL normalization | lower-case scheme/host, default ports dropped, `#fragments` removed, tracking parameters (`utm_*`, `gclid`, `fbclid`, ...) removed, `<base href>` honoured |
| Content | `gzip`/`deflate` decoded; charset from the HTTP header or `<meta charset>`; non-HTML bodies (PDF, images) are never downloaded; HTML over `max_page_bytes` is truncated |
| Scope | same host (optionally subdomains), `include`/`exclude` regexes on the path, `max_depth`, `max_pages` |
| Indexability | meta robots, `X-Robots-Tag`, `rel=canonical`: noindex pages and canonicalized duplicates are audited but never get link proposals |
| Extraction | title, meta description, meta robots, canonical, `lang`, every `<h1>`, body paragraphs (navigation/header/footer/aside excluded), every link with anchor text, location (content or navigation) and `rel=nofollow` |
| Persistence | `--save-crawl FILE` writes the whole crawl as JSON; `audit --from-crawl FILE` re-audits it without network access |

### Limits

* No JavaScript rendering: links and text injected client-side are not seen.
* One host per crawl (plus subdomains with `allow_subdomains`).
* Crawl state is kept in memory; `max_pages` in the low thousands is the intended range.

---

## Site audit checks

Every crawl is audited. On-page and structural checks only apply to **indexable** pages (HTTP 200, no noindex,
canonical to themselves): noindex pages and canonicalized duplicates are not expected to rank. **Site health** is the
share of indexable pages affected by no error or warning. Click depth is measured from the start page over every
internal link.

| Check | Severity | Meaning |
| :--- | :--- | :--- |
| `orphan_page` | error | no internal page links to it (only reachable through the sitemap) |
| `broken_internal_link` | error | an internal link answers 4xx/5xx or fails (reported once per target, with the linking pages) |
| `sitemap_url_broken` | error | a sitemap URL answers 4xx/5xx |
| `missing_title` | error | empty or missing `<title>` |
| `redirect_loop` | error | a URL redirects back onto itself |
| `canonical_broken` | error | the canonical URL of a page is broken |
| `duplicate_title` | warning | several indexable pages share the same `<title>` |
| `missing_h1` | warning | no `<h1>` |
| `multiple_h1` | warning | more than one `<h1>` |
| `generic_anchor` | warning | a contextual link uses a generic anchor ("click here", "read more", "saiba mais"...) |
| `redirected_internal_link` | warning | an internal link points at a URL that redirects |
| `redirect_chain` | warning | a URL needs two or more redirects to reach its final page |
| `deep_page` | warning | more than `max_click_depth` clicks from the start page |
| `unreachable_page` | warning | linked from somewhere, but not reachable from the start page by following links |
| `not_in_sitemap` | warning | crawled page missing from the XML sitemap |
| `no_contextual_inbound` | warning | only linked from navigation (header, nav, footer), never from content |
| `noindex_in_sitemap` | warning | a noindex page is listed in the sitemap |
| `sitemap_url_redirect` | warning | the sitemap lists a URL that redirects (it should list final URLs) |
| `broken_external_link` | warning | an outbound link is broken (only with `check_external`) |
| `missing_meta_description` | notice | no meta description |
| `canonicalized_page` | notice | the page declares another URL as canonical (it is a duplicate) |
| `nofollow_internal_link` | notice | an internal link carries `rel=nofollow` |
| `slow_page` | notice | the response took longer than `slow_page_ms` |

The ground truth for these checks is the pair of mock sites in `mock_sites/` (see [BENCHMARKS.md](BENCHMARKS.md#mock-sites)):
the good site must have none of them, the scrambled site exactly its planted ones.
