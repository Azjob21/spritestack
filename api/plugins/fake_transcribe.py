"""
Fake plugin: /transcribe
========================
Simulates speech-to-text without a real ASR model.

Since we obviously can't decode audio bytes in a fake, we do the next-best
thing: inspect the filename and byte length to pick a plausible canned
transcript from a rotation of realistic pixel-art scene prompts.

When a real model (e.g. Whisper via faster-whisper or OpenAI) is ready,
replace this module with one that passes audio_bytes to the model and
returns {"text": transcript}.
"""

from __future__ import annotations

import hashlib

# Pool of canned transcripts — picked deterministically from audio length
# so repeated test runs with the same file always return the same result.
_TRANSCRIPTS = [
    "tree on the left, rock on the right",
    "knight in the center, castle in the background",
    "forest with a river running through the middle",
    "mountain peak at the top, snow ground at the bottom",
    "small house on the right side with a fence",
    "dragon flying above the clouds on the left",
    "treasure chest in the center foreground",
    "sunset sky at the top, desert sand at the bottom",
    "bridge over water in the middle of the scene",
    "two torches flanking a dungeon door in the center",
]


async def run(data: dict) -> dict:
    """
    Entry-point called by the server.

    Expected keys:
      audio_bytes  – raw bytes of the WAV file
      filename     – original filename (optional, used as entropy)

    Returns:
      { "text": "<transcript string>" }
    """
    audio_bytes: bytes = data.get("audio_bytes") or b""
    filename: str = data.get("filename") or "prompt.wav"

    # Deterministic selection: hash filename + first 256 bytes of audio
    seed_material = filename.encode() + audio_bytes[:256]
    digest = hashlib.md5(seed_material).digest()
    index = digest[0] % len(_TRANSCRIPTS)
    transcript = _TRANSCRIPTS[index]

    return {"text": transcript}