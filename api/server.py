"""
SpriteStack Studio - AI Backend API
====================================
FastAPI server that brokers all AI model predictions consumed by the Qt app.

Endpoints
---------
  POST /parse-scene        → scene layout from a text prompt
  POST /transcribe         → speech-to-text (WAV → transcript)
  POST /generate-sprite    → pixel art sprite generation
  POST /inpaint-region     → selection-aware region generation/inpainting
  POST /chat               → assistant guidance for generation panel
  POST /tween-frames       → animation frame interpolation
  GET  /health             → readiness check + plugin manifest

Each endpoint first checks for a *real* model plugin registered in
PLUGIN_REGISTRY, then falls back to the matching fake-JSON plugin that ships
in plugins/.  This lets you swap in trained models without touching the app.

Plugin contract
---------------
Every plugin is a Python module exposing one coroutine:

    async def run(request_data: dict) -> dict

The server imports it, calls run(), and returns whatever dict it produces.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("spritestack_api")

BASE_DIR = Path(__file__).parent
PLUGINS_DIR = BASE_DIR / "plugins"
LOCAL_PIXEL_MODEL_DIR = BASE_DIR / "models" / "pixel-art-model"
LOCAL_NER_MODEL_DIR = BASE_DIR / "models" / "nlp_parser"
LOCAL_RIFE_RGBA_DIR = BASE_DIR.parent / "pixel_rife_rgba_integration_package" / "model"
REAL_GENERATION_ENABLED = os.getenv("SPRITESTACK_REAL_GENERATION", "1").strip().lower() not in {
    "0",
    "false",
    "off",
}
FORCE_REAL_GENERATION = os.getenv("SPRITESTACK_FORCE_REAL_GENERATION", "0").strip().lower() in {
    "1",
    "true",
    "on",
}
REAL_TRANSCRIPTION_ENABLED = os.getenv("SPRITESTACK_REAL_TRANSCRIPTION", "1").strip().lower() not in {
    "0",
    "false",
    "off",
}
PYTHON_SUPPORTS_LOCAL_MODEL = sys.version_info < (3, 12)

# ---------------------------------------------------------------------------
# Plugin registry
# ---------------------------------------------------------------------------
# Override any fake plugin by registering a real model module path here,
# e.g.  PLUGIN_REGISTRY["generate-sprite"] = "my_models.sprite_gen"
# The module must expose:  async def run(data: dict) -> dict
# ---------------------------------------------------------------------------

PLUGIN_REGISTRY: dict[str, str] = {}
if (
    LOCAL_PIXEL_MODEL_DIR.is_dir()
    and REAL_GENERATION_ENABLED
):
    PLUGIN_REGISTRY["generate-sprite"] = "plugins.real_generate_sprite"
if LOCAL_NER_MODEL_DIR.is_dir():
    PLUGIN_REGISTRY["parse-scene"] = "plugins.real_parse_scene"
LOCAL_TWEENER_MODEL = BASE_DIR / "models" / "sprite_tweener_rgba_64_cpu.pt"
if LOCAL_TWEENER_MODEL.is_file():
    PLUGIN_REGISTRY["tween-frames"] = "plugins.real_tween_frames"
if REAL_TRANSCRIPTION_ENABLED:
    PLUGIN_REGISTRY["transcribe"] = "plugins.real_transcribe"

# Fallback fake-plugin modules (always present, ship in plugins/)
FAKE_PLUGIN_MODULES: dict[str, str] = {
    "parse-scene":     "plugins.fake_parse_scene",
    "transcribe":      "plugins.fake_transcribe",
    "generate-sprite": "plugins.fake_generate_sprite",
    "inpaint-region":  "plugins.fake_inpaint_region",
    "chat":            "plugins.fake_chat",
    "tween-frames":    "plugins.fake_tween_frames",
}


def _load_plugin_module(module_path: str):
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Plugin load error: {exc}") from exc
    if not hasattr(module, "run"):
        raise HTTPException(
            status_code=500,
            detail=f"Plugin '{module_path}' must expose async def run(data) -> dict",
        )
    return module.run


def _load_plugin(endpoint_key: str):
    """Return the run() coroutine for a given endpoint, real or fake."""
    real_module_path = PLUGIN_REGISTRY.get(endpoint_key)
    fake_module_path = FAKE_PLUGIN_MODULES.get(endpoint_key)
    if real_module_path:
        try:
            return _load_plugin_module(real_module_path)
        except HTTPException as exc:
            if fake_module_path is None:
                raise
            log.warning(
                "Real plugin for '%s' unavailable (%s). Falling back to fake plugin.",
                endpoint_key,
                exc.detail,
            )
    if fake_module_path:
        return _load_plugin_module(fake_module_path)
    raise HTTPException(status_code=501, detail=f"No plugin registered for '{endpoint_key}'")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SpriteStack Studio AI API",
    version="1.0.0",
    description="Local AI backend for SpriteStack Studio — scene parsing, sprite generation, "
                "animation tweening, and voice transcription.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware — log every request/response time
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - t0) * 1000
    log.info("%s %s → %d (%.1f ms)", request.method, request.url.path, response.status_code, elapsed)
    return response


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", summary="Readiness check")
async def health():
    """Returns server status and which plugins are active (real vs fake)."""
    plugins_status = {}
    for key in FAKE_PLUGIN_MODULES:
        real = key in PLUGIN_REGISTRY
        plugins_status[key] = {
            "mode": "real" if real else "fake",
            "module": PLUGIN_REGISTRY.get(key) or FAKE_PLUGIN_MODULES[key],
        }
    return {
        "status": "ok",
        "plugins": plugins_status,
    }


# ---------------------------------------------------------------------------
# /parse-scene
# ---------------------------------------------------------------------------



@app.post("/parse-scene", summary="Parse a scene description into object placements")
async def parse_scene(request: Request):
    """
    Request body (JSON):
      { "prompt": "tree on the left, rock on the right" }

    Response (JSON):
      {
        "objects": [
          { "name": "Tree",  "type": "stack",  "x": 0.15, "y": 0.50 },
          { "name": "Rock",  "type": "sprite", "x": 0.85, "y": 0.50 }
        ]
      }

    The Qt app's parse_ai_scene_payload() normalises this into ObjectPlacement
    instances — any extra keys are silently ignored.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        raise HTTPException(status_code=422, detail="'prompt' must be a non-empty string.")

    run = _load_plugin("parse-scene")
    try:
        result = await run(data)
    except Exception as exc:
        log.exception("parse-scene plugin error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# /transcribe
# ---------------------------------------------------------------------------

@app.post("/transcribe", summary="Transcribe a voice WAV to text")
async def transcribe(file: UploadFile = File(...)):
    """
    Multipart/form-data:
      file: WAV audio file (16 kHz mono, recorded by SceneUIPanel)

    Response (JSON):
      { "text": "tree on the left, rock on the right" }

    The Qt app reads .text, .transcript, or .prompt — all are equivalent.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    run = _load_plugin("transcribe")
    using_real_plugin = "transcribe" in PLUGIN_REGISTRY
    try:
        result = await run({"audio_bytes": audio_bytes, "filename": file.filename or "prompt.wav"})
    except Exception as exc:
        if using_real_plugin:
            log.exception("transcribe real plugin error; falling back to fake plugin")
            fake_run = _load_plugin_module(FAKE_PLUGIN_MODULES["transcribe"])
            try:
                result = await fake_run({"audio_bytes": audio_bytes, "filename": file.filename or "prompt.wav"})
            except Exception as fallback_exc:
                log.exception("transcribe fallback plugin error")
                raise HTTPException(status_code=500, detail=str(fallback_exc)) from fallback_exc
        else:
            log.exception("transcribe plugin error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# /generate-sprite
# ---------------------------------------------------------------------------

@app.post("/generate-sprite", summary="Generate a pixel-art sprite from a text prompt")
async def generate_sprite(request: Request):
    """
    Request body (JSON):
      {
        "prompt": "knight with sword",
        "width":  16,
        "height": 16
      }

    Response — one of the formats the Qt app's _decode_ai_image() accepts:

    Option A — hex string (all pixels concatenated, RRGGBBAA × w×h):
      { "hex": "FF0000FF...", "width": 16, "height": 16 }

    Option B — list of per-pixel hex tokens:
      { "pixels": ["FF0000FF", "00FF00FF", ...], "width": 16, "height": 16 }

    Option C — frames list (first frame used):
      { "frames": [ { "hex": "...", "width": 16, "height": 16 } ] }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        raise HTTPException(status_code=422, detail="'prompt' must be a non-empty string.")

    run = _load_plugin("generate-sprite")
    using_real_plugin = "generate-sprite" in PLUGIN_REGISTRY
    try:
        result = await run(data)
    except Exception as exc:
        if using_real_plugin:
            log.exception("generate-sprite real plugin error; falling back to fake plugin")
            fake_run = _load_plugin_module(FAKE_PLUGIN_MODULES["generate-sprite"])
            try:
                result = await fake_run(data)
            except Exception as fallback_exc:
                log.exception("generate-sprite fallback plugin error")
                raise HTTPException(status_code=500, detail=str(fallback_exc)) from fallback_exc
        else:
            log.exception("generate-sprite plugin error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# /inpaint-region
# ---------------------------------------------------------------------------

@app.post("/inpaint-region", summary="Generate/inpaint pixels within a selection region")
async def inpaint_region(request: Request):
    """
    Request body: see fake_inpaint_region.py for full schema.
    Response: { "hex": str, "width": int, "height": int, "model": str }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")
    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        raise HTTPException(status_code=422, detail="'prompt' must be a non-empty string.")
    run = _load_plugin("inpaint-region")
    try:
        result = await run(data)
    except Exception as exc:
        log.exception("inpaint-region plugin error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

@app.post("/chat", summary="AI assistant chat for generation guidance")
async def chat(request: Request):
    """
    Request body: { "message": str, "context": dict }
    Response: { "reply": str, "suggestions": [str] }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")
    if not isinstance(data.get("message"), str) or not data["message"].strip():
        raise HTTPException(status_code=422, detail="'message' must be a non-empty string.")
    run = _load_plugin("chat")
    try:
        result = await run(data)
    except Exception as exc:
        log.exception("chat plugin error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# /tween-frames
# ---------------------------------------------------------------------------

@app.post("/tween-frames", summary="Predict intermediate animation frames")
async def tween_frames(request: Request):
    """
    Request body (JSON):
      {
        "current_frame": { "width": W, "height": H, "hex": "RRGGBBAA..." },
        "next_frame":    { "width": W, "height": H, "hex": "RRGGBBAA..." },
        "num_intermediate": 1
      }

    Response (JSON):
      {
        "frames": [ { "hex": "...", "width": W, "height": H } ],
        "confidence": 0.87
      }

    If confidence < _ai_tween_confidence_threshold (default 0.6) the Qt app
    falls back to linear interpolation — returning a low confidence from the
    fake plugin is intentional so you can test the fallback path too.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    for key in ("current_frame", "next_frame"):
        if not isinstance(data.get(key), dict):
            raise HTTPException(status_code=422, detail=f"'{key}' must be an object.")

    run = _load_plugin("tween-frames")
    using_real_plugin = "tween-frames" in PLUGIN_REGISTRY
    try:
        result = await run(data)
    except Exception as exc:
        if using_real_plugin:
            log.exception("tween-frames real plugin error; falling back to fake plugin")
            fake_run = _load_plugin_module(FAKE_PLUGIN_MODULES["tween-frames"])
            try:
                result = await fake_run(data)
            except Exception as fallback_exc:
                log.exception("tween-frames fallback plugin error")
                raise HTTPException(status_code=500, detail=str(fallback_exc)) from fallback_exc
        else:
            log.exception("tween-frames plugin error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Add parent dir so `plugins.*` is importable
    sys.path.insert(0, str(BASE_DIR))
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
