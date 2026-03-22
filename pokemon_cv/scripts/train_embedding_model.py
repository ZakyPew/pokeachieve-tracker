#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import logging
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch import nn
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, transforms

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pokemon_cv.embed.model import CosineMetricHead, MetricEmbeddingNet
from pokemon_cv.utils.logging import setup_logging


@dataclass(slots=True)
class TrainState:
    best_val_top1: float = 0.0
    best_epoch: int = 0


class WebcamArtifactAugment:
    """Augmentations that mimic webcam capture artifacts."""

    def __init__(self, apply_prob: float = 0.9) -> None:
        self.apply_prob = float(apply_prob)

    def __call__(self, img: Image.Image) -> Image.Image:
        arr = np.array(img.convert("RGB"))
        if random.random() > self.apply_prob:
            return Image.fromarray(arr)

        arr = self._maybe_blur(arr)
        arr = self._maybe_noise(arr)
        arr = self._maybe_jpeg(arr)
        arr = self._maybe_gamma(arr)
        arr = self._maybe_perspective(arr)
        arr = self._maybe_occlusion(arr)
        return Image.fromarray(arr)

    @staticmethod
    def _maybe_blur(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.45:
            k = random.choice([3, 5])
            return cv2.GaussianBlur(arr, (k, k), sigmaX=0)
        return arr

    @staticmethod
    def _maybe_noise(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.50:
            sigma = random.uniform(3.0, 16.0)
            noise = np.random.normal(0.0, sigma, arr.shape).astype(np.float32)
            out = np.clip(arr.astype(np.float32) + noise, 0, 255)
            return out.astype(np.uint8)
        return arr

    @staticmethod
    def _maybe_jpeg(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.50:
            quality = random.randint(35, 95)
            ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if ok:
                decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                if decoded is not None:
                    return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
        return arr

    @staticmethod
    def _maybe_gamma(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.45:
            gamma = random.uniform(0.65, 1.45)
            lut = np.array([(i / 255.0) ** (1.0 / gamma) * 255 for i in range(256)], dtype=np.uint8)
            return cv2.LUT(arr, lut)
        return arr

    @staticmethod
    def _maybe_perspective(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.35:
            h, w = arr.shape[:2]
            d = 0.05
            src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
            jitter = np.float32(
                [
                    [random.uniform(-d, d) * w, random.uniform(-d, d) * h],
                    [random.uniform(-d, d) * w, random.uniform(-d, d) * h],
                    [random.uniform(-d, d) * w, random.uniform(-d, d) * h],
                    [random.uniform(-d, d) * w, random.uniform(-d, d) * h],
                ]
            )
            dst = src + jitter
            mat = cv2.getPerspectiveTransform(src, dst)
            return cv2.warpPerspective(arr, mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return arr

    @staticmethod
    def _maybe_occlusion(arr: np.ndarray) -> np.ndarray:
        if random.random() < 0.30:
            h, w = arr.shape[:2]
            occ_w = max(2, int(w * random.uniform(0.08, 0.24)))
            occ_h = max(2, int(h * random.uniform(0.08, 0.24)))
            x1 = random.randint(0, max(0, w - occ_w))
            y1 = random.randint(0, max(0, h - occ_h))
            color = np.random.randint(0, 256, size=(3,), dtype=np.uint8)
            arr[y1:y1 + occ_h, x1:x1 + occ_w] = color
        return arr


class TransformedSubset(Dataset[tuple[torch.Tensor, int]]):
    def __init__(self, base: datasets.ImageFolder, indices: list[int], transform: transforms.Compose) -> None:
        self.base = base
        self.indices = indices
        self.transform = transform

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int]:
        idx = self.indices[i]
        path, target = self.base.samples[idx]
        image = self.base.loader(path)
        image = self.transform(image)
        return image, target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train embedding model for Pokemon sprite matching")
    parser.add_argument("--data-dir", type=str, required=True, help="ImageFolder dataset root")
    parser.add_argument("--output", type=str, default="models/embedding/mobilenet_metric.pt")
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--embedding-dim", type=int, default=256)
    parser.add_argument("--input-size", type=int, default=128)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_transforms(input_size: int) -> tuple[transforms.Compose, transforms.Compose]:
    norm = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

    train_tf = transforms.Compose(
        [
            transforms.RandomResizedCrop(input_size, scale=(0.70, 1.0), ratio=(0.85, 1.15)),
            transforms.RandomPerspective(distortion_scale=0.2, p=0.35),
            transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.15, hue=0.03),
            WebcamArtifactAugment(apply_prob=0.9),
            transforms.ToTensor(),
            transforms.RandomErasing(p=0.2, scale=(0.02, 0.18), value="random"),
            norm,
        ]
    )
    val_tf = transforms.Compose(
        [
            transforms.Resize((input_size, input_size)),
            transforms.ToTensor(),
            norm,
        ]
    )
    return train_tf, val_tf


def split_indices(n: int, val_split: float, seed: int) -> tuple[list[int], list[int]]:
    idx = list(range(n))
    rng = random.Random(seed)
    rng.shuffle(idx)
    val_count = max(1, int(math.floor(n * val_split)))
    val_idx = idx[:val_count]
    train_idx = idx[val_count:]
    return train_idx, val_idx


def accuracy_topk(logits: torch.Tensor, targets: torch.Tensor, k: int = 1) -> float:
    if logits.numel() == 0:
        return 0.0
    topk = logits.topk(k, dim=1).indices
    hits = (topk == targets.unsqueeze(1)).any(dim=1).float().mean().item()
    return float(hits)


def train_one_epoch(
    model: MetricEmbeddingNet,
    head: CosineMetricHead,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    head.train()

    total_loss = 0.0
    total_top1 = 0.0
    batches = 0

    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        emb = model(images)
        logits = head(emb)
        loss = F.cross_entropy(logits, targets)

        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

        total_loss += float(loss.item())
        total_top1 += accuracy_topk(logits, targets, k=1)
        batches += 1

    if batches == 0:
        return 0.0, 0.0
    return total_loss / batches, total_top1 / batches


@torch.no_grad()
def validate(
    model: MetricEmbeddingNet,
    head: CosineMetricHead,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, float, float]:
    model.eval()
    head.eval()

    total_loss = 0.0
    total_top1 = 0.0
    total_top3 = 0.0
    batches = 0

    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        emb = model(images)
        logits = head(emb)
        loss = F.cross_entropy(logits, targets)

        total_loss += float(loss.item())
        total_top1 += accuracy_topk(logits, targets, k=1)
        total_top3 += accuracy_topk(logits, targets, k=min(3, logits.shape[1]))
        batches += 1

    if batches == 0:
        return 0.0, 0.0, 0.0
    return total_loss / batches, total_top1 / batches, total_top3 / batches


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("pokemon_cv.train_embedding")

    set_seed(args.seed)

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {data_dir}")

    base_dataset = datasets.ImageFolder(root=str(data_dir))
    if len(base_dataset) < 8:
        raise RuntimeError("Dataset too small; add more samples before training")

    num_classes = len(base_dataset.classes)
    if num_classes < 2:
        raise RuntimeError("Embedding training requires at least 2 classes")

    train_tf, val_tf = build_transforms(args.input_size)
    train_idx, val_idx = split_indices(len(base_dataset), args.val_split, args.seed)

    train_ds = TransformedSubset(base_dataset, train_idx, train_tf)
    val_ds = TransformedSubset(base_dataset, val_idx, val_tf)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=False,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=True,
        drop_last=False,
    )

    device = torch.device(args.device)
    model = MetricEmbeddingNet(embedding_dim=args.embedding_dim).to(device)
    head = CosineMetricHead(embedding_dim=args.embedding_dim, num_classes=num_classes).to(device)

    optimizer = AdamW(
        list(model.parameters()) + list(head.parameters()),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )

    state = TrainState()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "train_start | samples=%s | classes=%s | train=%s | val=%s | device=%s",
        len(base_dataset),
        num_classes,
        len(train_ds),
        len(val_ds),
        device,
    )

    for epoch in range(1, args.epochs + 1):
        train_loss, train_top1 = train_one_epoch(model, head, train_loader, optimizer, device)
        val_loss, val_top1, val_top3 = validate(model, head, val_loader, device)

        logger.info(
            "epoch=%s train_loss=%.4f train_top1=%.4f val_loss=%.4f val_top1=%.4f val_top3=%.4f",
            epoch,
            train_loss,
            train_top1,
            val_loss,
            val_top1,
            val_top3,
        )

        if val_top1 >= state.best_val_top1:
            state.best_val_top1 = val_top1
            state.best_epoch = epoch
            checkpoint = {
                "model_state": model.state_dict(),
                "head_state": head.state_dict(),
                "class_to_idx": copy.deepcopy(base_dataset.class_to_idx),
                "embedding_dim": args.embedding_dim,
                "input_size": args.input_size,
                "best_val_top1": state.best_val_top1,
                "epoch": epoch,
            }
            torch.save(checkpoint, out_path)
            logger.info("checkpoint_saved | path=%s | val_top1=%.4f", out_path, val_top1)

    logger.info(
        "train_done | best_epoch=%s | best_val_top1=%.4f | checkpoint=%s",
        state.best_epoch,
        state.best_val_top1,
        out_path,
    )


if __name__ == "__main__":
    main()