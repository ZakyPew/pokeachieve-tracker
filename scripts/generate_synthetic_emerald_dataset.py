#!/usr/bin/env python
from __future__ import annotations

import argparse
import io
import json
import random
import re
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat, ImageDraw


def parse_roi(raw: str, width: int, height: int) -> Tuple[int, int, int, int]:
    vals = [float(x.strip()) for x in str(raw).split(',')]
    if len(vals) != 4:
        raise ValueError(f"Invalid ROI: {raw}")
    x1 = int(round(vals[0] * width))
    y1 = int(round(vals[1] * height))
    x2 = int(round(vals[2] * width))
    y2 = int(round(vals[3] * height))
    x1 = max(0, min(width - 2, x1))
    y1 = max(0, min(height - 2, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def parse_enemy_box(raw: str, width: int, height: int) -> Tuple[int, int, int, int]:
    vals = [int(float(x.strip())) for x in str(raw).split(',')]
    if len(vals) != 4:
        raise ValueError(f"Invalid enemy box: {raw}")
    x1, y1, x2, y2 = vals
    x1 = max(0, min(width - 2, x1))
    y1 = max(0, min(height - 2, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def infer_enemy_box_from_roi(roi: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = roi
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    ex1 = x1 + int(w * 0.18)
    ex2 = x1 + int(w * 0.83)
    ey1 = y1 + int(h * 0.03)
    ey2 = y1 + int(h * 0.72)
    ex2 = max(ex1 + 8, ex2)
    ey2 = max(ey1 + 8, ey2)
    return ex1, ey1, ex2, ey2


def clear_enemy_region(frame: Image.Image, enemy_box: Tuple[int, int, int, int]) -> None:
    ex1, ey1, ex2, ey2 = enemy_box
    ew = max(4, ex2 - ex1)
    eh = max(4, ey2 - ey1)
    pad = max(6, int(min(ew, eh) * 0.10))

    sample_boxes = []
    if ex1 - pad > 0:
        sample_boxes.append((max(0, ex1 - pad), ey1, ex1, ey2))
    if ex2 + pad < frame.width:
        sample_boxes.append((ex2, ey1, min(frame.width, ex2 + pad), ey2))
    if ey1 - pad > 0:
        sample_boxes.append((ex1, max(0, ey1 - pad), ex2, ey1))
    if ey2 + pad < frame.height:
        sample_boxes.append((ex1, ey2, ex2, min(frame.height, ey2 + pad)))

    rgb_means: List[Tuple[float, float, float]] = []
    for box in sample_boxes:
        try:
            patch = frame.crop(box).convert("RGB")
            if patch.width > 0 and patch.height > 0:
                stat = ImageStat.Stat(patch)
                if stat.mean and len(stat.mean) >= 3:
                    rgb_means.append((float(stat.mean[0]), float(stat.mean[1]), float(stat.mean[2])))
        except Exception:
            continue

    if rgb_means:
        r = int(round(sum(v[0] for v in rgb_means) / float(len(rgb_means))))
        g = int(round(sum(v[1] for v in rgb_means) / float(len(rgb_means))))
        b = int(round(sum(v[2] for v in rgb_means) / float(len(rgb_means))))
    else:
        stat = ImageStat.Stat(frame.convert("RGB"))
        r, g, b = [int(round(x)) for x in stat.mean[:3]]

    fill = Image.new("RGBA", (ew, eh), (r, g, b, 255))
    blur_radius = max(2.0, min(12.0, float(min(ew, eh)) * 0.08))
    fill = fill.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    frame.alpha_composite(fill, (ex1, ey1))


def parse_prefixes(raw: str) -> List[str]:
    return [token.strip().lower() for token in str(raw).split(",") if token.strip()]


def list_species_sprites(sprites_dir: Path, prefixes: List[str]) -> Dict[int, Path]:
    if not prefixes:
        raise ValueError("At least one sprite prefix is required")

    chosen: Dict[int, Tuple[int, int, Path]] = {}
    pat = re.compile(r"^([a-z0-9_]+)_(\d+)(?:_shiny)?\.png$", re.IGNORECASE)
    rank_by_prefix = {prefix: idx for idx, prefix in enumerate(prefixes)}
    files = sorted(p for p in sprites_dir.glob("*.png") if p.is_file())

    for p in files:
        m = pat.match(p.name)
        if not m:
            continue
        prefix = str(m.group(1)).lower()
        if prefix not in rank_by_prefix:
            continue
        sid = int(m.group(2))
        if sid <= 0:
            continue

        is_shiny = p.stem.lower().endswith("_shiny")
        candidate = (int(rank_by_prefix[prefix]), 1 if is_shiny else 0, p)
        current = chosen.get(sid)
        if current is None:
            chosen[sid] = candidate
            continue
        if candidate[0] < current[0]:
            chosen[sid] = candidate
            continue
        if candidate[0] == current[0] and candidate[1] < current[1]:
            chosen[sid] = candidate

    return {int(sid): row[2] for sid, row in chosen.items()}


def trim_alpha(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = rgba.split()[-1]
    bbox = alpha.getbbox()
    if bbox:
        return rgba.crop(bbox)
    return rgba


def jitter_translate_rect(rect: Tuple[int, int, int, int], jitter_px: int, width: int, height: int) -> Tuple[int, int, int, int]:
    if int(jitter_px) <= 0:
        return rect
    x1, y1, x2, y2 = rect
    w = x2 - x1
    h = y2 - y1
    dx = random.randint(-int(jitter_px), int(jitter_px))
    dy = random.randint(-int(jitter_px), int(jitter_px))
    nx1 = max(0, min(width - w, x1 + dx))
    ny1 = max(0, min(height - h, y1 + dy))
    return nx1, ny1, nx1 + w, ny1 + h


def paste_sprite(frame: Image.Image, sprite: Image.Image, enemy_box: Tuple[int, int, int, int]) -> None:
    ex1, ey1, ex2, ey2 = enemy_box
    ew = max(8, ex2 - ex1)
    eh = max(8, ey2 - ey1)

    scale_jitter = random.uniform(0.78, 1.12)
    target_w = int(ew * random.uniform(0.38, 0.62) * scale_jitter)
    target_h = int(eh * random.uniform(0.42, 0.74) * scale_jitter)

    sw, sh = sprite.size
    if sw <= 0 or sh <= 0:
        return
    fit = min(float(target_w) / float(sw), float(target_h) / float(sh))
    fit = max(0.2, fit)
    nw = max(8, int(round(sw * fit)))
    nh = max(8, int(round(sh * fit)))

    spr = sprite.resize((nw, nh), Image.Resampling.BILINEAR)
    spr = ImageEnhance.Brightness(spr).enhance(random.uniform(0.85, 1.18))
    spr = ImageEnhance.Contrast(spr).enhance(random.uniform(0.90, 1.15))

    jitter_x = int(random.uniform(-0.08, 0.08) * ew)
    jitter_y = int(random.uniform(-0.10, 0.08) * eh)

    px = ex1 + (ew - nw) // 2 + jitter_x
    py = ey1 + int(eh * 0.96) - nh + jitter_y

    px = max(0, min(frame.width - nw, px))
    py = max(0, min(frame.height - nh, py))

    frame.alpha_composite(spr, (int(px), int(py)))


def apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    gamma = max(0.4, min(2.2, float(gamma)))
    inv = 1.0 / gamma
    lut = [int(((i / 255.0) ** inv) * 255.0) for i in range(256)]
    if img.mode == "RGB":
        return img.point(lut * 3)
    if img.mode == "RGBA":
        rgb = img.convert("RGB").point(lut * 3)
        out = rgb.convert("RGBA")
        out.putalpha(img.split()[-1])
        return out
    return img


def add_jpeg_artifact(img: Image.Image, quality_min: int, quality_max: int) -> Image.Image:
    q = random.randint(int(quality_min), int(quality_max))
    b = io.BytesIO()
    img.convert("RGB").save(b, format="JPEG", quality=q, optimize=False)
    b.seek(0)
    return Image.open(b).convert("RGBA")


def add_noise(img: Image.Image, amount: float) -> Image.Image:
    base = img.convert("RGB")
    noise = Image.effect_noise(base.size, random.uniform(6.0, 18.0)).convert("L")
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    mixed = Image.blend(base, noise_rgb, max(0.01, min(0.25, float(amount))))
    return mixed.convert("RGBA")


def add_occlusion(img: Image.Image, strength: str) -> Image.Image:
    if strength == "strong":
        max_boxes = 3
        alpha_range = (80, 180)
    else:
        max_boxes = 1
        alpha_range = (60, 120)

    out = img.convert("RGBA")
    d = ImageDraw.Draw(out, "RGBA")
    w, h = out.size
    for _ in range(random.randint(0, max_boxes)):
        bw = random.randint(max(6, w // 12), max(8, w // 4))
        bh = random.randint(max(6, h // 12), max(8, h // 4))
        x1 = random.randint(0, max(0, w - bw))
        y1 = random.randint(0, max(0, h - bh))
        col = random.randint(50, 220)
        a = random.randint(alpha_range[0], alpha_range[1])
        d.rectangle((x1, y1, x1 + bw, y1 + bh), fill=(col, col, col, a))
    return out


def build_scene_variant(base_template: Image.Image, augment_level: str) -> Image.Image:
    img = base_template.copy().convert("RGBA")
    if augment_level == "strong":
        if random.random() < 0.95:
            img = ImageEnhance.Brightness(img).enhance(random.uniform(0.70, 1.30))
        if random.random() < 0.95:
            img = ImageEnhance.Contrast(img).enhance(random.uniform(0.70, 1.35))
        if random.random() < 0.85:
            img = apply_gamma(img, random.uniform(0.7, 1.45))
        if random.random() < 0.70:
            img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.15, 1.8)))
        if random.random() < 0.60:
            img = add_noise(img, amount=random.uniform(0.03, 0.12))
    else:
        if random.random() < 0.55:
            img = ImageEnhance.Brightness(img).enhance(random.uniform(0.85, 1.20))
        if random.random() < 0.55:
            img = ImageEnhance.Contrast(img).enhance(random.uniform(0.85, 1.20))
        if random.random() < 0.40:
            img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.1, 1.0)))
    return img


def augment_frame(frame: Image.Image, augment_level: str) -> Image.Image:
    img = frame.convert("RGBA")
    if augment_level == "strong":
        if random.random() < 0.80:
            img = ImageEnhance.Brightness(img).enhance(random.uniform(0.68, 1.35))
        if random.random() < 0.80:
            img = ImageEnhance.Contrast(img).enhance(random.uniform(0.68, 1.40))
        if random.random() < 0.75:
            img = apply_gamma(img, random.uniform(0.65, 1.55))
        if random.random() < 0.70:
            img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.2, 2.0)))
        if random.random() < 0.60:
            img = add_noise(img, amount=random.uniform(0.04, 0.16))
        if random.random() < 0.55:
            img = add_jpeg_artifact(img, quality_min=20, quality_max=70)
        if random.random() < 0.50:
            img = add_occlusion(img, strength="strong")
    else:
        if random.random() < 0.65:
            img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.2, 1.1)))
        if random.random() < 0.45:
            img = ImageEnhance.Brightness(img).enhance(random.uniform(0.82, 1.20))
        if random.random() < 0.45:
            img = ImageEnhance.Contrast(img).enhance(random.uniform(0.85, 1.20))
        if random.random() < 0.30:
            img = add_noise(img, amount=random.uniform(0.02, 0.08))
        if random.random() < 0.25:
            img = add_jpeg_artifact(img, quality_min=45, quality_max=90)
        if random.random() < 0.20:
            img = add_occlusion(img, strength="mild")
    return img


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic sprite dataset from a base battle frame")
    parser.add_argument("--base-image", type=str, required=True)
    parser.add_argument("--sprites-dir", type=str, default=str(Path.home() / ".pokeachieve" / "sprites"))
    parser.add_argument("--output-dir", type=str, default="debug/ai_dataset/synthetic/labeled")
    parser.add_argument(
        "--sprite-prefixes",
        type=str,
        default="generation_iii_emerald,emerald",
        help="Comma-separated sprite filename prefixes, e.g. generation_ii_gold,generation_ii_silver",
    )
    parser.add_argument("--samples-per-species", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--sprite-roi", type=str, default="")
    parser.add_argument("--enemy-box", type=str, default="")
    parser.add_argument("--species-ids", type=str, default="", help="Optional comma-separated species IDs to include")
    parser.add_argument("--save-base-clean", type=str, default="", help="Optional path for cleaned base frame preview")
    parser.add_argument("--no-clear-enemy-region", action="store_true", help="Disable cleanup of existing sprite in base frame")
    parser.add_argument("--max-species", type=int, default=386)
    parser.add_argument("--augment-level", type=str, default="mild", choices=["mild", "strong"])
    parser.add_argument("--scene-variants", type=int, default=1)
    parser.add_argument("--roi-jitter-px", type=int, default=0)
    parser.add_argument("--enemy-jitter-px", type=int, default=0)
    parser.add_argument("--filename-prefix", type=str, default="syn")
    parser.add_argument("--append-manifest", action="store_true")
    parser.add_argument("--negative-ratio", type=float, default=0.35, help="Background negatives as fraction of generated positives")
    parser.add_argument("--negative-class", type=str, default="__background__", help="Class folder name for non-sprite negatives")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(int(args.seed))

    base_path = Path(args.base_image).resolve()
    if not base_path.exists():
        raise FileNotFoundError(f"Base image not found: {base_path}")

    cfg_path = Path.home() / ".pokeachieve" / "config.json"
    cfg: Dict[str, object] = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    base = Image.open(base_path).convert("RGBA")
    W, H = base.size

    roi_raw = str(args.sprite_roi or "").strip()
    if not roi_raw:
        profiles = cfg.get("video_obs_scene_profiles") if isinstance(cfg.get("video_obs_scene_profiles"), list) else []
        p0 = profiles[0] if profiles and isinstance(profiles[0], dict) else {}
        roi_raw = str(p0.get("sprite_roi") or cfg.get("video_sprite_roi") or "0.53,0.15,0.90,0.63")
    sprite_roi = parse_roi(roi_raw, W, H)

    enemy_raw = str(args.enemy_box or "").strip()
    if enemy_raw:
        enemy_box = parse_enemy_box(enemy_raw, W, H)
    else:
        enemy_box = infer_enemy_box_from_roi(sprite_roi)

    sprites_dir = Path(args.sprites_dir).expanduser().resolve()
    if not sprites_dir.exists():
        raise FileNotFoundError(f"Sprites dir not found: {sprites_dir}")

    prefixes = parse_prefixes(str(args.sprite_prefixes))
    if not prefixes:
        raise ValueError("No sprite prefixes provided")

    species_to_sprite = list_species_sprites(sprites_dir, prefixes)
    if not species_to_sprite:
        raise RuntimeError(f"No matching sprites found for prefixes={prefixes} in sprites directory: {sprites_dir}")

    include_species = {
        int(token.strip())
        for token in str(args.species_ids or "").split(",")
        if str(token).strip().isdigit()
    }

    base_template = base.copy()
    if not bool(args.no_clear_enemy_region):
        clear_enemy_region(base_template, enemy_box)

    scene_variants = max(1, int(args.scene_variants))
    base_templates: List[Image.Image] = [base_template]
    for _ in range(scene_variants - 1):
        base_templates.append(build_scene_variant(base_template, augment_level=str(args.augment_level)))

    if str(args.save_base_clean or "").strip():
        save_path = Path(str(args.save_base_clean)).expanduser().resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        base_template.convert("RGB").save(save_path)

    out_root = Path(args.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    manifest_rows: List[Dict[str, object]] = []
    generated = 0
    generated_negative = 0

    for sid in sorted(species_to_sprite.keys()):
        if int(sid) <= 0 or int(sid) > int(args.max_species):
            continue
        if include_species and int(sid) not in include_species:
            continue

        sprite_path = species_to_sprite[sid]
        spr = trim_alpha(Image.open(sprite_path))
        class_dir = out_root / str(int(sid))
        class_dir.mkdir(parents=True, exist_ok=True)

        for i in range(int(args.samples_per_species)):
            frame = random.choice(base_templates).copy()
            cur_enemy = jitter_translate_rect(enemy_box, int(args.enemy_jitter_px), W, H)
            paste_sprite(frame, spr, cur_enemy)
            frame = augment_frame(frame, augment_level=str(args.augment_level))

            cur_roi = jitter_translate_rect(sprite_roi, int(args.roi_jitter_px), W, H)
            x1, y1, x2, y2 = cur_roi
            crop = frame.crop((x1, y1, x2, y2)).convert("RGB")
            name = f"{str(args.filename_prefix)}_{int(sid)}_{i:03d}.png"
            out_path = class_dir / name
            crop.save(out_path)
            manifest_rows.append(
                {
                    "species_id": int(sid),
                    "class_label": str(int(sid)),
                    "sprite_prefixes": list(prefixes),
                    "sprite_source": str(sprite_path),
                    "output": str(out_path),
                    "base_image": str(base_path),
                    "sprite_roi": [int(v) for v in cur_roi],
                    "enemy_box": [int(v) for v in cur_enemy],
                    "augment_level": str(args.augment_level),
                    "scene_variants": int(scene_variants),
                }
            )
            generated += 1

    # Hard negatives: no sprite / transition-like / noisy frames.
    negative_ratio = max(0.0, min(3.0, float(args.negative_ratio)))
    negative_total = int(round(float(generated) * float(negative_ratio)))
    negative_class = str(args.negative_class or "__background__").strip() or "__background__"
    if negative_total > 0:
        neg_dir = out_root / negative_class
        neg_dir.mkdir(parents=True, exist_ok=True)
        for i in range(int(negative_total)):
            frame = random.choice(base_templates).copy()

            # Simulate pre-encounter flashes and noisy transitions.
            roll = random.random()
            if roll < 0.28:
                frame = ImageEnhance.Brightness(frame).enhance(random.uniform(1.25, 1.95))
            elif roll < 0.50:
                frame = ImageEnhance.Contrast(frame).enhance(random.uniform(0.65, 0.92))

            if random.random() < 0.35:
                # Crop near sprite ROI without placing a sprite.
                cur_roi = jitter_translate_rect(sprite_roi, int(max(2, args.roi_jitter_px or 0)) + 8, W, H)
            else:
                # Crop random region to diversify negatives.
                rw = max(16, min(W, int((sprite_roi[2] - sprite_roi[0]) * random.uniform(0.75, 1.25))))
                rh = max(16, min(H, int((sprite_roi[3] - sprite_roi[1]) * random.uniform(0.75, 1.25))))
                rx1 = random.randint(0, max(0, W - rw))
                ry1 = random.randint(0, max(0, H - rh))
                cur_roi = (rx1, ry1, rx1 + rw, ry1 + rh)

            frame = augment_frame(frame, augment_level=str(args.augment_level))
            x1, y1, x2, y2 = cur_roi
            crop = frame.crop((x1, y1, x2, y2)).convert("RGB")
            name = f"{str(args.filename_prefix)}_bg_{i:03d}.png"
            out_path = neg_dir / name
            crop.save(out_path)
            manifest_rows.append(
                {
                    "species_id": 0,
                    "class_label": str(negative_class),
                    "sprite_prefixes": list(prefixes),
                    "sprite_source": "",
                    "output": str(out_path),
                    "base_image": str(base_path),
                    "sprite_roi": [int(v) for v in cur_roi],
                    "enemy_box": [int(v) for v in enemy_box],
                    "augment_level": str(args.augment_level),
                    "scene_variants": int(scene_variants),
                    "negative": True,
                }
            )
            generated_negative += 1

    manifest_path = out_root.parent / "synthetic_manifest.jsonl"
    mode = "a" if bool(args.append_manifest) else "w"
    with manifest_path.open(mode, encoding="utf-8") as f:
        for row in manifest_rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")

    print(
        json.dumps(
            {
                "generated_images": int(generated),
                "generated_negative_images": int(generated_negative),
                "species_count": int(len({int(r["species_id"]) for r in manifest_rows})),
                "output_dir": str(out_root),
                "manifest": str(manifest_path),
                "sprite_prefixes": list(prefixes),
                "sprite_roi": list(sprite_roi),
                "enemy_box": list(enemy_box),
                "base_cleaned": bool(not args.no_clear_enemy_region),
                "augment_level": str(args.augment_level),
                "scene_variants": int(scene_variants),
                "filename_prefix": str(args.filename_prefix),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
