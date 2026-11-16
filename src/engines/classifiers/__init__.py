"""
Link classifiers ("System 1" categorisers): the model that decides whether a
candidate internal link is legitimate. TypeSafe Jev is the default when its key
is set; any other provider, local model or custom class can be configured.

Only the base types are imported eagerly; providers load on demand.
"""

from src.engines.classifiers.base import ClassifierError, LinkCandidate, LinkClassifier, LinkJudgement
from src.engines.classifiers.factory import ClassifierConfig, FallbackClassifier, build_classifier
from src.engines.classifiers.heuristic import HeuristicClassifier

__all__ = [
    "ClassifierConfig",
    "ClassifierError",
    "FallbackClassifier",
    "HeuristicClassifier",
    "LinkCandidate",
    "LinkClassifier",
    "LinkJudgement",
    "build_classifier",
]
