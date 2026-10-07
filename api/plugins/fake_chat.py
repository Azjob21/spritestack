"""
Fake plugin: /chat
==================
Keyword-based assistant replies for generation guidance.
"""

from __future__ import annotations


_INTENTS: list[tuple[list[str], str, list[str]]] = [
    (
        ["prompt", "write", "good"],
        "A good pixel art prompt has three parts: subject ('worn knight'), style modifier ('dark fantasy, outlined'), and palette hint ('muted blues and browns'). Keep it under 20 words.",
        ["Show me an example", "What style tags exist?", "How does strength work?"],
    ),
    (
        ["strength"],
        "Strength (1-10) controls how aggressively the AI departs from the source pixels. Low (1-4): subtle texture overlay. Mid (5-7): visible changes, original shape preserved. High (8-10): full repaint of the region.",
        ["What is palette lock?", "Explain blend mode", "Try strength 4"],
    ),
    (
        ["palette", "lock"],
        "Palette lock forces the output pixels to snap to the nearest colour already present in your active layer. Useful when you want AI fills that don't introduce new colours.",
        ["What is blend mode?", "What is inpaint?"],
    ),
    (
        ["blend", "replace", "mode"],
        "'New layer' adds a layer above the current one — safest option. 'Replace selection' writes pixels directly into the active layer inside the selection boundary. 'Blend' does the same but at 70% opacity so original pixels show through.",
        ["How do I undo?", "What is palette lock?"],
    ),
    (
        ["inpaint", "region", "selection", "fill"],
        "Make a rectangular or lasso selection first (S or A key), then switch to 'Fill Selection' or 'Inpaint Region' mode. 'Fill Selection' generates only inside the selection. 'Inpaint' sends the surrounding pixels too so seams blend better.",
        ["How to make a selection?", "What is strength?"],
    ),
    (
        ["tag", "style", "tags"],
        "Useful style tags: 'outlined' (black pixel border), 'dithered' (checkerboard shading), 'cel shaded' (flat colours + hard shadow), 'top-down' (overhead perspective), 'isometric' (45° angle), 'dark fantasy' (moody palette).",
        ["How to write a good prompt?", "What is strength?"],
    ),
    (
        ["variation", "vary", "different"],
        "To get variations: set Variations to 2 or 4 before clicking Generate. Each variant comes back as a separate layer so you can compare and delete the ones you don't want.",
        ["Try 4 variations", "What is blend mode?"],
    ),
    (
        ["undo", "mistake", "revert"],
        "Press Ctrl+Z to undo any AI generation — it is pushed onto the undo stack before pixels are written. You can undo as many times as your undo history allows (default: 100 states).",
        ["How do I redo?", "What is the undo limit?"],
    ),
]

_FALLBACK_REPLY = (
    "I can help with prompts, generation modes, style tags, and settings. "
    "Try asking 'how do I write a good prompt?' or 'what does strength do?'"
)
_FALLBACK_SUGGESTIONS = [
    "How to write a good prompt?",
    "What does strength do?",
    "Explain inpaint mode",
]


def _match_intent(message: str) -> tuple[str, list[str]]:
    text = message.lower()
    for keywords, reply, suggestions in _INTENTS:
        if all(word in text for word in keywords):
            return reply, suggestions
    return _FALLBACK_REPLY, list(_FALLBACK_SUGGESTIONS)


def _selection_preamble(context: dict) -> str:
    if not isinstance(context, dict):
        return ""
    if not bool(context.get("has_selection")):
        return ""
    rect = context.get("selection_rect")
    if not isinstance(rect, dict):
        return ""
    w = int(rect.get("w") or 0)
    h = int(rect.get("h") or 0)
    layer_name = str(context.get("active_layer_name") or "Layer")
    if w <= 0 or h <= 0:
        return ""
    return f"(I see a {w}×{h} px selection on layer '{layer_name}') "


async def run(data: dict) -> dict:
    try:
        payload = data if isinstance(data, dict) else {}
        message = str(payload.get("message") or "").strip()
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        reply, suggestions = _match_intent(message)
        preamble = _selection_preamble(context)
        return {
            "reply": f"{preamble}{reply}",
            "suggestions": [str(s) for s in suggestions if str(s).strip()],
        }
    except Exception:
        return {
            "reply": _FALLBACK_REPLY,
            "suggestions": list(_FALLBACK_SUGGESTIONS),
        }
