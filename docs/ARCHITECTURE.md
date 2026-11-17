# SEO-Magus: Autonomous SEO Optimization & Analysis Suite
## Powered by TypeSafe Jev (System One) & Auxiliary Frontier AIs (System Two)

> **About this document.** This is the original design rationale (benchmarks, the cascade idea, Jev primitives).
> The implementation has since evolved: the System 1 classifier is pluggable (Jev is the default, not a requirement –
> [CLASSIFIERS.md](CLASSIFIERS.md)), sites are crawled and audited ([CRAWLER.md](CRAWLER.md)) and the methodology is
> specified in [ALGORITHMS.md](ALGORITHMS.md). The current code layout is in
> [CONTRIBUTING.md](../CONTRIBUTING.md#project-layout).

---

## Executive Summary & Background

This architecture specification is derived from real-world performance benchmarks and production SEO methodologies demonstrated by **Borja (@borjafat)**, **TypeSafe AI**, and the **Distribb** playbook:

* **The Core Discovery:** Rebuilding internal link maps and auditing site structure is primarily a **massive semantic classification and evaluation problem**, not a creative text generation problem.
* **The Cost/Speed Breakthrough:**
  * **Traditional Frontier LLMs (e.g., Claude Opus / GPT-4o):** Sequential processing burned ~\$43 and multiple hours to evaluate 586 pages (processing only ~21 pages in 45s at \$1.43).
  * **TypeSafe Jev (System 1):** Processed all **586 pages in 45.1 seconds**, performing **8,790 semantic decisions** (linking 584 pages and rejecting 139 unfit candidates) at a total cost of **\$0.21** (~190x-200x cost reduction).
* **The Paradigm:** Implement a **Cascade Hybrid Architecture**:
  1. **Jev (TypeSafe System 1):** Fast (70–500ms), low-cost parallel triage, semantic filtering, link qualification, and ranking.
  2. **Auxiliary Frontier LLMs (System 2 - Claude/Gemini/GPT):** Targeted contextual rewriting, anchor phrase insertion into copy, and strategic pillar/intent synthesis.

---

## Part 1: Scraped Knowledge Base & Insights

### 1.1 Source Tweet Analysis (@borjafat)
* **Status URL:** `https://x.com/borjafat/status/seo-linking-benchmark`
* **Benchmark Details:**
  * **Dataset:** 586 published website pages.
  * **Execution Time:** 45.1 seconds.
  * **Operations:** 8,790 discrete classification checks (`Noul` yes/no decisions):
    * Does Source Page $A$ have a genuine contextual justification to link to Target Page $B$?
    * Is there relevant, natural anchor text/concepts present in $A$'s existing body copy?
  * **Output:** 584 contextual links mapped; 139 pages explicitly rejected (no artificial/spammy links injected).
  * **Economics:** \$0.21 total cost with Jev vs. \$43 projected with Claude Opus 5.

### 1.2 Referenced Playbook: "8 Internal Linking Hacks to Improve SEO"
* **Article URL:** `https://x.com/borjafat/article/internal-linking-hacks`
* **8 Core Stages:**
  1. **Search Console Intelligence Ingestion:**
     * Connect to Google Search Console API (last 3 months, web search, country/device filtered).
     * Extract Page Clicks, Impressions, CTR, and Average Position.
     * Extract page-query mappings; track 28-day delta trends to catch declining visibility.
  2. **Topic Grouping & Search Intent Clustering:**
     * Group pages not merely by broad keyword tokens, but by the **underlying user question** and **task to be completed**.
  3. **Pillar Identification:**
     * Designate comprehensive guides as Pillar Content for each topical cluster.
  4. **Money Page Mapping:**
     * Identify commercial conversion pages (software signup, demo, pricing, service inquiry) and associate each topic group with its natural commercial destination.
  5. **Support Post Structuring & Link Topology:**
     * Strict link matrix rules:
       * `Support Posts ↔ Support Posts` (lateral task continuation)
       * `Support Posts → Pillar Content` (escalating to broad authority)
       * `Support Posts → Money Pages` (contextual conversion)
       * `Pillar Content ↔ Pillar Content` (cross-domain hub links)
       * `Pillar Content → Money Pages` (direct conversion funnel)
       * `Money Pages ↔ Money Pages` (comparison / bundle links)
  6. **SERP Page 2 Opportunity Booster (Positions 11–20):**
     * Filter queries with high impressions lingering in positions 11.0 to 20.0.
     * Prioritize pumping internal PageRank from established pages to these borderline rankers.
  7. **Global Navigation & Footer Architecture:**
     * Programmatically audit and enforce consistent site-wide links to core Pillar Guides and Money Pages via footers/header modules.
  8. **Contextual Anchor Text Diversity:**
     * Eliminate robotic, repetitive exact-match anchor text. Use descriptive phrases tailored directly to the sentence and reader promise.

---

## Part 2: System Architecture & The "Cascade" Engine

```
                             +-------------------------------+
                             |    Input Data / Connectors    |
                             |  - Google Search Console API  |
                             |  - Headless Web Scraper (CMS) |
                             |  - Current Internal Link Graph|
                             +---------------+---------------+
                                             |
                                             v
                      +---------------------------------------------+
                      |   Phase 1: Ingestion & Vector / Pre-Filter  |
                      |   - Content normalization & chunking        |
                      |   - Top-K Candidate Generation via Cosine   |
                      +----------------------+----------------------+
                                             |
                                             v
                      +---------------------------------------------+
                      |      Phase 2: JEV SYSTEM ONE DECISION RUN   |
                      |          (api.typesafe.ai/v1/systemone)     |
                      |                                             |
                      |   1. Choice: Intent & Cluster Tagging       |
                      |   2. Score: Relevance / Authority Quality   |
                      |   3. Noul: Binary Link Qualification        |
                      |            (Evaluates 10k pairs in seconds) |
                      +----------------------+----------------------+
                                             |
                                             | Qualified Candidates
                                             v
                      +---------------------------------------------+
                      |  Phase 3: AUXILIARY FRONTIER AI (System 2)  |
                      |       (Gemini 1.5/2.5 / Claude / GPT)       |
                      |                                             |
                      |   - Sentence extraction & natural insertion |
                      |   - Anchor text variation generation        |
                      |   - Content gap analysis & pillar synthesis |
                      +----------------------+----------------------+
                                             |
                                             v
                      +---------------------------------------------+
                      |  Phase 4: Verification, CMS Sync & Tracking |
                      |   - Graph cycles & orphan page checks       |
                      |   - Headless CMS / Git PR / WP REST API     |
                      |   - 28-day SERP delta impact monitoring     |
                      +---------------------------------------------+
```

---

## Part 3: Deep Dive into Jev Decision Primitives

TypeSafe Jev does not return freeform markdown or chat streams. It evaluates parallel structured questions against given state in ~100ms.

### 1. `Noul` (Probabilistic Binary Judgments)
Used for the 8,790+ pair-wise qualification matrix:
* **Question:** `"Does Source Page content provide an immediate educational or contextual reason for the reader to navigate to Target Page about [Target Topic]?"`
* **Question:** `"Is there a natural transition point in Source Paragraph without disrupting reader flow?"`
* **Output:** `Boolean` + `Confidence Probability` (e.g., `0.94`).

### 2. `Score` (Multi-Level Quality Ranking)
Used for SERP Page 2 prioritization and link urgency:
* **Question:** `"On a scale of 1-10, score the commercial and topical relevance between Source Page and Target Money Page."`
* **Output:** Float (e.g., `8.7 / 10`).

### 3. `Choice` (Categorical Clustering)
Used for high-speed categorization of hundreds of blog posts into clusters without running full token-heavy prompts:
* **Question:** `"Which of the following 12 Pillar Categories does this article primarily belong to?"`
* **Options:** `['Email Marketing', 'Domain Authentication', 'Lead Generation', ...]`
* **Output:** Exact category match.

---

## Part 4: Role of Auxiliary Frontier AIs (System 2)

While Jev handles the high-volume decision graph, Auxiliary Frontier AIs (Gemini / Claude / GPT) are reserved for tasks requiring creative prose and syntactical finesse:

1. **Contextual Anchor Insertion:**
   * Given the sentence identified by Jev, rewrite the sentence or wrap the existing phrase naturally:
   * *Before:* "To get high delivery rates, verify your DNS records."
   * *After:* "To get high delivery rates, follow our guide on [authenticating a sending domain](https://...) before launching your campaign."
2. **Anchor Variation Generation:**
   * Ensuring the target page receives distinct, natural anchor phrases (e.g., "welcome email series", "sequence setup tutorial", "plan automated follow-ups") rather than repetitive exact matches.
3. **Pillar Content Gap Analysis:**
   * Identifying orphan clusters that lack an authoritative pillar guide.

---

## Part 5: Modular Suite Specification & Directory Layout

The implemented layout is documented in [CONTRIBUTING.md](../CONTRIBUTING.md#project-layout). Mapping from the
original plan:

| Planned module | Status |
| :--- | :--- |
| `connectors/gsc_connector.py` | implemented (sample dataset; importing exports is open) |
| `connectors/sitemap_crawler.py` | implemented as a full crawler (`connectors/crawling/`) |
| `connectors/cms_writer.py` | open (Hacktoberfest issues #1 WordPress, #3 Ghost) |
| `engines/jev_client.py` | implemented; one provider of `engines/classifiers/` |
| `engines/candidate_finder.py` | implemented inside `workflows/linking_optimizer.py` (cluster affinities) |
| `engines/link_graph.py` | implemented (PageRank, CheiRank, pillar-weighted PageRank) |
| `engines/auxiliary_ai.py` | implemented (offline anchor engine; LLM rewriting is open) |
| `workflows/audit_pipeline.py` | implemented as `workflows/site_audit.py` + `cli.py audit` |
| `workflows/page2_booster.py` | implemented as Search Console steering in the optimizer + `cli.py boost-page2` |
| `config/rules.json` | replaced by `config/sites/<site>.yaml` (taxonomy, link rules) |

---

## Part 6: Execution Playbook & Step-by-Step Implementation Plan

1. **Step 1: Configuration & Ingestion**
   * Authenticate GSC Service Account (`GOOGLE_APPLICATION_CREDENTIALS`).
   * Crawl target site sitemap (extract URL, Title, H1, Meta, Body text, existing hrefs).
2. **Step 2: Candidate Generation (Pre-filtering)**
   * Generate candidate source-destination pairs $(A, B)$ where $A \neq B$ and no existing link exists.
   * Filter pairs by topical cosine similarity or category heuristics to avoid $N^2$ explosion on 10,000+ page sites.
3. **Step 3: Jev High-Speed Evaluation**
   * Dispatch batches to `api.typesafe.ai/v1/systemone` using `Noul` and `Score` questions.
   * Accept pairs with `confidence >= 0.85` and `score >= 7.0`.
4. **Step 4: Auxiliary AI Copy Insertion**
   * For accepted pairs, send Source paragraph + Destination summary to Auxiliary LLM to produce exact sentence replacement diff.
5. **Step 5: Output Generation & Review**
   * Generate actionable CSV/JSON audit report and diff preview for webmaster approval or automated CMS push.
