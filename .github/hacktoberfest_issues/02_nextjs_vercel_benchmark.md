# Issue 2: Add Next.js & Vercel Documentation Site Benchmark

**Labels:** `hacktoberfest`, `good first issue`, `documentation`, `tests`  
**Difficulty:** Beginner  

---

### Description
`SEO-magus` already features test benchmarks for famous websites like Mailchimp, Stripe, Shopify, and GitHub in `tests/test_famous_sites.py`.

We want to add a real-world developer documentation benchmark representing the **Next.js & Vercel** documentation architecture.

### Requirements
1. **Add Fixtures in `tests/fixtures/famous_sites_data.py`:**
   - Define `get_nextjs_pages()` returning a list of `ParsedPage` objects:
     - Pillar Guide: Next.js App Router Master Guide (`https://nextjs.org/docs/app`)
     - Support Post: Server Components vs Client Components tutorial (`https://nextjs.org/docs/app/building-your-application/rendering/server-components`)
     - Support Post: Route Handlers / API routes (`https://nextjs.org/docs/app/building-your-application/routing/route-handlers`)
     - Money Page: Vercel Enterprise Deployment (`https://vercel.com/enterprise`)
2. **Add Test Case in `tests/test_famous_sites.py`:**
   - Implement `test_nextjs_benchmark(self)` asserting that the optimizer establishes contextual links between Server Components, App Router, and Vercel Deployment.
3. **Add CLI Target:**
   - Update `src/cli.py` to allow running `python3 -m src.cli benchmark --site nextjs`.

### How to Get Started
- Look at `get_mailchimp_pages()` and `get_stripe_pages()` in `tests/fixtures/famous_sites_data.py`.
- Run tests locally with `python3 -m unittest discover tests`.
