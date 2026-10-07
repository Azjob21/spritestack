from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from server import app  # noqa: E402


client = TestClient(app)


def _inpaint_payload(prompt="worn texture", w=8, h=8, palette_lock=False):
    pixel = "FF0000FF"
    region_hex = pixel * (w * h)
    return {
        "prompt": prompt,
        "mode": "fill_selection",
        "width": w,
        "height": h,
        "strength": 5,
        "palette_lock": palette_lock,
        "style": "Pixel art",
        "selection": {
            "region_hex": region_hex,
            "context_hex": pixel * (16 * 16),
            "x": 0,
            "y": 0,
            "w": w,
            "h": h,
            "width": w,
            "height": h,
        },
    }


def _decode_rgba_channels(hex_str: str):
    for i in range(0, len(hex_str), 8):
        token = hex_str[i : i + 8]
        yield (
            int(token[0:2], 16),
            int(token[2:4], 16),
            int(token[4:6], 16),
            int(token[6:8], 16),
        )


def test_inpaint_returns_hex():
    r = client.post("/inpaint-region", json=_inpaint_payload())
    assert r.status_code == 200
    assert "hex" in r.json()


def test_inpaint_hex_correct_length():
    w, h = 8, 8
    r = client.post("/inpaint-region", json=_inpaint_payload(w=w, h=h))
    assert r.status_code == 200
    assert len(r.json()["hex"]) == w * h * 8


def test_inpaint_hex_is_valid_hex():
    r = client.post("/inpaint-region", json=_inpaint_payload())
    assert r.status_code == 200
    int(r.json()["hex"], 16)


def test_inpaint_different_prompts_differ():
    a = client.post("/inpaint-region", json=_inpaint_payload(prompt="worn knight"))
    b = client.post("/inpaint-region", json=_inpaint_payload(prompt="mossy gargoyle"))
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["hex"] != b.json()["hex"]


def test_inpaint_same_prompt_deterministic():
    payload = _inpaint_payload(prompt="worn knight")
    a = client.post("/inpaint-region", json=payload)
    b = client.post("/inpaint-region", json=payload)
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["hex"] == b.json()["hex"]


def test_inpaint_palette_lock_snaps_channels():
    r = client.post("/inpaint-region", json=_inpaint_payload(palette_lock=True))
    assert r.status_code == 200
    for rgba in _decode_rgba_channels(r.json()["hex"]):
        for channel in rgba:
            assert channel % 32 == 0


def test_inpaint_missing_prompt_422():
    payload = _inpaint_payload()
    payload.pop("prompt")
    r = client.post("/inpaint-region", json=payload)
    assert r.status_code == 422


def test_inpaint_malformed_hex_graceful():
    payload = _inpaint_payload(w=8, h=8)
    payload["selection"]["region_hex"] = "ZZZZZZ"
    r = client.post("/inpaint-region", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert len(body["hex"]) == 8 * 8 * 8
    int(body["hex"], 16)


def test_inpaint_zero_dimensions_graceful():
    payload = _inpaint_payload(w=0, h=0)
    r = client.post("/inpaint-region", json=payload)
    assert r.status_code == 200
    assert r.json()["hex"] == ""


def test_chat_returns_reply():
    r = client.post("/chat", json={"message": "hello", "context": {}})
    assert r.status_code == 200
    reply = r.json().get("reply")
    assert isinstance(reply, str)
    assert reply.strip() != ""


def test_chat_returns_suggestions():
    r = client.post("/chat", json={"message": "help", "context": {}})
    assert r.status_code == 200
    suggestions = r.json().get("suggestions")
    assert isinstance(suggestions, list)
    assert len(suggestions) >= 1
    assert all(isinstance(s, str) and s.strip() for s in suggestions)


def test_chat_strength_intent():
    r = client.post("/chat", json={"message": "what does strength control?", "context": {}})
    assert r.status_code == 200
    assert "strength" in r.json()["reply"].lower()


def test_chat_prompt_intent():
    r = client.post("/chat", json={"message": "how do I write a good prompt?", "context": {}})
    assert r.status_code == 200
    assert "prompt" in r.json()["reply"].lower()


def test_chat_blend_intent():
    r = client.post("/chat", json={"message": "explain blend vs replace mode", "context": {}})
    assert r.status_code == 200
    reply = r.json()["reply"].lower()
    assert "blend" in reply or "replace" in reply


def test_chat_fallback():
    r = client.post("/chat", json={"message": "xyzzy blorp floop", "context": {}})
    assert r.status_code == 200
    assert isinstance(r.json().get("reply"), str)
    assert r.json()["reply"].strip() != ""


def test_chat_context_selection_preamble():
    context = {
        "canvas_width": 64,
        "canvas_height": 64,
        "active_layer_name": "Slice 1",
        "has_selection": True,
        "selection_rect": {"x": 0, "y": 0, "w": 20, "h": 20},
        "layer_count": 4,
        "current_mode": "fill_selection",
    }
    r = client.post("/chat", json={"message": "what does strength control?", "context": context})
    assert r.status_code == 200
    assert r.json()["reply"].startswith("(I see a 20×20")


def test_chat_missing_message_422():
    r = client.post("/chat", json={})
    assert r.status_code == 422


def test_chat_empty_message_422():
    r = client.post("/chat", json={"message": "  "})
    assert r.status_code == 422
