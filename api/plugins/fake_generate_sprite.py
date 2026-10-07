"""
Fake plugin: /generate-sprite
==============================
Generates a deterministic pixel-art sprite WITHOUT a real diffusion model.

Algorithm
---------
1. Hash the prompt string into a seed.
2. Use the seed to build a tiny palette (3-5 colours).
3. Paint a simple symmetric pattern that differs per prompt.
4. Return the result as a hex string (RRGGBBAA × w × h) — the format the
   Qt app's _decode_ai_image() → _tokens_to_image() pipeline expects.

This gives unique-looking outputs for each prompt while being 100% repeatable,
which is ideal for regression testing UI behaviour before the real model lands.
"""

from __future__ import annotations

import hashlib
import math
import random


def _prompt_seed(prompt: str) -> int:
    digest = hashlib.sha256(prompt.lower().encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _make_palette(rng: random.Random) -> list[tuple[int, int, int, int]]:
    """Return 4-6 RGBA colours: background (transparent) + body colours."""
    transparent = (0, 0, 0, 0)
    base_h = rng.random()
    palette = [transparent]
    for i in range(4):
        h = (base_h + i * 0.15) % 1.0
        r, g, b = _hsv_to_rgb(h, 0.6 + rng.random() * 0.3, 0.6 + rng.random() * 0.3)
        palette.append((r, g, b, 255))
    return palette


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    sector = i % 6
    if sector == 0:
        r, g, b = v, t, p
    elif sector == 1:
        r, g, b = q, v, p
    elif sector == 2:
        r, g, b = p, v, t
    elif sector == 3:
        r, g, b = p, q, v
    elif sector == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


def _generate_sprite_data(
    prompt: str,
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    """Return a flat list of RGBA tuples, row-major."""
    seed = _prompt_seed(prompt)
    rng = random.Random(seed)
    palette = _make_palette(rng)

    # Half-width for symmetry (pixel art sprites are usually mirrored)
    half_w = (width + 1) // 2

    # Build left half pixel-by-pixel using noise-influenced rules
    left_grid: list[list[int]] = []  # palette indices
    for y in range(height):
        row = []
        for x in range(half_w):
            # Skip border region → stays transparent → creates silhouette
            is_border = (x == 0 and y == 0) or (x == 0 and y == height - 1)
            if is_border:
                row.append(0)
                continue
            # Use a cheap hash to decide fill
            cell_seed = (seed ^ (y * 31 + x * 7) ^ (y << 8)) & 0xFFFFFFFF
            cell_rng = random.Random(cell_seed)
            # Higher density toward the center
            cx = half_w - 1
            cy = height // 2
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            max_dist = math.sqrt(cx ** 2 + cy ** 2) or 1.0
            fill_chance = 0.85 - 0.7 * (dist / max_dist)
            if cell_rng.random() < fill_chance:
                # Pick a palette colour (weighted toward body colours, not outline)
                row.append(cell_rng.randint(1, len(palette) - 1))
            else:
                row.append(0)
        left_grid.append(row)

    # Mirror to produce full grid
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(height):
        full_row: list[tuple[int, int, int, int]] = []
        for x in range(width):
            if x < half_w:
                idx = left_grid[y][x]
            else:
                mirror_x = width - 1 - x
                if mirror_x < half_w:
                    idx = left_grid[y][mirror_x]
                else:
                    idx = 0
            full_row.append(palette[idx])
        pixels.extend(full_row)

    return pixels


async def run(data: dict) -> dict:
    """
    Entry-point called by the server.

    Expected keys:
      prompt  – text description of the sprite
      width   – canvas width in pixels
      height  – canvas height in pixels

    Returns one of the formats _decode_ai_image() accepts — we use the
    hex string format (RRGGBBAA × w×h concatenated):

      { "hex": "RRGGBBAA...", "width": W, "height": H }
    """
    prompt: str = (data.get("prompt") or "sprite").strip()
    width: int = max(1, int(data.get("width") or 16))
    height: int = max(1, int(data.get("height") or 16))

    pixels = _generate_sprite_data(prompt, width, height)

    hex_str = "".join(f"{r:02X}{g:02X}{b:02X}{a:02X}" for r, g, b, a in pixels)

    return {
        "hex": hex_str,
        "width": width,
        "height": height,
        "prompt": prompt,
        "model": "fake_generate_sprite_v1",
    }
