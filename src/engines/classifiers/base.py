"""
Provider-agnostic link classification ("System 1" categoriser).

The optimizer only talks to LinkClassifier: any model that can answer
"does this paragraph give readers a natural reason to follow a link to this
target page, how confident are you, and how valuable is it (1-10)?" can plug in.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Tuple


class ClassifierError(RuntimeError):
    """A classifier could not produce a judgement (network, auth, unparseable answer...)."""


@dataclass(frozen=True)
class LinkCandidate:
    source_url: str
    source_paragraph: str
    target_url: str
    target_title: str
    target_topic: str                          # usually the target's H1
    target_queries: Tuple[str, ...] = ()       # SERP page 2 queries of the target (Search Console)


@dataclass(frozen=True)
class LinkJudgement:
    relevant: bool          # is there a legitimate contextual reason to link?
    confidence: float       # 0..1, confidence in `relevant`
    score: float            # 1..10, value of the transition for the reader
    provider: str = ""      # which classifier actually answered
    detail: str = field(default="", compare=False)

    def __post_init__(self):
        object.__setattr__(self, "confidence", min(1.0, max(0.0, float(self.confidence))))
        object.__setattr__(self, "score", min(10.0, max(1.0, float(self.score))))


class LinkClassifier(ABC):
    """Base class of every link classifier."""

    name: str = "classifier"
    cost_per_call_usd: float = 0.0

    @abstractmethod
    def evaluate(self, candidate: LinkCandidate) -> LinkJudgement:
        """Judge one candidate; raise ClassifierError when no judgement can be made."""

    def describe(self) -> str:
        return self.name
