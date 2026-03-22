#!/usr/bin/env python
from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import torch
from PIL import Image
from transformers import ViTForImageClassification, ViTImageProcessor
from ultralytics import YOLO


@dataclass
class FramePacket:
    ok: bool
    frame: Optional[object]
    ts: float


class VideoCaptureAsync:
    def __init__(self, src: int = 0):
        self.cap = cv2.VideoCapture(int(src))
        ok, frame = self.cap.read()
        self.packet = FramePacket(ok=bool(ok), frame=frame, ts=time.monotonic())
        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self) -> "VideoCaptureAsync":
        if self.running:
            return self
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self) -> None:
        while self.running:
            ok, frame = self.cap.read()
            with self.lock:
                self.packet = FramePacket(ok=bool(ok), frame=frame, ts=time.monotonic())

    def read(self) -> FramePacket:
        with self.lock:
            pkt = self.packet
            frame_copy = None if pkt.frame is None else pkt.frame.copy()
            return FramePacket(ok=bool(pkt.ok), frame=frame_copy, ts=float(pkt.ts))

    def stop(self) -> None:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.5)
        self.cap.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Async YOLO+ViT Pokemon demo")
    parser.add_argument("--source", type=int, default=0, help="OpenCV camera source id")
    parser.add_argument("--yolo", type=str, default="best.pt", help="Path to custom YOLO localizer weights")
    parser.add_argument("--model-id", type=str, default="skshmjn/Pokemon-classifier-gen9-1025")
    parser.add_argument("--det-conf", type=float, default=0.50)
    parser.add_argument("--cls-conf", type=float, default=0.70)
    parser.add_argument("--device", type=str, default="")
    return parser.parse_args()


def clamp_box(box, w: int, h: int) -> Tuple[int, int, int, int]:
    x1 = max(0, min(int(w - 1), int(box[0])))
    y1 = max(0, min(int(h - 1), int(box[1])))
    x2 = max(int(x1 + 1), min(int(w), int(box[2])))
    y2 = max(int(y1 + 1), min(int(h), int(box[3])))
    return x1, y1, x2, y2


def main() -> None:
    args = parse_args()

    yolo_path = Path(str(args.yolo)).expanduser()
    if not yolo_path.exists():
        raise SystemExit(f"YOLO weights not found: {yolo_path}")

    detector = YOLO(str(yolo_path))

    device = str(args.device).strip() or ("cuda" if torch.cuda.is_available() else "cpu")
    classifier = ViTForImageClassification.from_pretrained(str(args.model_id)).to(device)
    classifier.eval()
    processor = ViTImageProcessor.from_pretrained(str(args.model_id))

    cap = VideoCaptureAsync(int(args.source)).start()

    try:
        while True:
            pkt = cap.read()
            if (not pkt.ok) or pkt.frame is None:
                continue

            frame = pkt.frame
            fh, fw = frame.shape[:2]

            results = detector.predict(frame, conf=float(args.det_conf), verbose=False)
            for result in results:
                boxes = getattr(result, "boxes", None)
                xyxy = getattr(boxes, "xyxy", None) if boxes is not None else None
                if xyxy is None:
                    continue
                arr = xyxy.detach().cpu().numpy() if hasattr(xyxy, "detach") else xyxy.cpu().numpy()
                for box in arr:
                    if len(box) < 4:
                        continue
                    x1, y1, x2, y2 = clamp_box(box[:4], fw, fh)
                    roi = frame[y1:y2, x1:x2]
                    if roi is None or roi.size == 0:
                        continue

                    roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(roi_rgb)
                    inputs = processor(images=pil_img, return_tensors="pt")
                    inputs = {k: v.to(device) for k, v in inputs.items()}
                    with torch.no_grad():
                        outputs = classifier(**inputs)
                    probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                    conf = float(torch.max(probs).item())
                    pred = int(torch.argmax(probs).item())

                    if conf >= float(args.cls_conf):
                        label = str(classifier.config.id2label.get(pred, f"class_{pred}"))
                        tag = f"{label} [{conf:.2f}]"
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(
                            frame,
                            tag,
                            (x1, max(12, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0, 255, 0),
                            2,
                        )

            cv2.imshow("Pokemon YOLO+ViT Async Demo", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
