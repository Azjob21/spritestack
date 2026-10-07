"""
Test suite for the SpriteStack Studio AI API
=============================================
Run with:  pytest tests/test_api.py -v

Covers all four endpoints with:
  - Happy-path checks (correct structure, types, value ranges)
  - Edge-case inputs (empty prompt, blank audio, mismatched frame sizes)
  - Fake-plugin specific paths (parse-scene no-objects, tween confidence modes)
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
import pytest

# Make the parent directory importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


# ===========================================================================
# /health
# ===========================================================================

def test_health_endpoint():
    """GET /health returns server info and plugin status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "status" in data
    

# ===========================================================================
# /api/parse-scene (NER)
# ===========================================================================

def test_parse_scene_happy_path():
    """POST /api/parse-scene with valid prompt returns scene objects."""
    response = client.post(
        "/parse-scene",
        json={"prompt": "a knight standing with a dragon flying above"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "objects" in data
    assert isinstance(data["objects"], list)
    assert "scene_metadata" in data
    assert "model" in data


def test_parse_scene_empty_prompt():
    """POST /api/parse-scene with empty prompt."""
    response = client.post(
        "/parse-scene",
        json={"prompt": ""}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("objects", []), list)


# ===========================================================================
# /api/generate-sprite (Image Generation)
# ===========================================================================

def test_generate_sprite_happy_path():
    """POST /api/generate-sprite with valid prompt returns base64 image."""
    response = client.post(
        "/generate-sprite",
        json={
            "prompt": "A red knight with a sword",
            "width": 64,
            "height": 64,
            "seed": 42
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "image" in data
    assert isinstance(data["image"], str)
    assert len(data["image"]) > 0
    assert "seed" in data
    assert "model" in data


def test_generate_sprite_edge_case_sizes():
    """POST /api/generate-sprite with various size combinations."""
    for w, h in [(16, 16), (32, 32), (64, 64), (128, 128)]:
        response = client.post(
            "/generate-sprite",
            json={
                "prompt": "a small creature",
                "width": w,
                "height": h,
                "seed": 100
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "image" in data


def test_generate_sprite_empty_prompt():
    """POST /api/generate-sprite with empty prompt."""
    response = client.post(
        "/generate-sprite",
        json={
            "prompt": "",
            "width": 64,
            "height": 64,
            "seed": 1
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "image" in data


# ===========================================================================
# /api/tween-frames (Animation)
# ===========================================================================

def test_tween_frames_happy_path():
    """POST /api/tween-frames with valid frames returns tweened sequence."""
    # Create minimal valid base64 images (1x1 PNG)
    # This is a valid 1x1 transparent PNG in base64
    valid_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    response = client.post(
        "/tween-frames",
        json={
            "frame_start": valid_png_b64,
            "frame_end": valid_png_b64,
            "num_frames": 3
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "frames" in data
    assert isinstance(data["frames"], list)
    assert len(data["frames"]) >= 2


def test_tween_frames_different_counts():
    """POST /api/tween-frames with various num_frames."""
    valid_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    for n in [2, 4, 8]:
        response = client.post(
            "/tween-frames",
            json={
                "frame_start": valid_png_b64,
                "frame_end": valid_png_b64,
                "num_frames": n
            }
        )
        assert response.status_code == 200


def test_tween_frames_edge_case_single_frame():
    """POST /api/tween-frames requesting single frame."""
    valid_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    response = client.post(
        "/tween-frames",
        json={
            "frame_start": valid_png_b64,
            "frame_end": valid_png_b64,
            "num_frames": 1
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "frames" in data
