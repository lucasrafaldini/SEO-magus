# Issue 4: Weighted Internal PageRank with Click-Depth & CheiRank

**Labels:** `hacktoberfest`, `algorithm`, `core-engine`  
**Difficulty:** Intermediate / Advanced  

---

### Description
In `src/engines/link_graph.py`, `LinkGraph.compute_pagerank()` currently implements standard PageRank where each outgoing link transmits equal equity.

In actual search engine algorithms (and Google's Random Surfer / Reasonable Surfer models), click-depth from the homepage and link placement within the DOM heavily influence the amount of crawl equity passed.

### Requirements
1. **Click-Depth Calculation:**
   - Compute shortest-path distance (BFS) from the root homepage (`/`) to every node.
   - Apply a damping penalty based on click depth (e.g. pages > 3 clicks deep pass less equity).
2. **Contextual In-Body Weighting:**
   - Differentiate links found within `<main>` or `<article>` body copy vs footer/sidebar navigation.
   - Body links should carry a higher edge weight ($w = 1.0$) compared to repetitive footer links ($w = 0.2$).
3. **CheiRank (Outdegree Inversion):**
   - Implement CheiRank computation to measure communicative power and identify link hubs vs dead-end sinks.
4. **Unit Tests:** Add tests in `tests/test_link_graph.py` verifying that pages closer to the homepage with prominent body links receive higher simulated equity.

### How to Get Started
- Inspect `src/engines/link_graph.py`.
- Check NetworkX documentation or pure-Python implementation already present in the file.
