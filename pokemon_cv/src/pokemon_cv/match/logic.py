from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UnknownDecision:
    is_unknown: bool
    reason: str


def decide_unknown(
    top1_similarity: float,
    top2_similarity: float | None,
    similarity_threshold: float,
    margin_threshold: float,
) -> UnknownDecision:
    if top1_similarity < similarity_threshold:
        return UnknownDecision(True, "below_similarity_threshold")
    if top2_similarity is not None and (top1_similarity - top2_similarity) < margin_threshold:
        return UnknownDecision(True, "ambiguous_margin")
    return UnknownDecision(False, "accepted")


def similarity_to_confidence(similarity: float) -> float:
    # cosine similarity range [-1, 1] => [0, 1]
    return max(0.0, min(1.0, (float(similarity) + 1.0) * 0.5))
