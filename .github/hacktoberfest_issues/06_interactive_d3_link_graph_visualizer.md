# Issue 6: Interactive Force-Directed Link Graph Visualizer (D3.js / HTML Export)

**Labels:** `hacktoberfest`, `feature`, `visualization`, `ui`  
**Difficulty:** Intermediate  

---

### Description
SEO site architecture is inherently visual. Being able to see how internal links flow between Pillars, Support Posts, and Money Pages provides immense value to webmasters and digital marketers.

We want to add a feature that exports an interactive, standalone HTML file displaying the site's link graph using **D3.js Force-Directed Graph**.

### Requirements
1. **CLI Flag:** Add `--visualize` / `--export-html` to `python3 -m src.cli audit`.
2. **Interactive Standalone HTML:**
   - Single-file export (e.g. `reports/link_graph.html`).
   - Color nodes by page role:
     - 🟢 **Pillars:** Green
     - 🟡 **Money Pages:** Gold / Orange
     - 🔵 **Support Posts:** Blue
     - 🔴 **Orphan Pages:** Red
   - Node size proportional to computed PageRank.
   - Animated edges representing approved new internal links.
   - Hover tooltips showing URL, in-degree, out-degree, and topical cluster.
3. **No External Build Step:** Embedded SVG / D3.js script via CDN or standalone bundle.

### How to Get Started
- Look at `src/engines/link_graph.py` and `src/workflows/linking_optimizer.py`.
- D3.js force-directed graph examples: https://d3js.org/d3-force
