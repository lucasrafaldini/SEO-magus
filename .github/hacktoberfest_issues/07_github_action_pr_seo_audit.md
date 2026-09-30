# Issue 7: Create GitHub Action to Audit Markdown PRs for Broken Link Silos

**Labels:** `hacktoberfest`, `devops`, `automation`, `ci-cd`  
**Difficulty:** Intermediate / Advanced  

---

### Description
Many modern documentation and engineering blogs are managed as static Markdown or MDX repositories on GitHub (e.g., Hugo, Astro, Docusaurus, Nextra).

When an author submits a Pull Request adding a new blog post or tutorial, it frequently becomes an **orphan page** because older articles have not been updated to link to it.

We want to package `SEO-magus` as a reusable GitHub Action (`action.yml`) that can be dropped into any content repository.

### Requirements
1. **GitHub Action Definition (`action.yml`):**
   - Inputs: `content_dir` (path to markdown files), `min_score`, `strict_mode` (fail PR if orphan page created).
   - Runs `SEO-magus` on the changed files in the pull request.
2. **PR Comment Bot:**
   - Post an automated, formatted Markdown comment on the Pull Request showing:
     - 📌 Suggested older articles that should link to this new post (with exact sentence diffs).
     - ⚠️ Warnings if the new post does not link back to any topic pillar.
3. **Example Workflow:**
   - Provide a `.github/workflows/internal-links-audit.yml` template in docs.

### How to Get Started
- Look at `src/workflows/linking_optimizer.py`.
- Creating a composite GitHub Action: https://docs.github.com/en/actions/creating-actions/creating-a-composite-action
