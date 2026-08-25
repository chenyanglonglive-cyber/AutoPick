from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PREPROCESS_VERSION = "embed-1024-jpeg82-v1"


@dataclass
class ImageInspection:
    width: int
    height: int
    byte_size: int
    sha256: str
    dhash: str
    blur_score: float
    dark_ratio: float
    bright_ratio: float
    quality_score: float
    flags: list[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dhash(image: Image.Image) -> str:
    pixels = np.asarray(image.convert("L").resize((9, 8)), dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    return f"{sum(int(bit) << index for index, bit in enumerate(bits)):016x}"


def dhash_bytes(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as opened:
        return _dhash(ImageOps.exif_transpose(opened).convert("RGB"))


def inspect_image(path: Path) -> ImageInspection:
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            gray = np.asarray(image.convert("L").resize((min(1024, width), max(1, round(height * min(1024, width) / width)))))
            gray_float = gray.astype(np.float32)
            # A lightweight, deterministic sharpness proxy; no local AI model is used.
            laplace_like = np.diff(gray_float, n=2, axis=0)
            blur_score = float(np.var(laplace_like))
            dark_ratio = float(np.mean(gray < 25))
            bright_ratio = float(np.mean(gray > 245))
            flags: list[str] = []
            if max(width, height) < 800:
                flags.append("low_resolution")
            if blur_score < 35:
                flags.append("possibly_blurry")
            if dark_ratio > 0.35:
                flags.append("too_dark")
            if bright_ratio > 0.35:
                flags.append("overexposed")
            ratio = max(width, height) / max(1, min(width, height))
            if ratio > 3.0:
                flags.append("unusual_aspect_ratio")
            quality = 1.0
            quality -= min(0.35, dark_ratio * 0.4 + bright_ratio * 0.4)
            quality -= 0.15 if "possibly_blurry" in flags else 0.0
            quality -= 0.12 if "low_resolution" in flags else 0.0
            return ImageInspection(
                width=width,
                height=height,
                byte_size=path.stat().st_size,
                sha256=sha256_file(path),
                dhash=_dhash(image),
                blur_score=blur_score,
                dark_ratio=dark_ratio,
                bright_ratio=bright_ratio,
                quality_score=max(0.0, round(quality, 4)),
                flags=flags,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"Unreadable image: {path.name}") from exc


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()


def make_derivative(source: Path, destination: Path, long_edge: int, quality: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
        image.save(destination, "JPEG", quality=quality, optimize=True, progressive=True)


def estimated_visual_tokens(width: int, height: int, long_edge: int = 1024) -> int:
    scale = min(1.0, long_edge / max(width, height))
    scaled_width, scaled_height = width * scale, height * scale
    return math.ceil(scaled_width * scaled_height / (32 * 32)) + 2


def flags_json(flags: list[str]) -> str:
    return json.dumps(flags, ensure_ascii=False)
