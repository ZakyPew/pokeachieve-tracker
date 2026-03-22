#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import torch
import torch.nn.functional as F
from torch import nn
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, transforms


@dataclass(slots=True)
class TrainState:
    best_val_top1: float = 0.0
    best_epoch: int = 0


class SpriteClassifier(nn.Module):
    """Compact grayscale CNN that matches tracker ONNX input expectations (N,1,H,W)."""

    def __init__(self, num_classes: int, input_size: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 24, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(24),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 48, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(48),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(48, 96, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(96),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(96, 128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(p=0.25),
            nn.Linear(128, max(16, int(num_classes))),
        )
        self.input_size = int(input_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        return self.head(x)


class SubsetWithTransform(Dataset[tuple[torch.Tensor, int]]):
    def __init__(self, base: datasets.ImageFolder, indices: list[int], tf: transforms.Compose) -> None:
        self.base = base
        self.indices = indices
        self.tf = tf

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        item_idx = self.indices[idx]
        path, target = self.base.samples[item_idx]
        image = self.base.loader(path)
        return self.tf(image), int(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train tracker ONNX species classifier from ImageFolder data")
    parser.add_argument("--data-dir", type=str, required=True, help="ImageFolder root (class folders should be species IDs)")
    parser.add_argument("--output-onnx", type=str, default="models/tracker_species.onnx")
    parser.add_argument("--output-labels", type=str, default="models/tracker_species_labels.json")
    parser.add_argument("--output-checkpoint", type=str, default="models/tracker_species.pt")
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--input-size", type=int, default=64)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def split_indices(n: int, val_split: float, seed: int) -> tuple[list[int], list[int]]:
    idx = list(range(n))
    rng = random.Random(seed)
    rng.shuffle(idx)
    val_count = max(1, int(math.floor(float(n) * float(val_split))))
    return idx[val_count:], idx[:val_count]


def topk_acc(logits: torch.Tensor, y: torch.Tensor, k: int) -> float:
    topk = logits.topk(k=min(k, logits.shape[1]), dim=1).indices
    return float((topk == y.unsqueeze(1)).any(dim=1).float().mean().item())


def species_id_map(class_to_idx: Dict[str, int]) -> Dict[int, int]:
    idx_to_species: Dict[int, int] = {}
    negative_labels = {"__background__", "background", "__negative__", "negative", "no_pokemon", "nopokemon", "unknown", "none"}
    for label, idx in class_to_idx.items():
        token = str(label).strip()
        if str(token).strip().lower() in negative_labels:
            idx_to_species[int(idx)] = 0
            continue
        try:
            sid = int(token)
        except Exception:
            m = re.match(r"^(\d+)", token)
            if not m:
                raise ValueError(f"Class '{label}' must be numeric species ID (e.g., 290)")
            sid = int(m.group(1))
        idx_to_species[int(idx)] = int(sid)
    return idx_to_species


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("train_tracker_species_onnx")

    set_seed(int(args.seed))

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {data_dir}")

    base = datasets.ImageFolder(root=str(data_dir))
    if len(base) < 20:
        raise RuntimeError("Dataset too small (need at least 20 images)")
    if len(base.classes) < 2:
        raise RuntimeError("Need at least 2 classes for training")

    idx_to_species = species_id_map(base.class_to_idx)

    train_tf = transforms.Compose(
        [
            transforms.Grayscale(num_output_channels=1),
            transforms.RandomResizedCrop(int(args.input_size), scale=(0.75, 1.0), ratio=(0.90, 1.12)),
            transforms.ColorJitter(brightness=0.30, contrast=0.30),
            transforms.ToTensor(),
        ]
    )
    val_tf = transforms.Compose(
        [
            transforms.Grayscale(num_output_channels=1),
            transforms.Resize((int(args.input_size), int(args.input_size))),
            transforms.ToTensor(),
        ]
    )

    train_idx, val_idx = split_indices(len(base), float(args.val_split), int(args.seed))
    train_ds = SubsetWithTransform(base, train_idx, train_tf)
    val_ds = SubsetWithTransform(base, val_idx, val_tf)

    train_loader = DataLoader(train_ds, batch_size=int(args.batch_size), shuffle=True, num_workers=int(args.num_workers), pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=int(args.batch_size), shuffle=False, num_workers=int(args.num_workers), pin_memory=True)

    device = torch.device(str(args.device))
    model = SpriteClassifier(num_classes=len(base.classes), input_size=int(args.input_size)).to(device)
    optimizer = AdamW(model.parameters(), lr=float(args.lr), weight_decay=float(args.weight_decay))

    state = TrainState()
    ckpt_path = Path(args.output_checkpoint).resolve()
    onnx_path = Path(args.output_onnx).resolve()
    labels_path = Path(args.output_labels).resolve()
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("train_start | samples=%s | classes=%s | train=%s | val=%s", len(base), len(base.classes), len(train_ds), len(val_ds))

    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        train_loss = 0.0
        train_top1 = 0.0
        train_batches = 0
        for x, y in train_loader:
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            logits = model(x)
            loss = F.cross_entropy(logits, y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())
            train_top1 += topk_acc(logits, y, 1)
            train_batches += 1

        model.eval()
        val_loss = 0.0
        val_top1 = 0.0
        val_top3 = 0.0
        val_batches = 0
        with torch.no_grad():
            for x, y in val_loader:
                x = x.to(device, non_blocking=True)
                y = y.to(device, non_blocking=True)
                logits = model(x)
                loss = F.cross_entropy(logits, y)
                val_loss += float(loss.item())
                val_top1 += topk_acc(logits, y, 1)
                val_top3 += topk_acc(logits, y, 3)
                val_batches += 1

        if train_batches > 0:
            train_loss /= float(train_batches)
            train_top1 /= float(train_batches)
        if val_batches > 0:
            val_loss /= float(val_batches)
            val_top1 /= float(val_batches)
            val_top3 /= float(val_batches)

        logger.info(
            "epoch=%s train_loss=%.4f train_top1=%.4f val_loss=%.4f val_top1=%.4f val_top3=%.4f",
            epoch,
            train_loss,
            train_top1,
            val_loss,
            val_top1,
            val_top3,
        )

        if float(val_top1) >= float(state.best_val_top1):
            state.best_val_top1 = float(val_top1)
            state.best_epoch = int(epoch)
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "class_to_idx": dict(base.class_to_idx),
                    "idx_to_species": dict(idx_to_species),
                    "input_size": int(args.input_size),
                    "best_val_top1": float(state.best_val_top1),
                    "epoch": int(epoch),
                },
                ckpt_path,
            )

    if not ckpt_path.exists():
        raise RuntimeError("No checkpoint produced")

    checkpoint = torch.load(ckpt_path, map_location="cpu")
    model = SpriteClassifier(num_classes=len(base.classes), input_size=int(args.input_size)).to("cpu")
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    dummy = torch.zeros(1, 1, int(args.input_size), int(args.input_size), dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=18,
    )

    labels_payload = {str(int(k)): int(v) for k, v in dict(idx_to_species).items()}
    labels_path.write_text(json.dumps(labels_payload, indent=2), encoding="utf-8")

    logger.info(
        "train_done | best_epoch=%s | best_val_top1=%.4f | onnx=%s | labels=%s",
        state.best_epoch,
        state.best_val_top1,
        onnx_path,
        labels_path,
    )


if __name__ == "__main__":
    main()


