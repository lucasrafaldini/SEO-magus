#!/usr/bin/env bash
# Script to automatically create the 7 Hacktoberfest issues on GitHub using gh CLI

set -e

echo "🎃 Checking GitHub CLI authentication..."
if ! command -v gh &> /dev/null; then
    echo "⚠️ 'gh' CLI is not installed. You can copy the issues manually from .github/hacktoberfest_issues/ or install gh."
    exit 1
fi

echo "Creating Hacktoberfest Issues on repository..."

# Issue 1
gh issue create \
  --title "[Hacktoberfest] Add WordPress REST API Connector for automated internal link updates" \
  --body-file .github/hacktoberfest_issues/01_wordpress_rest_api_connector.md \
  --label "hacktoberfest,good first issue,enhancement,connectors"

# Issue 2
gh issue create \
  --title "[Hacktoberfest] Add Next.js & Vercel Documentation Site Benchmark" \
  --body-file .github/hacktoberfest_issues/02_nextjs_vercel_benchmark.md \
  --label "hacktoberfest,good first issue,documentation,tests"

# Issue 3
gh issue create \
  --title "[Hacktoberfest] Implement Ghost CMS Admin API Connector" \
  --body-file .github/hacktoberfest_issues/03_ghost_cms_connector.md \
  --label "hacktoberfest,enhancement,connectors"

# Issue 4
gh issue create \
  --title "[Hacktoberfest] Weighted Internal PageRank with Click-Depth & CheiRank" \
  --body-file .github/hacktoberfest_issues/04_weighted_pagerank_click_depth.md \
  --label "hacktoberfest,algorithm,core-engine"

# Issue 5
gh issue create \
  --title "[Hacktoberfest] Add Local LLM Fallback (Ollama / Llama.cpp) for Offline System 1 Decision Making" \
  --body-file .github/hacktoberfest_issues/05_local_llm_ollama_fallback.md \
  --label "hacktoberfest,ai-engine,enhancement"

# Issue 6
gh issue create \
  --title "[Hacktoberfest] Interactive Force-Directed Link Graph Visualizer (D3.js / HTML Export)" \
  --body-file .github/hacktoberfest_issues/06_interactive_d3_link_graph_visualizer.md \
  --label "hacktoberfest,feature,visualization"

# Issue 7
gh issue create \
  --title "[Hacktoberfest] Create GitHub Action to Audit Markdown PRs for Broken Link Silos" \
  --body-file .github/hacktoberfest_issues/07_github_action_pr_seo_audit.md \
  --label "hacktoberfest,devops,automation"

echo "🎉 All 7 Hacktoberfest issues created successfully!"
