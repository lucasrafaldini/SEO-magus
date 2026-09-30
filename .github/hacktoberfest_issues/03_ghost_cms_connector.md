# Issue 3: Implement Ghost CMS Admin API Connector

**Labels:** `hacktoberfest`, `enhancement`, `connectors`  
**Difficulty:** Intermediate  

---

### Description
Ghost CMS is widely used by independent magazines, technical newsletters, and publication blogs (such as ZAZAZINE).

We need an official Ghost connector in `src/connectors/ghost_connector.py` to allow `SEO-magus` to read and update articles directly through the Ghost Admin API.

### Requirements
1. **JWT Authentication:** Generate the short-lived JWT token required by the Ghost Admin API using the user's `ADMIN_API_KEY` (Key ID + Secret).
2. **Fetch Articles:** Method `get_posts()` to retrieve posts including HTML and Lexical/Mobiledoc content via `GET /ghost/api/admin/posts/`.
3. **Link Modification:** Method `update_post_content(post_id, updated_html)` to update post body with new internal links while preserving metadata and tags.
4. **Integration with Workflows:** Connect with `src/workflows/linking_optimizer.py`.
5. **Unit Tests:** Provide mocked tests in `tests/test_ghost_connector.py`.

### How to Get Started
- Ghost Admin API Reference: https://ghost.org/docs/admin-api/
- Python JWT token generation pattern for Ghost Admin API.
