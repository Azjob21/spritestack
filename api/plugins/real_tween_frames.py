"""
Real plugin: /tween-frames
===========================
Uses the local TorchScript RIFE-RGBA model for 64×64 pixel-art frame
interpolation.

The model was exported with ``torch.jit.trace`` and optimised via
``torch.jit.optimize_for_inference`` in channels_last (NHWC) format.
It accepts an 8-channel tensor (RGBA_frame1 + RGBA_frame2 concatenated
along the channel dimension) and returns a 4-channel RGBA prediction.

Install: pip install torch numpy Pillow
"""

from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
# pyrefly: ignore [missing-import]
import torch
from PIL import Image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model path — the TorchScript bundle lives in models/
# ---------------------------------------------------------------------------
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "sprite_tweener_rgba_64_cpu.pt"
MODEL_SIZE = 64  # The model was trained on 64×64 pixel-art

_model = None
_model_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Lazy-load the TorchScript model (thread-safe, one-time cost)
# ---------------------------------------------------------------------------
def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:              # double-check after acquiring lock
            return _model
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(
                f"TorchScript RIFE-RGBA model not found at: {MODEL_PATH}"
            )
        log.info("Loading TorchScript RIFE-RGBA model from %s …", MODEL_PATH)
        loaded = torch.jit.load(str(MODEL_PATH), map_location="cpu")
        loaded.eval()
        _model = loaded
        log.info("Model loaded successfully.")
        return _model


# ---------------------------------------------------------------------------
# Hex frame ↔ numpy helpers (shared with the fake plugin's format)
# ---------------------------------------------------------------------------

def _decode_hex_frame(frame: dict) -> tuple[int, int, np.ndarray] | None:
    """Decode { hex, width, height } → (w, h, rgba_uint8[H,W,4]) or None."""
    try:
        w = int(frame.get("width") or frame.get("w") or 0)
        h = int(frame.get("height") or frame.get("h") or 0)
        hex_str = str(frame.get("hex") or frame.get("pixel_hex") or "")
    except (TypeError, ValueError):
        return None

    if w <= 0 or h <= 0 or not hex_str:
        return None

    hex_clean = "".join(ch for ch in hex_str if ch in "0123456789abcdefABCDEF")
    expected_chars = w * h * 8  # 4 bytes per pixel × 2 hex chars per byte
    if len(hex_clean) != expected_chars:
        return None

    raw = bytes.fromhex(hex_clean)
    rgba = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 4)).copy()
    return w, h, rgba


def _encode_hex_frame(w: int, h: int, rgba: np.ndarray) -> dict:
    """Encode numpy RGBA array → { hex, width, height }."""
    return {
        "hex": rgba.astype(np.uint8, copy=False).tobytes().hex().upper(),
        "width": w,
        "height": h,
    }


def _resize_rgba(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize an RGBA numpy array using nearest-neighbour (pixel-art safe)."""
    img = Image.fromarray(rgba, "RGBA")
    img = img.resize((width, height), Image.Resampling.NEAREST)
    return np.asarray(img, dtype=np.uint8).copy()


# ---------------------------------------------------------------------------
# Inference — runs in a thread pool so we never block the async event loop
# ---------------------------------------------------------------------------

def _infer_sync(cur_rgba: np.ndarray, nxt_rgba: np.ndarray) -> np.ndarray:
    """
    Run a single forward pass through the TorchScript model.

    The model signature is:  forward(img0: Tensor, img1: Tensor) -> Tensor
    Each input is a (1, 4, H, W) float32 RGBA tensor in [0, 1].
    The model concatenates them internally in IFNet_RGBA.

    Parameters
    ----------
    cur_rgba, nxt_rgba : np.ndarray  – uint8 arrays of shape (64, 64, 4)

    Returns
    -------
    np.ndarray – uint8 RGBA array of shape (64, 64, 4)
    """
    model = _get_model()

    # Convert HWC uint8 → NCHW float32 [0, 1]
    img0 = torch.from_numpy(cur_rgba).permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
    img1 = torch.from_numpy(nxt_rgba).permute(2, 0, 1).float().div_(255.0).unsqueeze(0)

    # Use channels_last memory format to match the model's export optimisation
    img0 = img0.to(memory_format=torch.channels_last)
    img1 = img1.to(memory_format=torch.channels_last)

    with torch.no_grad():
        out = model(img0, img1)  # (1, 4, 64, 64)

    # Convert back to HWC uint8
    pred = out.squeeze(0).clamp(0.0, 1.0).mul(255.0).byte()
    pred = pred.permute(1, 2, 0).contiguous().cpu().numpy()  # (64, 64, 4)
    return pred


# ---------------------------------------------------------------------------
# Fake fallback (used for test_mode or dimension mismatches)
# ---------------------------------------------------------------------------

async def _run_fake(data: dict) -> dict:
    try:
        from plugins.fake_tween_frames import run as fake_run
    except ModuleNotFoundError:
        # pyrefly: ignore [missing-import]
        from api.plugins.fake_tween_frames import run as fake_run
    return await fake_run(data)


# ---------------------------------------------------------------------------
# Plugin entry-point
# ---------------------------------------------------------------------------

async def run(data: dict) -> dict:
    """
    Entry-point called by the server.

    Expected keys
    -------------
    current_frame    – { hex, width, height }
    next_frame       – { hex, width, height }
    num_intermediate – int (we always produce 1 frame)
    test_mode        – optional, if truthy → delegate to fake plugin

    Returns
    -------
    {
        "frames":     [{ "hex": str, "width": int, "height": int }],
        "confidence": float,
        "model":      str
    }
    """
    current_raw = data.get("current_frame") or {}
    next_raw = data.get("next_frame") or {}

    # Test-mode escape hatch
    if data.get("test_mode"):
        return await _run_fake(data)

    # Decode hex frames
    current_decoded = _decode_hex_frame(current_raw)
    next_decoded = _decode_hex_frame(next_raw)
    if current_decoded is None or next_decoded is None:
        return {
            "frames": [],
            "confidence": 0.0,
            "model": "sprite_tweener_rgba_64_torchscript",
            "error": "Could not decode one or both input frames.",
        }

    w, h, cur_rgba = current_decoded
    w2, h2, nxt_rgba = next_decoded

    # Dimension mismatch → return current frame unchanged
    if (w, h) != (w2, h2):
        return {
            "frames": [_encode_hex_frame(w, h, cur_rgba)],
            "confidence": 0.10,
            "model": "sprite_tweener_rgba_64_torchscript",
            "warning": "Frame dimensions differ; returning current frame unchanged.",
        }

    # If not 64×64, resize to 64×64 → infer → resize back
    original_size = (w, h)
    needs_resize = (w, h) != (MODEL_SIZE, MODEL_SIZE)
    if needs_resize:
        cur_rgba = _resize_rgba(cur_rgba, MODEL_SIZE, MODEL_SIZE)
        nxt_rgba = _resize_rgba(nxt_rgba, MODEL_SIZE, MODEL_SIZE)

    # Run inference in a thread pool (CPU model, ~28 ms typical)
    try:
        loop = asyncio.get_running_loop()
        pred = await loop.run_in_executor(None, _infer_sync, cur_rgba, nxt_rgba)
    except Exception:
        log.exception("TorchScript RIFE-RGBA tween failed")
        raise

    # Resize back to original dimensions if needed
    if needs_resize:
        pred = _resize_rgba(pred, original_size[0], original_size[1])
        out_w, out_h = original_size
    else:
        out_w, out_h = MODEL_SIZE, MODEL_SIZE

    return {
        "frames": [_encode_hex_frame(out_w, out_h, pred)],
        "confidence": 0.95,
        "model": "sprite_tweener_rgba_64_torchscript",
    }
