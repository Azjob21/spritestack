"""
Fake plugin: /inpaint-region
============================
Deterministically alters a selected region based on prompt text.
"""

from __future__ import annotations

import colorsys
import hashlib
from typing import Iterable


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clean_hex_tokens(hex_str: str, expected_chars: int) -> list[str] | None:
    if not isinstance(hex_str, str):
        return None
    cleaned = "".join(ch for ch in hex_str if ch in "0123456789abcdefABCDEF")
    if len(cleaned) != expected_chars:
        return None
    return [cleaned[i : i + 8] for i in range(0, len(cleaned), 8)]


def _decode_pixels(region_hex: str, width: int, height: int) -> list[tuple[int, int, int, int]] | None:
    if width <= 0 or height <= 0:
        return []
    tokens = _clean_hex_tokens(region_hex, width * height * 8)
    if tokens is None:
        return None
    pixels: list[tuple[int, int, int, int]] = []
    try:
        for token in tokens:
            pixels.append(
                (
                    int(token[0:2], 16),
                    int(token[2:4], 16),
                    int(token[4:6], 16),
                    int(token[6:8], 16),
                )
            )
    except Exception:
        return None
    return pixels


def _encode_pixels(pixels: Iterable[tuple[int, int, int, int]]) -> str:
    return "".join(f"{r:02X}{g:02X}{b:02X}{a:02X}" for r, g, b, a in pixels)


def _quantize32(value: int) -> int:
    snapped = int(round(value / 32.0)) * 32
    if snapped < 0:
        return 0
    if snapped > 255:
        return 224
    return snapped


def _hue_shift_pixel(r: int, g: int, b: int, a: int, shift_degrees: int, palette_lock: bool) -> tuple[int, int, int, int]:
    if a <= 0:
        return (0, 0, 0, 0)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    h = (h + (shift_degrees / 360.0)) % 1.0
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    out = (
        int(round(nr * 255)),
        int(round(ng * 255)),
        int(round(nb * 255)),
        int(a),
    )
    if palette_lock:
        return tuple(_quantize32(c) for c in out)
    return out


def _placeholder(width: int, height: int) -> dict:
    w = max(0, int(width))
    h = max(0, int(height))
    return {
        "hex": "00000000" * (w * h),
        "width": w,
        "height": h,
        "model": "fake_inpaint_region_v1",
    }


async def run(data: dict) -> dict:
    try:
        payload = data if isinstance(data, dict) else {}
        selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else {}

        width = _safe_int(payload.get("width"), _safe_int(selection.get("width"), 0))
        height = _safe_int(payload.get("height"), _safe_int(selection.get("height"), 0))
        width = max(0, width)
        height = max(0, height)
        if width == 0 or height == 0:
            return _placeholder(width, height)

        prompt = str(payload.get("prompt") or "")
        palette_lock = bool(payload.get("palette_lock", False))
        region_hex = selection.get("region_hex")
        if not isinstance(region_hex, str):
            return _placeholder(width, height)

        pixels = _decode_pixels(region_hex, width, height)
        if pixels is None:
            return _placeholder(width, height)

        digest = hashlib.sha256(prompt.lower().encode("utf-8", errors="ignore")).digest()
        seed = int.from_bytes(digest[:4], "big")
        shift = (seed % 60) - 30

        out_pixels = [_hue_shift_pixel(r, g, b, a, shift, palette_lock) for r, g, b, a in pixels]
        return {
            "hex": _encode_pixels(out_pixels),
            "width": width,
            "height": height,
            "model": "fake_inpaint_region_v1",
        }
    except Exception:
        width = _safe_int((data or {}).get("width"), 0) if isinstance(data, dict) else 0
        height = _safe_int((data or {}).get("height"), 0) if isinstance(data, dict) else 0
        return _placeholder(width, height)
