"""
Shared text primitives for the offline engines (Jev simulation and anchor extraction).

One tokenizer, one stopword list and one matching rule, so the simulated Jev
decision and the anchor chosen for a link always agree on what "mentions the
target topic" means.

Matching rule: a text token matches a topic token when they are equal, or when
both are at least 4 characters long and one is a prefix of the other. This is a
deliberately light stemmer that handles plurals and inflections in English and
Portuguese (segment/segmentation, salário/salários, reminder/reminders).
"""

import re
from typing import FrozenSet, Iterable, List, Set

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
MIN_PREFIX_LEN = 4

STOPWORDS: FrozenSet[str] = frozenset({
    # Portuguese
    "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "com", "sem", "por", "para", "sobre", "entre", "sob", "ate", "até",
    "e", "ou", "mas", "que", "se", "como", "quando", "onde", "porque",
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "seu", "sua", "seus", "suas", "meu", "minha", "nosso", "nossa",
    "ele", "ela", "eles", "elas", "este", "esta", "esse", "essa", "aquele", "aquela",
    "isso", "isto", "aquilo", "mais", "menos", "muito", "pouco", "bem", "mal",
    "tambem", "também", "ja", "já", "ainda", "assim", "caso", "entao", "então",
    "ao", "aos", "à", "às", "pelo", "pela", "pelos", "pelas", "num", "numa",
    # English
    "the", "a", "an", "and", "or", "in", "to", "for", "of", "with", "by", "on", "at",
    "from", "into", "onto", "upon", "about", "above", "across", "after", "against",
    "is", "are", "be", "it", "its", "this", "that", "these", "those", "as", "vs",
    "your", "you", "our", "we", "my", "their", "they", "them", "his", "her",
    "how", "what", "which", "who", "when", "where", "why",
})


def tokenize(text: str) -> List[str]:
    """Lower-case word tokens (letters and digits, any language)."""
    return [token.lower() for token in WORD_RE.findall(text)]


def is_content_token(token: str) -> bool:
    """A token that can carry meaning on its own: not a stopword, not just a number."""
    token = token.lower()
    return token not in STOPWORDS and not token.isdigit()


def content_tokens(*texts: str) -> Set[str]:
    """Distinct content tokens of one or more texts (the "topic vocabulary")."""
    return {token for text in texts for token in tokenize(text) if is_content_token(token)}


def tokens_match(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    return min(len(a), len(b)) >= MIN_PREFIX_LEN and (a.startswith(b) or b.startswith(a))


def matched_topic_tokens(topic: Iterable[str], text: str) -> Set[str]:
    """Topic tokens mentioned in text (under the shared matching rule)."""
    words = set(tokenize(text))
    return {t for t in topic if any(tokens_match(t, w) for w in words)}
