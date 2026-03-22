#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import faiss
import numpy as np
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.app.pipeline import resolve_runtime_paths
from pokemon_cv.config import load_config
from pokemon_cv.embed.dataset import iter_image_files, parse_reference_sample
from pokemon_cv.embed.extractor import EmbeddingExtractor
from pokemon_cv.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS index from reference sprites")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--references-dir", type=str, required=True, help="Directory containing reference sprite images")
    parser.add_argument("--output-index", type=str, help="Output FAISS index path")
    parser.add_argument("--output-metadata", type=str, help="Output metadata JSON path")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.build_index")

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)
    cfg = resolve_runtime_paths(cfg, config_path=cfg_path)

    references_dir = Path(args.references_dir).resolve()
    if not references_dir.exists():
        raise FileNotFoundError(f"References directory not found: {references_dir}")

    matching_cfg = cfg.get("matching", {})
    output_index = Path(args.output_index).resolve() if args.output_index else Path(str(matching_cfg.get("faiss_index_path", "artifacts/reference_index.faiss"))).resolve()
    output_meta = Path(args.output_metadata).resolve() if args.output_metadata else Path(str(matching_cfg.get("metadata_path", "artifacts/reference_metadata.json"))).resolve()

    output_index.parent.mkdir(parents=True, exist_ok=True)
    output_meta.parent.mkdir(parents=True, exist_ok=True)

    extractor = EmbeddingExtractor(cfg.get("embedding", {}))

    image_paths = iter_image_files(references_dir)
    if not image_paths:
        raise RuntimeError(f"No reference images found under {references_dir}")

    vectors: list[np.ndarray] = []
    metadata: list[dict[str, object]] = []

    for image_path in tqdm(image_paths, desc="embedding", unit="img"):
        sample = parse_reference_sample(references_dir, image_path)
        img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            logger.warning("skip_invalid_image | path=%s", image_path)
            continue

        emb = extractor.embed(img)
        vectors.append(emb.astype(np.float32))
        metadata.append(
            {
                "label": sample.label,
                "species": sample.species,
                "form": sample.form,
                "shiny": sample.shiny,
                "path": str(image_path),
            }
        )

    if not vectors:
        raise RuntimeError("No embeddings were generated; check reference images and model checkpoint")

    matrix = np.vstack(vectors).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.clip(norms, 1e-12, None)

    dim = matrix.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(matrix)

    faiss.write_index(index, str(output_index))
    output_meta.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info(
        "reference_index_built | vectors=%s | dim=%s | index=%s | metadata=%s",
        matrix.shape[0],
        dim,
        output_index,
        output_meta,
    )


if __name__ == "__main__":
    main()