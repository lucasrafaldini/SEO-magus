# Issue 1: Add WordPress REST API Connector for automated internal link updates

**Labels:** `hacktoberfest`, `good first issue`, `enhancement`, `connectors`  
**Difficulty:** Beginner / Intermediate  

---

### Description
Currently, `SEO-magus` generates actionable link proposals with exact before-and-after sentences and anchor text, but applying these edits to CMS platforms like WordPress requires manual copying and pasting.

We want to add a native WordPress REST API connector in `src/connectors/wordpress_connector.py`.

### Requirements
1. **Authentication:** Support WordPress Application Passwords (Basic Auth over HTTPS).
2. **Fetch Posts:** Retrieve published posts and pages via `GET /wp-json/wp/v2/posts` and `GET /wp-json/wp/v2/pages`.
3. **Update Content:** Method `apply_link_replacement(post_id, original_sentence, updated_sentence)` that safely updates `content.raw` using `POST /wp-json/wp/v2/posts/<id>`.
4. **Dry Run Mode:** Provide a `--dry-run` flag so users can review the diff before committing changes to their live site.
5. **Unit Tests:** Add mocked tests in `tests/test_wordpress_connector.py`.

### How to Get Started
- Check `src/connectors/sitemap_crawler.py` and `src/workflows/linking_optimizer.py`.
- WordPress REST API Reference: https://developer.wordpress.org/rest-api/reference/posts/
