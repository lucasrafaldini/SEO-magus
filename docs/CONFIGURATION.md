# Configuration

A site config is a YAML file passed with `--config` (start from
[`config/config.example.yaml`](../config/config.example.yaml); complete real examples live in
[`config/sites/`](../config/sites/)). Every section and key is optional.

* **Precedence:** command-line flag > config file > built-in default.
* **Strict:** unknown keys inside a section raise an error, so a typo never silently falls back to a default.
  Unknown top-level sections are reported with a warning.
* **Secrets:** API keys are never read from the config file, only from environment variables.

| Section | Controls |
| :--- | :--- |
| [`crawler`](#crawler) | how sites are crawled |
| [`thresholds`](#thresholds) | classifier gate, anchor quality, SERP page 2 window, audit limits |
| [`taxonomy`](#taxonomy) | page roles (pillar / money / support) and topic clusters |
| [`link_rules`](#link_rules) | linking policy |
| [`classifier`](#classifier) | the model that judges candidate links |
| `site` | informational only (not used by the code yet) |

---

## `crawler`

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `max_pages` | `500` | HTML pages to crawl at most |
| `max_depth` | `null` | link-following depth from the start page (`null` = unlimited); sitemap URLs are still crawled |
| `concurrency` | `4` | parallel requests |
| `delay` | `0.0` | minimum seconds between requests; robots.txt `Crawl-delay` wins if larger |
| `timeout` | `10` | seconds per request |
| `retries` | `2` | retries on HTTP 429/5xx and network errors (exponential backoff, `Retry-After` honoured) |
| `respect_robots` | `true` | obey robots.txt (`--ignore-robots` only for sites you own) |
| `follow_nofollow` | `true` | also discover pages through `rel=nofollow` links and meta nofollow pages |
| `allow_subdomains` | `false` | treat `blog.example.com` as part of `example.com` |
| `include` | `[]` | regexes on the URL path (+query): if set, only matching URLs are crawled |
| `exclude` | `[]` | regexes on the URL path (+query): matching URLs are skipped |
| `strip_query_params` | tracking params | glob patterns removed from URLs (`utm_*`, `gclid`, `fbclid`, `msclkid`, ...) |
| `check_external` | `false` | request external link targets (HEAD, then GET) to find broken outbound links |
| `max_page_bytes` | `5000000` | larger HTML bodies are truncated |
| `max_redirects` | `10` | redirects followed per URL at most (longer chains are not followed further) |
| `user_agent` | `SEO-Magus/1.0 (+repo URL)` | User-Agent sent with every request and used for robots.txt rules |

## `thresholds`

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `min_confidence` | `0.80` | minimum classifier confidence that a link is legitimate |
| `min_score` | `7.0` | minimum classifier relevance score (1–10) |
| `anchor_min_words` | `2` | minimum distinct topic words in an anchor ("descriptive anchors") |
| `page2_min_position` / `page2_max_position` | `11.0` / `20.0` | SERP page 2 window (inclusive) |
| `min_impressions` | `50` | minimum Search Console impressions for a page 2 opportunity |
| `max_click_depth` | `3` | site audit: pages deeper than this are flagged (`deep_page`) |
| `slow_page_ms` | `2000` | site audit: slower responses are flagged (`slow_page`) |

Legacy names `jev_noul_min_confidence` and `jev_score_min` are still accepted, with a deprecation warning.

## `taxonomy`

Everything site-specific lives here; the engines make no assumption about any site.

```yaml
taxonomy:
  pillars: ["/guides/composting/", "/guides/vegetable-gardening/"]      # exact pages
  money_pages: ["/shop/compost-tumbler/", "https://example.com/pricing"]  # exact pages
  clusters:                                   # cluster -> URL substrings, first match wins
    composting: ["/guides/composting", "/blog/hot-composting", "/shop/compost-tumbler"]
    vegetables: ["/guides/vegetable-gardening", "/blog/raised-bed-soil"]
  cluster_affinities:                         # source cluster -> other clusters it may link to
    general: [composting, vegetables]
    composting: [vegetables]
```

* **Roles.** `pillars` and `money_pages` are URL paths or absolute URLs matched exactly (trailing slash ignored).
  Unlisted pages are `support` pages. Pillars anchor the click-depth weighted PageRank; money pages are subject to
  `link_rules`.
* **Clusters.** Patterns are case-insensitive URL substrings checked in config order; pages matching none are in the
  `general` cluster. A page may link within its own cluster plus the clusters listed in its `cluster_affinities`
  (one-way). Without clusters there is no topic boundary.
* Entries that match no crawled page are reported with a `TaxonomyWarning` (typos, stale config).

## `link_rules`

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `money_to_support` | `forbid` | may money pages link to support posts? `forbid` · `same_cluster` (e.g. tool sites whose calculators lead to related tools) · `allow` |

## `classifier`

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `provider` | `auto` | `auto`, `heuristic`, `jev`, `openai`, `anthropic`, `gemini`, `openrouter`, `groq`, `ollama`, `lmstudio`, `openai_compatible` or `python:package.module:Class` |
| `model` | `""` | model name (required for cloud LLM providers; `ollama` defaults to `llama3.2:3b`) |
| `base_url` | provider default | endpoint override (self-hosted servers, proxies) |
| `api_key_env` | provider default | environment variable holding the API key |
| `timeout` | `30` | seconds per request |
| `fallback` | `heuristic` | when the provider is unusable or a call fails: `heuristic` (logged and counted) or `none` (stop) |
| `cost_per_call_usd` | provider default | used for cost estimates (Jev: 0.000025) |
| `temperature` | `0.0` | sampling temperature for LLM providers |

Details, provider list and the plugin API: [CLASSIFIERS.md](CLASSIFIERS.md).
