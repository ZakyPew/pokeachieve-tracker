from __future__ import annotations

from pokemon_cv.smooth.voting import NofMTemporalSmoother


def test_smoother_requires_n_of_m_consensus() -> None:
    smoother = NofMTemporalSmoother(window_size=6, min_votes=4, min_stable_confidence=0.60)

    # 3 votes is not enough
    for _ in range(3):
        stable = smoother.update("nincada", 0.9)
        assert stable.is_stable is False

    # 4th vote reaches 4-of-6
    stable = smoother.update("nincada", 0.9)
    assert stable.is_stable is True
    assert stable.label == "nincada"
    assert stable.support_count >= 4


def test_smoother_rejects_low_confidence_consensus() -> None:
    smoother = NofMTemporalSmoother(window_size=6, min_votes=4, min_stable_confidence=0.75)
    for _ in range(6):
        stable = smoother.update("taillow", 0.60)
    assert stable.is_stable is False
    assert stable.label == "unknown"


def test_smoother_ignores_unknown_votes() -> None:
    smoother = NofMTemporalSmoother(window_size=6, min_votes=3, min_stable_confidence=0.50)
    smoother.update("unknown", 0.0)
    smoother.update("unknown", 0.0)
    stable = smoother.update("poochyena", 0.8)
    assert stable.is_stable is False

    smoother.update("poochyena", 0.8)
    stable = smoother.update("poochyena", 0.8)
    assert stable.is_stable is True
    assert stable.label == "poochyena"