"""
Real plugin: /transcribe
========================
Offline speech-to-text via faster-whisper.

This plugin keeps the same contract as fake_transcribe.py:

    input:  {"audio_bytes": <wav bytes>, "filename": "..."}
    output: {"text": "..."}

The model name, device, and compute type are configurable through
environment variables so the app can stay offline-first and CPU-only by
default:

    SPRITESTACK_TRANSCRIPTION_MODEL        (default: "small")
    SPRITESTACK_TRANSCRIPTION_DEVICE       (default: "cpu")
    SPRITESTACK_TRANSCRIPTION_COMPUTE_TYPE (default: "int8")
    SPRITESTACK_TRANSCRIPTION_BEAM_SIZE     (default: "5")
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_MODEL_DIR = BASE_DIR / "models" / "whisper-small-en"

_MODEL_LOCK = threading.Lock()
_MODEL = None


def _get_setting(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value.strip() or default


def _get_bool_setting(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in {"0", "false", "off", "no"}


def _get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError("faster-whisper is not installed") from exc

        model_path = _get_setting("SPRITESTACK_TRANSCRIPTION_MODEL_PATH", str(LOCAL_MODEL_DIR))
        model_name = _get_setting("SPRITESTACK_TRANSCRIPTION_MODEL", "small.en")
        device = _get_setting("SPRITESTACK_TRANSCRIPTION_DEVICE", "cpu")
        compute_type = _get_setting("SPRITESTACK_TRANSCRIPTION_COMPUTE_TYPE", "int8")
        local_files_only = _get_bool_setting("SPRITESTACK_TRANSCRIPTION_LOCAL_FILES_ONLY", True)

        model_source = model_path or model_name
        if model_path and not Path(model_path).is_dir():
            raise RuntimeError(f"Local transcription model path does not exist: {model_path}")

        _MODEL = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
            local_files_only=local_files_only,
        )
        return _MODEL


def _write_temp_wav(audio_bytes: bytes, filename: str) -> Path:
    suffix = ".wav"
    if "." in filename:
        extracted_suffix = Path(filename).suffix
        if extracted_suffix:
            suffix = extracted_suffix
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(audio_bytes)
        handle.flush()
        return Path(handle.name)
    finally:
        handle.close()


async def run(data: dict) -> dict:
    audio_bytes: bytes = data.get("audio_bytes") or b""
    filename: str = str(data.get("filename") or "prompt.wav")
    if not audio_bytes:
        return {"text": ""}

    temp_path = _write_temp_wav(audio_bytes, filename)
    try:
        model = _get_model()
        beam_size = int(_get_setting("SPRITESTACK_TRANSCRIPTION_BEAM_SIZE", "5"))
        segments, info = model.transcribe(
            str(temp_path),
            beam_size=beam_size,
            vad_filter=True,
            language="en",
        )
        text = "".join(segment.text for segment in segments).strip()
        result: dict[str, Any] = {
            "text": text,
            "model": f"faster-whisper:{_get_setting('SPRITESTACK_TRANSCRIPTION_MODEL_PATH', '') or _get_setting('SPRITESTACK_TRANSCRIPTION_MODEL', 'small.en')}",
            "source": "local" if _get_bool_setting("SPRITESTACK_TRANSCRIPTION_LOCAL_FILES_ONLY", True) else "downloadable",
        }
        language = getattr(info, "language", None)
        if language:
            result["language"] = str(language)
        probability = getattr(info, "language_probability", None)
        if probability is not None:
            try:
                result["language_probability"] = float(probability)
            except (TypeError, ValueError):
                pass
        return result
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except TypeError:  # Python < 3.8 compatibility path
            try:
                temp_path.unlink()
            except OSError:
                pass
        except OSError:
            pass
