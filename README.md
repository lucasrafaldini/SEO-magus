# 🔮 SEO-Magus: High-Speed SEO Optimization & Internal Linking Suite

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Hacktoberfest: 2026](https://img.shields.io/badge/Hacktoberfest-2026-orange.svg)](https://hacktoberfest.com/)
[![CI](https://github.com/YOUR_USERNAME/SEO-magus/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/SEO-magus/actions)

> **Rebuilding internal link maps is a semantic classification and graph optimization problem, not creative writing.**
>
> Inspired by **Borja (@borjafat)**, **TypeSafe Jev**, and **Distribb**.

---

## ⚡ The Breakthrough: System 1 (Jev) + System 2 (Frontier AI)

* **The Problem:** Auditing internal link structures across hundreds of pages with traditional frontier models (Claude Opus / GPT-4) costs \$40–\$100+ and takes hours of sequential inference.
* **The Solution (The Cascade Pattern):**
  1. **TypeSafe Jev (System 1):** Sub-second parallel decision engine evaluates **8,000+ candidate pairs in 45 seconds for ~\$0.21** (~190x cheaper) using typed primitives: `noul` (yes/no), `score` (relevance), and `choice` (clustering).
  2. **Auxiliary Frontier LLMs (System 2 - Gemini / Claude / GPT):** Reserved strictly for high-nuance rewriting, inserting descriptive non-repetitive anchor texts into natural sentences.
  3. **Google Search Console Integration:** Targets high-impression keywords lingering on **SERP Page 2 (Positions 11.0 to 20.0)** to pump link equity where it creates instant rank jumps.

---

## 🏛️ Famous Sites Benchmarks

SEO-Magus includes verified benchmark fixtures and tests modeled after industry-leading domain architectures:

| Company | Tested Topology | Key Verified Internal Links |
| :--- | :--- | :--- |
| **Mailchimp** | Email Marketing Guide (Pillar) $\leftrightarrow$ Welcome Sequence (Support) $\rightarrow$ Audience Segmentation (Money) | `welcome-sequence-guide` $\rightarrow$ `audience-segmentation` |
| **Stripe** | Online Payments (Pillar) $\leftrightarrow$ Fraud Prevention / Radar (Support) $\rightarrow$ Stripe Checkout (Money) | `how-to-prevent-credit-card-fraud` $\rightarrow$ `checkout` |
| **Shopify** | Start Ecommerce Business (Pillar) $\leftrightarrow$ Dropshipping Guide (Support) $\rightarrow$ Point of Sale / POS (Money) | `what-is-dropshipping` $\rightarrow$ `shopify.com/pos` |
| **GitHub** | CI/CD DevOps (Pillar) $\leftrightarrow$ GitHub Actions Tutorial (Support) $\rightarrow$ GitHub Enterprise (Money) | `what-is-ci-cd` $\rightarrow$ `github-actions-tutorial` & `enterprise` |

Run the benchmarks locally with:
```bash
python3 -m src.cli benchmark --site all
```

---

## 🚀 Quickstart

### 1. Installation
Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/SEO-magus.git
cd SEO-magus
```

Create a virtual environment (zero external dependencies required for core test execution):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Tests & Benchmarks
```bash
# Run unit & famous sites tests
python3 -m unittest discover tests

# Run demo link audit
python3 -m src.cli audit --demo

# Run SERP Page 2 opportunity scanner
python3 -m src.cli boost-page2
```

---

## 🎃 Hacktoberfest 2026: Join Us!

We are participating in **Hacktoberfest 2026**! We welcome contributors of all experience levels.

Check out our [Contributing Guidelines](CONTRIBUTING.md) and pick one of our **7 curated Hacktoberfest issues**:

| Issue | Title | Labels | Difficulty |
| :---: | :--- | :--- | :---: |
| **[#1](.github/hacktoberfest_issues/01_wordpress_rest_api_connector.md)** | Add WordPress REST API Connector for automated internal link updates | `good first issue`, `connectors` | Beginner |
| **[#2](.github/hacktoberfest_issues/02_nextjs_vercel_benchmark.md)** | Add Next.js & Vercel Documentation Site Benchmark | `good first issue`, `tests` | Beginner |
| **[#3](.github/hacktoberfest_issues/03_ghost_cms_connector.md)** | Implement Ghost CMS Admin API Connector & Webhook Listener | `enhancement`, `connectors` | Intermediate |
| **[#4](.github/hacktoberfest_issues/04_weighted_pagerank_click_depth.md)** | Weighted Internal PageRank with Click-Depth & CheiRank | `algorithm`, `core-engine` | Intermediate |
| **[#5](.github/hacktoberfest_issues/05_local_llm_ollama_fallback.md)** | Add Local LLM Fallback (Ollama / Llama.cpp) for Offline System 1 Decisions | `ai-engine`, `enhancement` | Intermediate |
| **[#6](.github/hacktoberfest_issues/06_interactive_d3_link_graph_visualizer.md)** | Interactive Force-Directed Link Graph Visualizer (D3.js / HTML Export) | `feature`, `visualization` | Intermediate |
| **[#7](.github/hacktoberfest_issues/07_github_action_pr_seo_audit.md)** | Create GitHub Action to Audit Markdown PRs for Broken Link Silos | `devops`, `automation` | Advanced |

---

## 📚 Documentation
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): Complete architecture specification, cascade pattern, and data flow.
* [`docs/JEV_INTEGRATION.md`](docs/JEV_INTEGRATION.md): TypeSafe Jev API contracts, `choice`/`score`/`noul` primitives.
* [`docs/PLAYBOOK_GUIDE.md`](docs/PLAYBOOK_GUIDE.md): The 8-step internal linking playbook and autonomous prompt template.
* [`reports/canivete_cc_audit_report.md`](reports/canivete_cc_audit_report.md): Case study audit of [canivete.cc](https://canivete.cc/).
* [`reports/zazazine_audit_report.md`](reports/zazazine_audit_report.md): Case study audit of [zazazine.verdindex.com](https://zazazine.verdindex.com/).

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
