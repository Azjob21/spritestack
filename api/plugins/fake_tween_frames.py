"""
Fake plugin: /tween-frames
==========================
Produces a midpoint interpolation between two hex-encoded pixel frames
WITHOUT a real ML tweening model.

Confidence behaviour
--------------------
The fake plugin exposes two test modes controlled by the presence of a
special key in the request payload:

  "test_mode": "high_confidence"   → confidence = 0.92  (AI frame used)
  "test_mode": "low_confidence"    → confidence = 0.25  (fallback to Qt linear interp)
  (default)                        → confidence = 0.72  (AI frame used)

This lets you drive both code-paths in the Qt app's _on_tween_frames_ready()
without a real model.

Pixel format
------------
Frames are sent/received as RRGGBBAA hex strings (8 hex chars per pixel,
width × height pixels).  The same format used by generate-sprite.
"""

from __future__ import annotations

import struct


def _decode_hex_frame(frame: dict) -> tuple[int, int, list[tuple[int, int, int, int]]] | None:
    """Decode { hex, width, height } → (w, h, [(r,g,b,a), ...]) or None."""
    try:
        w = int(frame.get("width") or frame.get("w") or 0)
        h = int(frame.get("height") or frame.get("h") or 0)
        hex_str = str(frame.get("hex") or frame.get("pixel_hex") or "")
    except (TypeError, ValueError):
        return None

    if w <= 0 or h <= 0 or not hex_str:
        return None

    hex_clean = "".join(ch for ch in hex_str if ch in "0123456789abcdefABCDEF")
    expected_chars = w * h * 8  # 4 bytes per pixel, 2 hex chars per byte
    if len(hex_clean) != expected_chars:
        return None

    pixels: list[tuple[int, int, int, int]] = []
    for i in range(0, len(hex_clean), 8):
        chunk = hex_clean[i : i + 8]
        r = int(chunk[0:2], 16)
        g = int(chunk[2:4], 16)
        b = int(chunk[4:6], 16)
        a = int(chunk[6:8], 16)
        pixels.append((r, g, b, a))

    return w, h, pixels


def _lerp_pixel(
    p1: tuple[int, int, int, int],
    p2: tuple[int, int, int, int],
    t: float,
) -> tuple[int, int, int, int]:
    return (
        int(p1[0] * (1 - t) + p2[0] * t),
        int(p1[1] * (1 - t) + p2[1] * t),
        int(p1[2] * (1 - t) + p2[2] * t),
        int(p1[3] * (1 - t) + p2[3] * t),
    )


def _encode_hex_frame(
    w: int,
    h: int,
    pixels: list[tuple[int, int, int, int]],
) -> dict:
    hex_str = "".join(f"{r:02X}{g:02X}{b:02X}{a:02X}" for r, g, b, a in pixels)
    return {"hex": hex_str, "width": w, "height": h}


async def run(data: dict) -> dict:
    """
    Entry-point called by the server.

    Expected keys:
      current_frame    – { hex, width, height }
      next_frame       – { hex, width, height }
      num_intermediate – int (we always produce 1 for the fake)
      test_mode        – optional: "high_confidence" | "low_confidence"

    Returns:
      {
        "frames":     [ { "hex": "...", "width": W, "height": H } ],
        "confidence": float,
        "model":      "fake_tween_frames_v1"
      }
    """
    current_raw: dict = data.get("current_frame") or {}
    next_raw: dict = data.get("next_frame") or {}
    test_mode: str = str(data.get("test_mode") or "").strip().lower()

    # Confidence routing for test coverage
    if test_mode == "high_confidence":
        confidence = 0.92
    elif test_mode == "low_confidence":
        confidence = 0.25
    else:
        confidence = 0.72

    # Decode frames
    current_decoded = _decode_hex_frame(current_raw)
    next_decoded = _decode_hex_frame(next_raw)

    if current_decoded is None or next_decoded is None:
        # Frames couldn't be decoded — return empty result with low confidence
        # so the Qt app triggers its fallback linear interpolation.
        return {
            "frames": [],
            "confidence": 0.0,
            "model": "fake_tween_frames_v1",
            "error": "Could not decode one or both input frames.",
        }

    w, h, cur_px = current_decoded
    w2, h2, nxt_px = next_decoded

    # If dimensions differ, return the current frame unchanged at low confidence
    if (w, h) != (w2, h2):
        return {
            "frames": [_encode_hex_frame(w, h, cur_px)],
            "confidence": 0.10,
            "model": "fake_tween_frames_v1",
            "warning": "Frame dimensions differ; returning current frame unchanged.",
        }

    # Produce midpoint blend (t=0.5) — identical to what Qt does as fallback,
    # but returned through the API path so we test the full round-trip.
    mid_pixels = [_lerp_pixel(a, b, 0.5) for a, b in zip(cur_px, nxt_px)]
    mid_frame = _encode_hex_frame(w, h, mid_pixels)

    return {
        "frames": [mid_frame],
        "confidence": confidence,
        "model": "fake_tween_frames_v1",
    }
