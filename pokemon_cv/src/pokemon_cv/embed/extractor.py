from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch

from pokemon_cv.embed.model import MetricEmbeddingNet


class EmbeddingExtractor:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.logger = logging.getLogger("pokemon_cv.embed")
        self.model_path = Path(str(cfg.get("model_path", "")))
        self.embedding_dim = int(cfg.get("embedding_dim", 256))
        self.input_size = int(cfg.get("input_size", 128))
        self.device = torch.device(str(cfg.get("device", "cpu")))
        self.allow_untrained = bool(cfg.get("allow_untrained", False))

        self.model = MetricEmbeddingNet(embedding_dim=self.embedding_dim)
        self.model.to(self.device)
        self.model.eval()

        if self.model_path.exists():
            state = torch.load(self.model_path, map_location=self.device)
            if isinstance(state, dict) and "model_state" in state:
                self.model.load_state_dict(state["model_state"], strict=False)
            elif isinstance(state, dict):
                self.model.load_state_dict(state, strict=False)
            else:
                raise ValueError(f"Unsupported embedding checkpoint format: {self.model_path}")
            self.logger.info("embedding_checkpoint_loaded | path=%s", self.model_path)
        elif self.allow_untrained:
            self.logger.warning(
                "embedding_checkpoint_missing | path=%s | using_untrained_model=true",
                self.model_path,
            )
        else:
            raise FileNotFoundError(
                "Embedding checkpoint not found: "
                f"{self.model_path}. Train with scripts/train_embedding_model.py or set embedding.allow_untrained=true."
            )

    def embed(self, crop_bgr: np.ndarray) -> np.ndarray:
        if crop_bgr is None or crop_bgr.size == 0:
            raise ValueError("Cannot embed empty crop")
        inp = self._preprocess(crop_bgr)
        with torch.no_grad():
            emb = self.model(inp).detach().cpu().numpy()[0]
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb.astype(np.float32)

    def _preprocess(self, crop_bgr: np.ndarray) -> torch.Tensor:
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR)
        arr = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        chw = np.transpose(arr, (2, 0, 1))
        tensor = torch.from_numpy(chw).unsqueeze(0).to(self.device)
        return tensor