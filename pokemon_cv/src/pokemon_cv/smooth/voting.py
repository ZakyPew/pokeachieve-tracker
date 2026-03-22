from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from pokemon_cv.match.types import StablePrediction


@dataclass(slots=True)
class _Vote:
    label: str
    confidence: float


class NofMTemporalSmoother:
    """Sliding-window N-of-M voting for stable label emission."""

    def __init__(
        self,
        window_size: int = 6,
        min_votes: int = 4,
        min_stable_confidence: float = 0.60,
        unknown_label: str = "unknown",
    ) -> None:
        self.window_size = max(1, int(window_size))
        self.min_votes = max(1, min(int(min_votes), self.window_size))
        self.min_stable_confidence = float(min_stable_confidence)
        self.unknown_label = str(unknown_label)
        self._window: deque[_Vote] = deque(maxlen=self.window_size)

    def reset(self) -> None:
        self._window.clear()

    def update(self, label: str, confidence: float) -> StablePrediction:
        clean_label = str(label or self.unknown_label)
        clean_conf = max(0.0, min(1.0, float(confidence)))
        self._window.append(_Vote(label=clean_label, confidence=clean_conf))

        counts: dict[str, int] = defaultdict(int)
        conf_sums: dict[str, float] = defaultdict(float)
        for vote in self._window:
            if vote.label == self.unknown_label:
                continue
            counts[vote.label] += 1
            conf_sums[vote.label] += vote.confidence

        if not counts:
            return StablePrediction(
                label=self.unknown_label,
                confidence=0.0,
                support_count=0,
                window_size=len(self._window),
                is_stable=False,
            )

        best_label = max(
            counts.keys(),
            key=lambda k: (
                counts[k],
                conf_sums[k] / max(1, counts[k]),
            ),
        )
        support_count = counts[best_label]
        avg_conf = conf_sums[best_label] / max(1, support_count)
        is_stable = (
            support_count >= self.min_votes
            and avg_conf >= self.min_stable_confidence
        )
        return StablePrediction(
            label=best_label if is_stable else self.unknown_label,
            confidence=avg_conf if is_stable else 0.0,
            support_count=support_count,
            window_size=len(self._window),
            is_stable=is_stable,
        )