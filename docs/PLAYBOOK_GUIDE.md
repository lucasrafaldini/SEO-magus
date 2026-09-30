# The 8-Step Internal Linking Playbook (SEO-Magus Edition)
*Synthesized from Borja (@borjafat) & Distribb internal linking methodology*

---

## Why Internal Linking Over Backlinks / New Content?

* **No New Writing Overhead:** Leverages high-quality assets already published on your domain.
* **Full Control:** You control page content, link placement, anchor text, and deployment velocity.
* **Instant PageRank Redistribution:** Moves equity from high-authority pages directly to converting money pages and high-impression Page 2 candidates.

---

## The 8 Execution Steps

### 1. Check Search Console
* Pull **Web Search** performance for the last **3 months** (fixed country & device filters).
* Ingest:
  * Page-level metrics: Clicks, Impressions, CTR, Average Position.
  * Query-level mappings: Connect each query to its serving URL.
  * Delta comparison: Compare the last 28 days vs. previous 28 days to isolate pages experiencing keyword decay or velocity drop.

### 2. Group Your Topics (Intent Clustering)
* Cluster pages by **the reader's specific question and task**, not generic keywords.
* Example:
  * *Topic A:* "How to write a welcome email" (Email Copywriting group)
  * *Topic B:* "Configuring SPF/DKIM records" (Email Deliverability group)
* Avoid mixing distinct intents even if both contain common words.

### 3. Pick Your Pillars
* Designate one definitive, comprehensive guide per topical cluster.
* Requirements:
  * Answers the broad subject comprehensively.
  * Links to every granular support post within its domain.
  * Receives inbound contextual links from all related support posts.

### 4. Pick Money Pages
* Identify the direct conversion endpoints (Product tours, Pricing, Demo booking, Free trial signup).
* Map each topic cluster to its corresponding commercial endpoint.
* Identify key transactional turning points in informational content where a product recommendation naturally solves the reader's immediate problem.

### 5. Structure Support Posts & Link Rules
Follow the canonical link matrix:
* `Support Post ↔ Support Post`: Horizontal continuation (e.g., from *Welcome Email Template* to *Subject Line Guide*).
* `Support Post → Pillar Guide`: Upward topical authority reinforcement.
* `Support Post → Money Page`: Direct contextual conversion path.
* `Pillar Guide ↔ Pillar Guide`: Cross-topic authority bridging.
* `Pillar Guide → Money Page`: High-intent funnel transition.
* `Money Page ↔ Money Page`: Comparison / cross-sell links.

### 6. Boost Pages Stuck on SERP Page 2 (Positions 11–20)
* Filter Search Console data for pages with strong impression volume averaging **positions 11.0 to 20.0**.
* These URLs already have Google's attention; they only need internal link equity and relevance signals to cross into top 10 positions.
* Direct internal links from established, high-traffic pages specifically targeting these Page 2 keywords.

### 7. Global Navigation & Footer Links
* Use the global footer template to give search bots and users a persistent route to core Pillars and Money Pages.
* Keep anchor text clean and recognizable (e.g., "Email Marketing Software", "Deliverability Guide").

### 8. Contextually Vary Anchor Text
* Match the anchor text to the natural cadence of the surrounding sentence.
* Avoid robotic, repetitive exact-match anchors across all incoming links.
* Let the surrounding sentence provide the promise of what the destination page contains.

---

## The Full Autonomous Agent Prompt Template

```text
Build an internal linking plan for my website. Read my page content, existing internal links, and Search Console data. Tell me which inputs are missing. Group pages by topic and the reader's question. Choose a pillar guide and relevant money pages for each group. Identify support posts and explain the next useful step for someone reading each one. Find pages averaging positions 11 to 20 for relevant queries. Use consistent country, device, search type, and date filters. Find existing articles with useful passages that could link to those pages. Exclude links already present. Propose contextual links between related support posts, from support posts to pillars and money pages, between related pillars, between related money pages, and from pillars to money pages. Assess each direction separately. For each suggestion, return the source URL, destination URL, existing sentence, proposed sentence, anchor text, and the reader's reason to click. Use only real pages you have checked. Suggest a small set of products and guides for the footer. Write descriptive anchors that fit the surrounding sentence. Keep navigation labels consistent. Save the proposed edits together and show me the changes. After applying edits, check that the links work and record each changed page and the date. Compare search performance using the same filters. Repeat the check when new articles are published.
```
