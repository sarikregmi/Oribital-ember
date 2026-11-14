import re
from collections.abc import Iterable

from .models import Investigation, InvestigationResult


FIRE_SAFETY_SIGNALS = {
    "flammability": 3.0,
    "detection": 3.0,
    "suppression": 3.0,
    "oxygen": 2.0,
    "habitat": 2.0,
    "crew": 2.0,
    "material": 1.5,
    "smoke": 1.5,
    "extinction": 1.5,
    "fire": 1.0,
}
STOP_WORDS = {
    "about", "and", "are", "does", "for", "how", "in", "is", "of", "on",
    "the", "this", "what", "when", "where", "which", "why", "with",
}


def _tokens(value: str) -> set[str]:
    """Use whole meaningful words so incidental substrings do not create matches."""
    return {
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def rank_investigations(
    investigations: Iterable[Investigation], query: str = "",
) -> list[InvestigationResult]:
    terms = _tokens(query)
    results = []
    for investigation in investigations:
        fields = [
            investigation.name,
            investigation.description,
            investigation.domain,
            *investigation.gravity,
            *investigation.fuels,
            *investigation.conditions,
            *investigation.measurements,
            *investigation.hardware,
            *investigation.keywords,
        ]
        field_tokens = _tokens(" ".join(fields))
        name_tokens = _tokens(investigation.name)
        keyword_tokens = _tokens(" ".join(investigation.keywords))
        matched = sorted(term for term in terms if term in field_tokens)
        score = 0.0
        for term in matched:
            signal_weight = FIRE_SAFETY_SIGNALS.get(term, 0.5)
            if term == investigation.domain:
                score += signal_weight
            elif term in keyword_tokens:
                score += signal_weight * 0.75
            elif term in name_tokens:
                score += signal_weight * 0.6
            else:
                score += 0.25
        if not query:
            score = FIRE_SAFETY_SIGNALS.get(investigation.domain, 0.0)
        results.append(InvestigationResult(
            **investigation.model_dump(),
            relevance_score=round(score, 2),
            matched_signals=matched,
        ))
    return sorted(results, key=lambda item: (-item.relevance_score, item.id))
