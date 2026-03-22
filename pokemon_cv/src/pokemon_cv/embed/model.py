from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as tvm


class MetricEmbeddingNet(nn.Module):
    def __init__(self, embedding_dim: int = 256) -> None:
        super().__init__()
        backbone = tvm.mobilenet_v3_small(weights=None)
        self.features = backbone.features
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        last_ch = 576
        self.projector = nn.Sequential(
            nn.Linear(last_ch, 512),
            nn.Hardswish(),
            nn.Dropout(p=0.1),
            nn.Linear(512, embedding_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.features(x)
        pooled = self.pool(feat).flatten(1)
        emb = self.projector(pooled)
        return F.normalize(emb, dim=1)


class CosineMetricHead(nn.Module):
    """Classification head used during embedding training."""

    def __init__(self, embedding_dim: int, num_classes: int, scale: float = 24.0) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.randn(num_classes, embedding_dim))
        self.scale = float(scale)

    def forward(self, emb: torch.Tensor) -> torch.Tensor:
        w = F.normalize(self.weight, dim=1)
        logits = torch.matmul(emb, w.T) * self.scale
        return logits
