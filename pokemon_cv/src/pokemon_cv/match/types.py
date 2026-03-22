from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(slots=True)
class Candidate:
    box_xyxy: tuple[int, int, int, int]
    score: float
    source: str


@dataclass(slots=True)
class MatchResult:
    label: str
    species: str
    form: str | None
    shiny: bool
    similarity: float
    confidence: float


@dataclass(slots=True)
class CandidatePrediction:
    candidate: Candidate
    top_k: List[MatchResult] = field(default_factory=list)
    rejected_unknown: bool = False
    raw_label: str = "unknown"
    raw_confidence: float = 0.0


@dataclass(slots=True)
class StablePrediction:
    label: str
    confidence: float
    support_count: int
    window_size: int
    is_stable: bool
