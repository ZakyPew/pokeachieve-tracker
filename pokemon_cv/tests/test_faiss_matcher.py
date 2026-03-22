from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from pokemon_cv.match.faiss_matcher import FaissSpeciesMatcher


def _build_tmp_index(tmp_path: Path) -> tuple[Path, Path]:
    index_path = tmp_path / "index.faiss"
    meta_path = tmp_path / "meta.json"

    # Two orthonormal vectors in cosine space.
    vecs = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    faiss.write_index(index, str(index_path))

    metadata = [
        {"label": "nincada", "species": "nincada", "form": None, "shiny": False, "path": "a.png"},
        {"label": "taillow", "species": "taillow", "form": None, "shiny": False, "path": "b.png"},
    ]
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    return index_path, meta_path


def test_faiss_matcher_accepts_clear_match(tmp_path: Path) -> None:
    index_path, meta_path = _build_tmp_index(tmp_path)
    matcher = FaissSpeciesMatcher(
        {
            "faiss_index_path": str(index_path),
            "metadata_path": str(meta_path),
            "top_k": 2,
            "similarity_threshold": 0.62,
            "margin_threshold": 0.07,
            "unknown_label": "unknown",
        }
    )

    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    label, conf, topk, rejected, reason = matcher.classify(query)
    assert rejected is False
    assert reason == "accepted"
    assert label == "nincada"
    assert conf > 0.9
    assert len(topk) == 2


def test_faiss_matcher_rejects_ambiguous(tmp_path: Path) -> None:
    index_path, meta_path = _build_tmp_index(tmp_path)
    matcher = FaissSpeciesMatcher(
        {
            "faiss_index_path": str(index_path),
            "metadata_path": str(meta_path),
            "top_k": 2,
            "similarity_threshold": 0.4,
            "margin_threshold": 0.2,
            "unknown_label": "unknown",
        }
    )

    query = np.array([0.70710677, 0.70710677, 0.0, 0.0], dtype=np.float32)
    label, _conf, _topk, rejected, reason = matcher.classify(query)
    assert rejected is True
    assert reason == "ambiguous_margin"
    assert label == "unknown"