"""
Evaluation sources, offline: every adapter is run against recorded responses in
the documented format of its API or dump, so the parsing rules (what is a gold
link, which label is primary, how redirects resolve) are pinned down by tests.

Note: these fixtures are hand-written in the APIs' documented shapes, not live
captures; the first live fetch of each source should be checked by eye
(`python -m src.evaluation info`), and its recorded cache can then become a fixture.
"""

import gzip
import io
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from src.evaluation.corpus import Corpus
from src.evaluation.sources import site_crawl
from src.evaluation.sources.http import HttpJsonClient, OfflineCacheMiss
from src.evaluation.sources.internet_archive import InternetArchiveSource, description_html, identifier_from_href
from src.evaluation.sources.prose import extract_prose
from src.evaluation.sources.stackexchange import StackExchangeDump, parse_tags
from src.evaluation.sources.wikipedia import WikipediaSource, article_url, load_clickstream, title_from_href
from tests.fixtures.crawls import load_crawl

AGENT = "SEO-Magus-test/1.0 (tests@example.com)"


class ScriptedClient:
    """Answers requests from a function of their parameters; records every call."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def get_json(self, url, params=None):
        params = dict(params) if not isinstance(params, list) else params
        self.calls.append((url, params))
        return self.answer(url, params)


# ------------------------------------------------------------------- prose


class TestProse(unittest.TestCase):
    def test_only_prose_links_with_their_paragraph(self):
        html = ('<div class="hatnote">See <a href="/wiki/X">X</a></div><table class="infobox"><tr><td>'
                '<a href="/wiki/Box">box</a></td></tr></table>'
                '<p>Compost <a href="/wiki/Fertilizer">fertilizes</a> soil.<sup class="reference">'
                '<a href="#c1">[1]</a></sup> See <a class="new" href="/w/index.php?title=Red">red</a>.</p>'
                '<p>Second<br>line with <a href="/wiki/Humus#Types">humus types</a></p>'
                '<ul><li>list <a href="/wiki/L">item</a></li></ul><div role="navigation"><p><a href="/wiki/N">n</a></p></div>')
        paragraphs, links = extract_prose(html, "https://en.wikipedia.org/wiki/Compost")
        self.assertEqual(paragraphs, ["Compost fertilizes soil. See red.", "Second line with humus types"])
        self.assertEqual([(l.href.rsplit("/", 1)[-1], l.anchor, l.paragraph) for l in links],
                         [("Fertilizer", "fertilizes", 0), ("Humus#Types", "humus types", 1)])
        paragraphs, links = extract_prose(html, "https://en.wikipedia.org/wiki/Compost", list_items=True)
        self.assertIn("list item", paragraphs)

    def test_malformed_html_never_breaks_the_anchor_invariant(self):
        html = "<p>one <a href='/a'>two</p> three</a> <p>four <b><a href='/b'>five</b></a></p></div></span>"
        paragraphs, links = extract_prose(html, "https://x.example/")
        for link in links:
            self.assertIn(link.anchor, paragraphs[link.paragraph])


# -------------------------------------------------------------------- http


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class TestHttpClient(unittest.TestCase):
    def test_contact_is_required_for_live_requests(self):
        with self.assertRaisesRegex(ValueError, "contact"):
            HttpJsonClient("SEO-Magus/1.0")
        with self.assertRaisesRegex(ValueError, "cache_dir"):
            HttpJsonClient(AGENT, offline=True)

    def test_record_replay_retry_and_gzip(self):
        attempts = []

        def opener(request, timeout):
            attempts.append(request.get_header("User-agent"))
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 503, "busy", {"Retry-After": "0"}, None)
            return FakeResponse(gzip.compress(b'{"ok": true}'), {"Content-Encoding": "gzip"})

        with tempfile.TemporaryDirectory() as tmp:
            client = HttpJsonClient(AGENT, cache_dir=tmp, min_interval=0, opener=opener)
            self.assertEqual(client.get_json("https://api.example/x", {"b": 2, "a": 1}), {"ok": True})
            self.assertEqual(attempts, [AGENT, AGENT])            # retried once after 503
            replay = HttpJsonClient(AGENT, cache_dir=tmp, offline=True)
            self.assertEqual(replay.get_json("https://api.example/x", {"a": 1, "b": 2}), {"ok": True})   # order-free key
            self.assertEqual(replay.cache_hits, 1)
            with self.assertRaises(OfflineCacheMiss):
                replay.get_json("https://api.example/x", {"a": 2})

    def test_network_errors_are_retried_then_surface(self):
        from urllib.error import URLError
        calls = []

        def flaky(request, timeout):
            calls.append(1)
            if len(calls) < 2:
                raise URLError("connection reset")
            return FakeResponse(b'{"n": 1}')

        from unittest import mock
        with mock.patch("src.evaluation.sources.http.time.sleep") as sleep:
            client = HttpJsonClient(AGENT, min_interval=0, retries=2, opener=flaky)
            self.assertEqual(client.get_json("https://api.example/z"), {"n": 1})
            self.assertEqual(sleep.call_args_list[-1].args, (2.0,))          # exponential backoff
            down = HttpJsonClient(AGENT, min_interval=0, retries=1, opener=lambda r, timeout: (_ for _ in ()).throw(URLError("down")))
            with self.assertRaises(URLError):
                down.get_json("https://api.example/z")
        self.assertEqual(client.requests_made, 2)
        with self.assertRaisesRegex(ValueError, "record\\(\\) needs a cache_dir"):
            client.record("https://api.example/z", None, {})

    def test_requests_are_spaced_by_the_minimum_interval(self):
        from unittest import mock
        with mock.patch("src.evaluation.sources.http.time.sleep") as sleep:
            client = HttpJsonClient(AGENT, min_interval=30, opener=lambda r, timeout: FakeResponse(b"{}"))
            client.get_json("https://api.example/1")
            client.get_json("https://api.example/2")
        self.assertTrue(any(call.args[0] > 29 for call in sleep.call_args_list))

    def test_non_retryable_errors_surface(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        client = HttpJsonClient(AGENT, min_interval=0, opener=opener)
        with self.assertRaises(HTTPError):
            client.get_json("https://api.example/y")


# --------------------------------------------------------------- wikipedia

WIKI_HTML = {
    "Compost": ('<p><b>Compost</b> feeds <a href="/wiki/Worm_composting" class="mw-redirect">worm composting</a> '
                'and is unlike a <a href="/wiki/Galaxy">galaxy</a>, a <a href="/wiki/File:X.jpg">file</a>, '
                'a <a href="https://de.wikipedia.org/wiki/Kompost">foreign page</a> or the '
                '<a href="/wiki/Sun">Sun</a>.</p>'),
    "Vermicompost": '<p>Vermicompost is a kind of <a href="/wiki/compost">compost</a>.</p>',
    "Star": '<p>A star lives in a <a href="/wiki/Galaxy">galaxy</a>.</p>',
    "Galaxy": "<p>A galaxy is big.</p><table><tr><td><a href='/wiki/Star'>star</a></td></tr></table>",
}
WIKI_CATEGORIES = {
    "Compost": [{"category": "Soil_improvers"}, {"category": "Articles_with_short_description", "hidden": True}],
    "Vermicompost": [{"category": "Composting"}],
    "Star": [{"category": "Stellar_astronomy"}],
    "Galaxy": [],
}


def wikipedia_api(url, params):
    assert params["format"] == "json" and params["formatversion"] == 2 and params["maxlag"] == 5
    if params.get("list") == "categorymembers":
        members = {"Category:Composting": ["Compost", "Vermicompost"], "Category:Astronomy": ["Star", "Galaxy"]}
        return {"query": {"categorymembers": [{"title": t} for t in members[params["cmtitle"]]]}}
    if params.get("action") == "parse":
        title = params["page"]
        return {"parse": {"title": title, "pageid": len(title), "text": WIKI_HTML[title],
                          "categories": WIKI_CATEGORIES[title]}}
    if params.get("prop") == "pageviews":
        views = {"Compost": {"2024-01-01": 10, "2024-01-02": None}, "Star": {"2024-01-01": 500}}
        return {"query": {"pages": [{"title": t, "pageviews": views.get(t)} for t in params["titles"].split("|")]}}
    if params.get("prop") == "links":
        links = {"Compost": ["Galaxy", "Worm composting"], "Star": ["Galaxy", "Vermicompost"]}
        pages = [{"title": t, "links": [{"title": l} for l in links.get(t, [])]} for t in params["titles"].split("|")]
        if "plcontinue" not in params:        # first page of a continued result
            return {"continue": {"plcontinue": "next", "continue": "||"}, "query": {"pages": pages[:1]}}
        return {"query": {"pages": pages[1:]}}
    if "titles" in params:                   # resolve
        titles = params["titles"].split("|")
        return {"query": {"normalized": [{"from": "compost", "to": "Compost"}] if "compost" in titles else [],
                          "redirects": [{"from": "Worm composting", "to": "Vermicompost"}],
                          "pages": [{"title": t} for t in titles if t not in ("Worm composting", "compost")]}}
    raise AssertionError(f"unexpected request {params}")


class TestWikipedia(unittest.TestCase):
    def test_titles_from_links(self):
        self.assertEqual(title_from_href("https://en.wikipedia.org/wiki/Worm_composting#Bins", "en"), "Worm composting")
        self.assertEqual(title_from_href("https://en.wikipedia.org/wiki/caf%C3%A9", "en"), "Café")
        for href in ("https://en.wikipedia.org/wiki/File:X.jpg", "https://en.wikipedia.org/wiki/Talk:X",
                     "https://de.wikipedia.org/wiki/X", "https://en.wikipedia.org/w/index.php?title=X",
                     "https://en.wikipedia.org/wiki/Category_talk:X"):
            self.assertIsNone(title_from_href(href, "en"), href)
        self.assertEqual(title_from_href("https://en.wikipedia.org/wiki/Star_Wars:_Episode_IV", "en"), "Star Wars: Episode IV")
        self.assertEqual(article_url("pt", "São Paulo"), "https://pt.wikipedia.org/wiki/S%C3%A3o_Paulo")

    def test_category_sample_with_every_layer(self):
        client = ScriptedClient(wikipedia_api)
        corpus = WikipediaSource(client, "en").build("wiki-test", categories=["Composting", "Astronomy"], limit=4)
        url = lambda t: article_url("en", t)
        self.assertEqual(sorted(corpus.ids), sorted(url(t) for t in WIKI_HTML))
        compost = corpus.get(url("Compost"))
        # Redirect resolved, foreign / file / out-of-sample (Sun) links dropped; anchor and paragraph kept.
        self.assertEqual([(l.target, l.anchor, l.paragraph) for l in compost.links],
                         [(url("Vermicompost"), "worm composting", 0), (url("Galaxy"), "galaxy", 0)])
        self.assertEqual(corpus.get(url("Vermicompost")).link_targets, [url("Compost")])   # "compost" normalized
        self.assertEqual(corpus.get(url("Galaxy")).links, [])                              # table link is not prose
        self.assertEqual(compost.labels, ["Composting", "Soil improvers"])                 # seed first, hidden dropped
        self.assertEqual((compost.popularity, corpus.get(url("Galaxy")).popularity), (10.0, None))
        self.assertEqual(corpus.get(url("Star")).extra_links, [url("Galaxy"), url("Vermicompost")])   # continuation
        self.assertEqual(corpus.provenance.method, "action-api/categories")
        self.assertEqual(corpus.provenance.language, "en")

    def test_snowball_follows_prose_links_until_the_limit(self):
        client = ScriptedClient(wikipedia_api)
        corpus = WikipediaSource(client, "en").build("snow", seeds=["Star"], limit=2, pageviews=False, wikilinks=False)
        self.assertEqual(corpus.ids, [article_url("en", "Star"), article_url("en", "Galaxy")])
        with self.assertRaisesRegex(ValueError, "exactly one sampler"):
            WikipediaSource(client).build("x", seeds=["A"], random_count=3)

    def test_requests_are_deterministic_for_replay(self):
        first, second = ScriptedClient(wikipedia_api), ScriptedClient(wikipedia_api)
        WikipediaSource(first).build("a", categories=["Composting", "Astronomy"], limit=4)
        WikipediaSource(second).build("a", categories=["Composting", "Astronomy"], limit=4)
        self.assertEqual(first.calls, second.calls)

    def test_random_sampler_failed_pages_and_missing_targets(self):
        draws = iter([["Star", "Galaxy", "Star"], ["Galaxy", "Nowhere", "Vermicompost"]])

        def api(url, params):
            if params.get("list") == "random":
                return {"query": {"random": [{"title": t} for t in next(draws)]}}
            if params.get("action") == "parse" and params["page"] == "Nowhere":
                return {"error": {"code": "missingtitle", "info": "The page you specified doesn't exist."}}
            if "titles" in params and params.get("prop") is None and params.get("action") == "query":
                titles = params["titles"].split("|")
                return {"query": {"pages": [{"title": t, **({"missing": True} if t == "Sun" else {})} for t in titles]}}
            return wikipedia_api(url, params)

        client = ScriptedClient(api)
        source = WikipediaSource(client, "en")
        self.assertEqual(source.random_titles(4), ["Star", "Galaxy", "Nowhere", "Vermicompost"])   # duplicates dropped
        self.assertEqual(len({c[1]["requestid"] for c in client.calls}), 2)                        # distinct cache keys
        draws = iter([["Star", "Nowhere"]])
        with self.assertLogs("seo_magus.evaluation.sources.wikipedia", "WARNING") as logs:
            corpus = source.build("r", random_count=2, limit=2, wikilinks=False)
        self.assertIn("parse failed for 'Nowhere'", logs.output[0])
        self.assertEqual(corpus.ids, [article_url("en", "Star")])
        self.assertEqual(source.resolve(["Sun", "Star"]), {"Star": "Star"})                        # missing page dropped

    def test_clickstream_keeps_navigation_inside_the_corpus(self):
        corpus = WikipediaSource(ScriptedClient(wikipedia_api)).build("c", categories=["Composting", "Astronomy"], limit=4)
        lines = ["Compost\tVermicompost\tlink\t40\n", "Compost\tGalaxy\tother\t12\n", "other-search\tStar\texternal\t900\n",
                 "Compost\tSun\tlink\t5\n", "Star\tGalaxy\tlink\t3\n", "Star\tGalaxy\tother\t2\n", "broken line\n"]
        load_clickstream(corpus, lines)
        url = lambda t: article_url("en", t)
        self.assertEqual(corpus.clickstream, {(url("Compost"), url("Vermicompost")): {"link": 40},
                                              (url("Compost"), url("Galaxy")): {"other": 12},
                                              (url("Star"), url("Galaxy")): {"link": 3, "other": 2}})
        self.assertIn("clickstream", corpus.layers)


# -------------------------------------------------------- internet archive


def archive_api(url, params):
    query = dict(params)
    collection = query["q"].split("(")[1].split(")")[0]
    items = {
        "prelinger": [{"identifier": "duck_and_cover", "title": "Duck and Cover", "downloads": 120000,
                       "collection": ["prelinger", "feature_films"], "subject": ["civil defense", "cold war"],
                       "description": "A 1951 film.<br><br>See also <a href='https://archive.org/details/atomic_cafe'>"
                                      "The Atomic Cafe</a>."},
                      {"identifier": "atomic_cafe", "title": "The Atomic Cafe", "downloads": 5000,
                       "collection": "prelinger", "subject": "documentary", "description": ["Part one.", "Part two."]}],
        "gutenberg": [{"identifier": "moby_dick", "title": "Moby Dick", "downloads": 90000, "collection": "gutenberg",
                       "subject": ["whaling"], "description": "<p>A novel.</p>"}],
    }[collection]
    if query["rows"] == 1:
        return {"response": {"numFound": len(items), "docs": items[:1]}}
    assert ("sort[]", "identifier asc") in params            # never sorted by downloads (range restriction)
    return {"response": {"numFound": len(items), "docs": items}}


class TestInternetArchive(unittest.TestCase):
    def test_collection_sample_with_labels_popularity_and_links(self):
        corpus = InternetArchiveSource(ScriptedClient(archive_api)).build("ia", ["prelinger", "gutenberg"], limit=4)
        film = corpus.get("https://archive.org/details/duck_and_cover")
        self.assertEqual(film.labels, ["prelinger", "feature_films", "subject:civil defense", "subject:cold war"])
        self.assertEqual(film.popularity, 120000.0)
        self.assertEqual(film.paragraphs, ["A 1951 film.", "See also The Atomic Cafe."])
        self.assertEqual([(l.target, l.anchor) for l in film.links],
                         [("https://archive.org/details/atomic_cafe", "The Atomic Cafe")])
        self.assertEqual(corpus.get("https://archive.org/details/atomic_cafe").paragraphs, ["Part one.", "Part two."])
        self.assertEqual(corpus.get("https://archive.org/details/moby_dick").labels, ["gutenberg", "subject:whaling"])

    def test_helpers(self):
        self.assertEqual(identifier_from_href("https://archive.org/details/abc/file.mp4"), "abc")
        self.assertIsNone(identifier_from_href("https://example.org/details/abc"))
        self.assertEqual(description_html("a\n\nb"), "<p>a</p><p>b</p>")
        self.assertEqual(description_html(None), "")


# ----------------------------------------------------------- stack exchange

POSTS = """<?xml version="1.0" encoding="utf-8"?>
<posts>
  <row Id="1" PostTypeId="1" Title="How do I start composting?" Tags="&lt;composting&gt;&lt;soil&gt;" ViewCount="900"
       Body="&lt;p&gt;How to start? See &lt;a href=&quot;https://gardening.stackexchange.com/questions/2/worms&quot;&gt;worm bins&lt;/a&gt;.&lt;/p&gt;" Score="5"/>
  <row Id="2" PostTypeId="1" Title="Are worms good for compost?" Tags="|composting|worms|" ViewCount="300"
       Body="&lt;p&gt;Worms?&lt;/p&gt;" Score="2"/>
  <row Id="3" PostTypeId="1" Title="Tomato leaves turning yellow" Tags="&lt;tomatoes&gt;" ViewCount="50"
       Body="&lt;p&gt;Yellow leaves.&lt;/p&gt;" Score="1"/>
  <row Id="10" PostTypeId="2" ParentId="2" Score="7"
       Body="&lt;p&gt;Yes, read &lt;a href=&quot;/a/11&quot;&gt;this answer on starting&lt;/a&gt;.&lt;/p&gt;"/>
  <row Id="11" PostTypeId="2" ParentId="1" Score="3" Body="&lt;p&gt;Start small.&lt;/p&gt;"/>
  <row Id="12" PostTypeId="2" ParentId="3" Score="1"
       Body="&lt;p&gt;&lt;a href=&quot;https://other.example/questions/1&quot;&gt;elsewhere&lt;/a&gt;&lt;/p&gt;"/>
</posts>"""
POST_LINKS = """<?xml version="1.0" encoding="utf-8"?>
<postlinks><row Id="1" PostId="2" RelatedPostId="1" LinkTypeId="3"/><row Id="2" PostId="3" RelatedPostId="1" LinkTypeId="1"/></postlinks>"""


class TestStackExchange(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "Posts.xml").write_text(POSTS, encoding="utf-8")
        Path(self.tmp.name, "PostLinks.xml").write_text(POST_LINKS, encoding="utf-8")

    def test_question_pages_with_answer_links_tags_views_and_postlinks(self):
        corpus = StackExchangeDump(self.tmp.name, "gardening.stackexchange.com").import_dump("se", limit=10)
        q = lambda n: f"https://gardening.stackexchange.com/questions/{n}"
        self.assertEqual(sorted(corpus.ids), [q(1), q(2), q(3)])
        self.assertEqual([(l.target, l.anchor) for l in corpus.get(q(1)).links], [(q(2), "worm bins")])
        worms = corpus.get(q(2))
        self.assertEqual(worms.paragraphs, ["Worms?", "Yes, read this answer on starting."])   # question, then answers
        self.assertEqual([l.target for l in worms.links], [q(1)])                                # /a/11 -> question 1
        self.assertEqual(worms.extra_links, [q(1)])                                              # duplicate relation
        self.assertEqual((worms.labels, worms.popularity), (["composting", "worms"], 300.0))
        self.assertEqual(corpus.get(q(3)).links, [])                                             # other host ignored

    def test_tag_sampling_and_formats(self):
        corpus = StackExchangeDump(self.tmp.name, "gardening.stackexchange.com").import_dump("se", limit=2,
                                                                                             tags=["worms", "tomatoes"])
        self.assertEqual(sorted(d.labels[0] for d in corpus.documents), ["tomatoes", "worms"])
        self.assertEqual(parse_tags("<a><b-c>"), ["a", "b-c"])
        self.assertEqual(parse_tags("|a|b-c|"), ["a", "b-c"])
        with self.assertRaises(FileNotFoundError):
            StackExchangeDump("/nonexistent", "x.stackexchange.com")


# ------------------------------------------------------------------ crawl


class TestSavedCrawlSource(unittest.TestCase):
    def test_mock_site_crawl_becomes_a_corpus_of_its_prose_links(self):
        corpus = site_crawl.from_crawl(load_crawl("greenleaf-good"), "greenleaf-good")
        self.assertEqual(len(corpus), 10)                              # indexable pages only
        self.assertIn("links", corpus.layers)
        for doc in corpus.documents:
            for link in doc.links:
                self.assertIn(link.anchor, doc.paragraphs[link.paragraph])
        self.assertNotIn("labels", corpus.layers)                       # never derived from URLs

    def test_links_outside_paragraphs_and_non_indexable_pages(self):
        from src.connectors.sitemap_crawler import CrawlResult, parse_html_page
        pages = [parse_html_page("https://s.example/", "<title>Home</title><p>Read the <a href='/a/'>a page</a>.</p>"
                                                       "<ul><li><a href='/b/'>b page</a></li></ul>"),
                 parse_html_page("https://s.example/a/", "<title>A</title><meta name='robots' content='noindex'>"),
                 parse_html_page("https://s.example/b/", "<title>B</title><p>B.</p>")]
        crawl = CrawlResult("https://s.example/", pages, [], False, {p.url: 200 for p in pages}, {}, [])
        corpus = site_crawl.from_crawl(crawl, "s")
        self.assertEqual(corpus.ids, ["https://s.example/", "https://s.example/b/"])   # noindex page dropped
        home = corpus.get("https://s.example/")
        self.assertEqual(home.links, [])                     # its only prose link pointed at the dropped page
        self.assertEqual(home.extra_links, ["https://s.example/b/"])   # list link: a human link, not prose
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Corpus.load(corpus.save(Path(tmp, "c.jsonl.gz"))).fingerprint(), corpus.fingerprint())


if __name__ == "__main__":
    unittest.main()
