from __future__ import annotations

from pokemon_cv.match.logic import decide_unknown, similarity_to_confidence


def test_decide_unknown_below_similarity_threshold() -> None:
    d = decide_unknown(
        top1_similarity=0.58,
        top2_similarity=0.20,
        similarity_threshold=0.62,
        margin_threshold=0.07,
    )
    assert d.is_unknown is True
    assert d.reason == "below_similarity_threshold"


def test_decide_unknown_ambiguous_margin() -> None:
    d = decide_unknown(
        top1_similarity=0.80,
        top2_similarity=0.76,
        similarity_threshold=0.62,
        margin_threshold=0.07,
    )
    assert d.is_unknown is True
    assert d.reason == "ambiguous_margin"


def test_decide_unknown_accepted() -> None:
    d = decide_unknown(
        top1_similarity=0.82,
        top2_similarity=0.60,
        similarity_threshold=0.62,
        margin_threshold=0.07,
    )
    assert d.is_unknown is False
    assert d.reason == "accepted"


def test_similarity_to_confidence_mapping() -> None:
    assert similarity_to_confidence(-1.0) == 0.0
    assert similarity_to_confidence(1.0) == 1.0
    assert abs(similarity_to_confidence(0.0) - 0.5) < 1e-6