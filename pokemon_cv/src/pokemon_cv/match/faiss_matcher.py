from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from pokemon_cv.match.logic import decide_unknown, similarity_to_confidence
from pokemon_cv.match.types import MatchResult


@dataclass(slots=True)
class ReferenceMeta:
    label: str
    species: str
    form: str | None
    shiny: bool
    path: str


class FaissSpeciesMatcher:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.index_path = Path(str(cfg.get("faiss_index_path", "")))
        self.metadata_path = Path(str(cfg.get("metadata_path", "")))
        self.top_k = int(cfg.get("top_k", 5))
        self.similarity_threshold = float(cfg.get("similarity_threshold", 0.62))
        self.margin_threshold = float(cfg.get("margin_threshold", 0.07))
        self.unknown_label = str(cfg.get("unknown_label", "unknown"))

        if not self.index_path.exists():
            raise FileNotFoundError(
                f"FAISS index not found: {self.index_path}. Build with scripts/build_reference_index.py"
            )
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata not found: {self.metadata_path}. Build with scripts/build_reference_index.py"
            )

        self.index = faiss.read_index(str(self.index_path))
        self.metadata = self._load_metadata(self.metadata_path)

    def match_top_k(self, embedding: np.ndarray, top_k: int | None = None) -> list[MatchResult]:
        if embedding.ndim != 1:
            raise ValueError("Embedding must be shape [D]")
        vec = embedding.astype(np.float32)[None, :]
        k = int(top_k or self.top_k)
        sims, idxs = self.index.search(vec, k)

        out: list[MatchResult] = []
        for sim, idx in zip(sims[0], idxs[0]):
            if int(idx) < 0 or int(idx) >= len(self.metadata):
                continue
            meta = self.metadata[int(idx)]
            score = float(sim)
            out.append(
                MatchResult(
                    label=meta.label,
                    species=meta.species,
                    form=meta.form,
                    shiny=meta.shiny,
                    similarity=score,
                    confidence=similarity_to_confidence(score),
                )
            )
        return out

    def classify(self, embedding: np.ndarray, top_k: int | None = None) -> tuple[str, float, list[MatchResult], bool, str]:
        top_matches = self.match_top_k(embedding, top_k=top_k)
        if not top_matches:
            return self.unknown_label, 0.0, [], True, "no_neighbors"

        top1 = top_matches[0]
        top2_sim = top_matches[1].similarity if len(top_matches) > 1 else None
        decision = decide_unknown(
            top1_similarity=top1.similarity,
            top2_similarity=top2_sim,
            similarity_threshold=self.similarity_threshold,
            margin_threshold=self.margin_threshold,
        )
        if decision.is_unknown:
            return self.unknown_label, top1.confidence, top_matches, True, decision.reason
        return top1.label, top1.confidence, top_matches, False, decision.reason

    @staticmethod
    def _load_metadata(path: Path) -> list[ReferenceMeta]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"Metadata file must contain a list: {path}")
        items: list[ReferenceMeta] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            items.append(
                ReferenceMeta(
                    label=str(row.get("label", "unknown")),
                    species=str(row.get("species", "unknown")),
                    form=(None if row.get("form") in (None, "") else str(row.get("form"))),
                    shiny=bool(row.get("shiny", False)),
                    path=str(row.get("path", "")),
                )
            )
        return items
