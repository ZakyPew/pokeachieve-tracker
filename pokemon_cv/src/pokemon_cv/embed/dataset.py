from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass(slots=True)
class ReferenceSample:
    image_path: Path
    species: str
    form: str | None
    shiny: bool
    label: str


def iter_image_files(root_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in root_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            files.append(path)
    files.sort()
    return files


def parse_reference_sample(root_dir: Path, image_path: Path) -> ReferenceSample:
    rel = image_path.resolve().relative_to(root_dir.resolve())
    parts = [p for p in rel.parts]
    stem = image_path.stem

    species = "unknown"
    form: str | None = None
    shiny = False

    if len(parts) >= 2:
        species = _clean_token(parts[0])
        form_parts = [_clean_token(p) for p in parts[1:-1]]
        form_parts = [p for p in form_parts if p and p not in {"normal", "sprites", "forms"}]
        if "shiny" in form_parts:
            shiny = True
            form_parts = [p for p in form_parts if p != "shiny"]
        form = ":".join(form_parts) if form_parts else None
    else:
        # fallback to filename pattern: species__form__shiny.png
        name_tokens = [_clean_token(t) for t in stem.split("__") if t]
        if name_tokens:
            species = name_tokens[0]
        for token in name_tokens[1:]:
            if token == "shiny":
                shiny = True
            elif token != "normal":
                form = token if not form else f"{form}:{token}"

    if "shiny" in stem.lower():
        shiny = True

    label = build_label(species=species, form=form, shiny=shiny)
    return ReferenceSample(
        image_path=image_path,
        species=species,
        form=form,
        shiny=shiny,
        label=label,
    )


def build_label(species: str, form: str | None = None, shiny: bool = False) -> str:
    s = _clean_token(species)
    label = s
    if form:
        label = f"{label}:{_clean_token(form)}"
    if shiny:
        label = f"{label}:shiny"
    return label


def _clean_token(text: str) -> str:
    return str(text).strip().lower().replace(" ", "_")