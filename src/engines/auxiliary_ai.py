"""
Auxiliary Frontier AI Client (System Two).

Responsible for the generative, high-nuance rewriting and anchor-text insertion
once Jev has approved the link candidate.
Includes Portuguese and English stop-word filtering and multi-word anchor generation.
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

PT_EN_STOPWORDS: Set[str] = {
    # Portuguese
    "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "com", "sem", "por", "para", "sobre", "entre", "sob", "ate", "até",
    "e", "ou", "mas", "que", "se", "como", "quando", "onde", "porque",
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "seu", "sua", "seus", "suas", "meu", "minha", "nosso", "nossa",
    "ele", "ela", "eles", "elas", "este", "esta", "esse", "essa", "aquele", "aquela",
    "isso", "isto", "aquilo", "mais", "menos", "muito", "pouco", "bem", "mal",
    "tambem", "também", "ja", "já", "ainda", "assim", "caso", "entao", "então",
    # English
    "the", "a", "an", "and", "or", "in", "to", "for", "of", "with", "by", "on", "at",
    "from", "into", "onto", "upon", "about", "above", "across", "after", "against",
    "guide", "how", "what", "which", "who", "when", "where", "why",
}


@dataclass
class InsertionProposal:
    original_sentence: str
    updated_sentence: str
    anchor_text: str
    target_url: str
    rationale: str


class AuxiliaryAIEngine:
    def __init__(
        self,
        provider: str = "auto",
        api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

    def craft_link_insertion(
        self,
        source_paragraph: str,
        target_url: str,
        target_title: str,
        target_topic: str,
    ) -> Optional[InsertionProposal]:
        """
        Locates the best sentence in source_paragraph, finds a multi-word or high-relevance anchor,
        and rewrites/wraps it naturally.
        """
        sentences = [s.strip() for s in re.split(r"(?<=[.!?]) +", source_paragraph) if s.strip()]
        if not sentences:
            sentences = [source_paragraph]

        # Extract meaningful keywords from target topic and title
        clean_target = re.sub(r"[—\-:★\(\)]", " ", f"{target_title} {target_topic}").lower()
        target_tokens = [
            t for t in re.findall(r"\b[a-z0-9à-ú]{3,}\b", clean_target)
            if t not in PT_EN_STOPWORDS
        ]

        if not target_tokens:
            return None

        # Score sentences by token overlap
        best_sentence = None
        max_overlap = 0

        for s in sentences:
            s_lower = s.lower()
            overlap = sum(1 for t in target_tokens if t in s_lower)
            if overlap > max_overlap:
                max_overlap = overlap
                best_sentence = s

        if not best_sentence or max_overlap == 0:
            return None

        # Build candidate multi-word phrases from title or topic that might exist in sentence
        # e.g. "seguro-desemprego", "carta de demissão", "calculadora de rescisão clt", "salário líquido"
        candidate_phrases = []
        # Try full target topic or title parts
        for candidate in [target_topic, target_title]:
            cand_clean = re.sub(r"[—\-:★\(\)]", "", candidate).strip()
            if cand_clean.lower() in best_sentence.lower():
                candidate_phrases.append(cand_clean)

        # Check for 2-word or 3-word n-grams in target_title that appear in sentence
        words_in_title = target_title.split()
        for n in [4, 3, 2]:
            for i in range(len(words_in_title) - n + 1):
                phrase = " ".join(words_in_title[i : i + n]).strip(",.:;—")
                if len(phrase) > 5 and phrase.lower() in best_sentence.lower():
                    candidate_phrases.append(phrase)

        # Pick the longest matched phrase
        chosen_anchor = None
        candidate_phrases.sort(key=len, reverse=True)
        for ph in candidate_phrases:
            pattern = re.compile(rf"\b({re.escape(ph)})\b", re.IGNORECASE)
            if pattern.search(best_sentence):
                chosen_anchor = ph
                break

        # Fallback to single token if no multi-word phrase matched, but token must NOT be a stopword
        if not chosen_anchor:
            for t in sorted(target_tokens, key=len, reverse=True):
                pattern = re.compile(rf"\b({re.escape(t)}[a-zà-ú]*)\b", re.IGNORECASE)
                m = pattern.search(best_sentence)
                if m and m.group(1).lower() not in PT_EN_STOPWORDS and len(m.group(1)) >= 4:
                    chosen_anchor = m.group(1)
                    break

        if not chosen_anchor:
            return None

        # Wrap anchor text cleanly
        updated_sentence = re.sub(
            rf"\b({re.escape(chosen_anchor)})\b",
            rf"[\1]({target_url})",
            best_sentence,
            count=1,
            flags=re.IGNORECASE,
        )

        return InsertionProposal(
            original_sentence=best_sentence,
            updated_sentence=updated_sentence,
            anchor_text=chosen_anchor,
            target_url=target_url,
            rationale=f"Conecta o contexto da leitura diretamente à ferramenta/guia '{target_title}'.",
        )
