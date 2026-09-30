# Contributing to SEO-Magus

Thank you for your interest in contributing to **SEO-Magus**! 🚀

Whether you are participating in **Hacktoberfest**, fixing a bug, adding new test benchmarks, or building a CMS connector, your contributions are welcome!

---

## 🎃 Hacktoberfest Participation Guidelines

SEO-Magus is an official participant in **Hacktoberfest**!

1. **Find an Issue:** Look for issues tagged with [`hacktoberfest`](https://github.com/issues) and [`good first issue`](https://github.com/issues). Check our [curated Hacktoberfest issues](.github/hacktoberfest_issues/)!
2. **Claim an Issue:** Leave a comment on the issue you would like to work on so we can assign it to you and avoid duplicate work.
3. **Quality Matters:** Spam pull requests (e.g. whitespace changes, trivial README edits, bot-generated PRs) will be labeled `spam` or `invalid` and disqualified. We care about meaningful contributions!
4. **Follow the PR Template:** Fill out all sections of the Pull Request template.

---

## 🛠️ Development Setup

### 1. Fork and Clone
```bash
git clone https://github.com/YOUR_USERNAME/SEO-magus.git
cd SEO-magus
```

### 2. Set Up Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the Test Suite
All tests use Python's built-in `unittest` runner and require zero external mock servers:
```bash
python3 -m unittest discover tests
```

### 4. Run Famous Sites Benchmarks
Test internal linking generation against real-world architectures from Mailchimp, Stripe, Shopify, and GitHub:
```bash
python3 -m src.cli benchmark --site all
```

---

## 📌 Making a Pull Request

1. **Branch Naming:**
   - `feature/your-feature-name`
   - `fix/issue-description`
   - `docs/what-you-changed`
2. **Keep Commits Clean:** Write descriptive commit messages (e.g., `feat(connectors): add WordPress REST API client`).
3. **Ensure Tests Pass:** Make sure `python3 -m unittest discover tests` passes before opening your PR.
4. **Include Tests:** If you are adding a feature or connector, add corresponding test coverage under `tests/`.

---

## 💬 Community & Questions

Feel free to open an issue or start a discussion if you need guidance on any issue. Happy hacking! 🎃
