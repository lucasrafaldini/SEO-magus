"""
Auxiliary Frontier AI Client (System Two).

Responsible for the generative, high-nuance rewriting and anchor-text insertion
once Jev has approved the link candidate.
Includes Portuguese and English stop-word filtering and multi-word anchor generation.
"""

import os
import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Sequence, Set, Tuple

from src.engines.text import STOPWORDS, WORD_RE, content_tokens, is_content_token, tokens_match
from src.log import get_logger

logger = get_logger(__name__)

# Kept for backwards compatibility; the shared list lives in src/engines/text.py.
PT_EN_STOPWORDS: Set[str] = set(STOPWORDS)

DEFAULT_MIN_ANCHOR_WORDS = 2
MAX_INNER_STOPWORDS = 2          # "Contrato de Prestação de Serviços" keeps its inner "de"s
MAX_INNER_MODIFIERS = 1          # "reclassificação federal da cannabis": one non-topic word inside
MAX_ANCHOR_WORDS = 6             # keep anchors short and natural
_TITLE_SEPARATOR_RE = re.compile(r"\s[|:–—-]\s|:\s")   # "Name | Tagline", "Name: Subtitle"
_JOINER_RE = re.compile(r"[\s\-'’]*")  # text allowed between two words of one anchor


@dataclass
class InsertionProposal:
    original_sentence: str
    updated_sentence: str
    anchor_text: str
    target_url: str
    rationale: str


@dataclass(frozen=True)
class AnchorSpan:
    text: str           # exact text in the sentence (original casing)
    start: int
    end: int
    content_words: int  # distinct topic terms the anchor names
    modifiers: int = 0  # non-topic words inside the anchor
    words: int = 0      # total words
    terms: FrozenSet[str] = frozenset()  # the topic terms named

    def rank(self, name_terms: Set[str]) -> Tuple[int, int, int, int]:
        """
        Higher is better: topic terms net of modifiers, then terms of the target's
        name (first title segment, e.g. "Stripe Checkout" in "Stripe Checkout | ...")
        net of modifiers, then fewer words, then earlier in the sentence.
        """
        net_name_terms = len(self.terms & name_terms) - self.modifiers
        return (self.content_words - self.modifiers, net_name_terms, -self.words, -self.start)


def split_sentences(paragraph: str) -> List[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?]) +", paragraph) if s.strip()]
    return sentences or [paragraph]


def _topic_term(token: str, topic: Set[str]) -> Optional[str]:
    if not is_content_token(token):
        return None
    return next((t for t in sorted(topic) if tokens_match(token, t)), None)


def find_anchor_spans(sentence: str, topic: Set[str]) -> List[AnchorSpan]:
    """
    Candidate anchors in a sentence: phrases of at most MAX_ANCHOR_WORDS adjacent
    words that start and end with a word naming the target topic. Inside, a phrase
    may contain up to MAX_INNER_STOPWORDS consecutive stopwords and
    MAX_INNER_MODIFIERS other (non-numeric) words; it breaks at punctuation (only
    spaces, hyphens and apostrophes may join its words) and at bare numbers.
    """
    words = list(WORD_RE.finditer(sentence))
    terms: List[Optional[str]] = []
    kinds: List[str] = []
    for match in words:
        token = match.group(0).lower()
        term = _topic_term(token, topic)
        terms.append(term)
        if term is not None:
            kinds.append("topic")
        elif token in STOPWORDS:
            kinds.append("stop")
        elif not token.isdigit():
            kinds.append("modifier")
        else:
            kinds.append("other")

    spans: List[AnchorSpan] = []
    for i, kind in enumerate(kinds):
        if kind != "topic":
            continue
        stops_in_row = modifiers = 0
        for j in range(i, min(len(words), i + MAX_ANCHOR_WORDS)):
            if j > i:
                joined = _JOINER_RE.fullmatch(sentence[words[j - 1].end():words[j].start()])
                if not joined or kinds[j] == "other":
                    break
                if kinds[j] == "stop":
                    stops_in_row += 1
                    if stops_in_row > MAX_INNER_STOPWORDS:
                        break
                    continue
                stops_in_row = 0
                if kinds[j] == "modifier":
                    modifiers += 1
                    if modifiers > MAX_INNER_MODIFIERS:
                        break
                    continue
            start, end = words[i].start(), words[j].end()
            spans.append(AnchorSpan(
                text=sentence[start:end],
                start=start,
                end=end,
                content_words=len({terms[k] for k in range(i, j + 1) if terms[k] is not None}),
                modifiers=modifiers,
                words=j - i + 1,
                terms=frozenset(terms[k] for k in range(i, j + 1) if terms[k] is not None),
            ))
    return spans


def _occurrences(sentence: str, phrases: Sequence[str]) -> List[Tuple[int, int]]:
    """Character intervals of every case-insensitive occurrence of the phrases."""
    lowered = sentence.lower()
    intervals = []
    for phrase in phrases:
        phrase = phrase.strip().lower()
        start = lowered.find(phrase) if phrase else -1
        while start != -1:
            intervals.append((start, start + len(phrase)))
            start = lowered.find(phrase, start + 1)
    return intervals


class AuxiliaryAIEngine:
    def __init__(
        self,
        provider: str = "auto",
        api_key: Optional[str] = None,
        min_anchor_words: int = DEFAULT_MIN_ANCHOR_WORDS,
    ):
        self.provider = provider
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.min_anchor_words = min_anchor_words
        if self.api_key:
            logger.warning(
                "Auxiliary AI: an LLM API key is set, but only the offline anchor engine is implemented; using it"
            )
        logger.info("Auxiliary AI ready: offline anchor engine (anchors >= %d topic words)", min_anchor_words)

    def craft_link_insertion(
        self,
        source_paragraph: str,
        target_url: str,
        target_title: str,
        target_topic: str,
        target_queries: Optional[List[str]] = None,
        blocked_phrases: Sequence[str] = (),
    ) -> Optional[InsertionProposal]:
        """
        Find the most descriptive anchor for the target in source_paragraph and
        wrap it in place.

        Anchor quality rules (the playbook's "descriptive anchors"):
          * a contiguous phrase of the sentence naming the target topic
            (title, H1 and page 2 search queries);
          * at least min_anchor_words distinct topic words;
          * never starts or ends with a stopword or a bare number.
          * at most MAX_ANCHOR_WORDS words;
          * no overlap with blocked_phrases (anchor texts of links already on the
            page or already proposed), so links are never nested.
        Among valid anchors the best AnchorSpan.rank wins (topic terms net of
        modifiers, then words naming the target, then fewer words, then earlier);
        earlier sentences win ties.
        Returns None when no valid anchor exists.
        """
        topic = content_tokens(target_title, target_topic, *(target_queries or []))
        name = _TITLE_SEPARATOR_RE.split(target_title, maxsplit=1)[0]
        name_terms = {t for t in topic if any(tokens_match(t, w) for w in content_tokens(name))}
        best: Optional[Tuple[Tuple[int, int, int, int], str, AnchorSpan]] = None
        for sentence in split_sentences(source_paragraph):
            taken = _occurrences(sentence, blocked_phrases)
            for span in find_anchor_spans(sentence, topic):
                if span.content_words < self.min_anchor_words:
                    continue
                if any(span.start < end and start < span.end for start, end in taken):
                    continue
                rank = span.rank(name_terms)
                if best is None or rank > best[0]:
                    best = (rank, sentence, span)

        if best is None:
            logger.debug("No anchor with >= %d topic words for %s in: %.80s",
                         self.min_anchor_words, target_url, source_paragraph)
            return None

        _, sentence, span = best
        updated_sentence = f"{sentence[:span.start]}[{span.text}]({target_url}){sentence[span.end:]}"
        logger.debug("Anchor %r chosen for %s", span.text, target_url)
        return InsertionProposal(
            original_sentence=sentence,
            updated_sentence=updated_sentence,
            anchor_text=span.text,
            target_url=target_url,
            rationale=f"Connects the reader's current context directly to '{target_title}'.",
        )
