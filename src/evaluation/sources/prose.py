"""
HTML -> prose paragraphs and the links written inside them.

Every source that delivers HTML (Wikipedia parser output, Stack Exchange post
bodies, Internet Archive descriptions) goes through this one extractor, so
"a human-placed in-prose link" means the same thing for every source:

  * only text inside <p> elements counts as prose (list items optionally);
  * tables (infoboxes), navigation boxes, reference markers, edit links,
    figures, math, scripts and styles are skipped with everything inside them;
  * a link is kept with its anchor text and the index of its paragraph, and
    the anchor text is always a substring of that paragraph's text.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

_SKIP_TAGS = {"table", "sup", "style", "script", "noscript", "figure", "math", "nav", "template", "svg"}
_SKIP_CLASSES = ("mw-editsection", "reference", "noprint", "navbox", "hatnote", "infobox", "mw-empty-elt",
                 "metadata", "mwe-math-element")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ProseLink:
    href: str          # absolute URL (fragment kept; callers decide)
    anchor: str        # link text, whitespace-normalized
    paragraph: int     # index into the returned paragraphs


class _ProseParser(HTMLParser):
    def __init__(self, base_url: str, list_items: bool):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks = {"p", "li"} if list_items else {"p"}
        self.stack: List[Tuple[str, bool]] = []     # (tag, skipped)
        self.skip_depth = 0
        self.paragraph: Optional[List[str]] = None
        self.links_in_paragraph: List[Tuple[str, List[str]]] = []
        self.anchor: Optional[Tuple[str, List[str]]] = None
        self.paragraphs: List[str] = []
        self.links: List[ProseLink] = []

    # -- structure

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in _VOID:
            if tag == "br" and self.paragraph is not None and not self.skip_depth:
                self._text(" ")
            return
        classes = (attrs.get("class") or "").split()
        skipped = (tag in _SKIP_TAGS or attrs.get("role") == "navigation"
                   or any(c.startswith(_SKIP_CLASSES) for c in classes))
        if tag in self.blocks and not self.skip_depth:
            self._close_paragraph()
            self.paragraph = []
        self.stack.append((tag, skipped))
        if skipped:
            self.skip_depth += 1
            return
        if tag == "a" and self.paragraph is not None and not self.skip_depth and attrs.get("href"):
            if "new" not in classes:          # MediaWiki red link: the target page does not exist
                self.anchor = (urljoin(self.base_url, attrs["href"]), [])

    def handle_endtag(self, tag):
        if tag in _VOID or not any(open_tag == tag for open_tag, _ in self.stack):
            return                            # stray end tag
        while self.stack:
            open_tag, skipped = self.stack.pop()
            if skipped:
                self.skip_depth -= 1
            if open_tag == "a":
                self._close_anchor()
            if open_tag in self.blocks and not self.skip_depth:
                self._close_paragraph()
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.paragraph is not None and not self.skip_depth:
            self._text(data)

    def _text(self, data: str):
        self.paragraph.append(data)
        if self.anchor is not None:
            self.anchor[1].append(data)

    def _close_anchor(self):
        if self.anchor is not None:
            href, parts = self.anchor
            self.links_in_paragraph.append((href, parts))
            self.anchor = None

    def _close_paragraph(self):
        self._close_anchor()
        if self.paragraph is None:
            return
        text = _SPACE_RE.sub(" ", "".join(self.paragraph)).strip()
        if text:
            index = len(self.paragraphs)
            self.paragraphs.append(text)
            for href, parts in self.links_in_paragraph:
                anchor = _SPACE_RE.sub(" ", "".join(parts)).strip()
                if anchor and anchor in text:
                    self.links.append(ProseLink(href, anchor, index))
        self.paragraph, self.links_in_paragraph = None, []

    def close(self):
        super().close()
        self._close_paragraph()


def extract_prose(html: str, base_url: str, list_items: bool = False) -> Tuple[List[str], List[ProseLink]]:
    """Paragraph texts and the links inside them (see the module docstring for the rules)."""
    parser = _ProseParser(base_url, list_items)
    parser.feed(html or "")
    parser.close()
    return parser.paragraphs, parser.links
