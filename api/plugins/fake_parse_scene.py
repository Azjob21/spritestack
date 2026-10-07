"""
Fake plugin: /parse-scene
=========================
Converts a text prompt into scene object placements without a real NLP model.

Strategy
--------
1. Keyword scan for known object names and positional words.
2. Return 1-4 objects with normalised (x, y) coordinates in [0, 1] space.
   These map directly to ObjectPlacement fields consumed by the Qt app's
   parse_ai_scene_payload() / apply_ai_scene_layout().

The fake plugin also exercises the "no objects found" edge-case when the
prompt contains "empty" or "blank" so you can test graceful degradation.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

# name → preferred object type
OBJECT_KEYWORDS: dict[str, str] = {
    # vegetation
    "tree": "stack", "pine": "stack", "oak": "stack", "bush": "stack",
    "grass": "texture", "flower": "sprite",
    # terrain
    "rock": "stack", "stone": "stack", "cliff": "stack", "mountain": "stack",
    "hill": "texture", "ground": "texture", "sand": "texture", "snow": "texture",
    # water
    "water": "texture", "lake": "texture", "river": "texture", "ocean": "texture",
    "waterfall": "stack",
    # structures
    "house": "stack", "castle": "stack", "tower": "stack", "bridge": "stack",
    "fence": "sprite", "wall": "stack", "door": "sprite", "window": "sprite",
    # characters / items
    "knight": "sprite", "hero": "sprite", "enemy": "sprite", "npc": "sprite",
    "sword": "sprite", "shield": "sprite", "chest": "sprite", "coin": "sprite",
    "torch": "sprite", "lamp": "sprite",
    # nature misc
    "cloud": "sprite", "sun": "sprite", "moon": "sprite", "star": "sprite",
    "bird": "sprite", "fish": "sprite",
    # atmosphere / background
    "sky": "texture", "fog": "texture", "rain": "sprite",
}

# Horizontal position clues → normalised x
H_ANCHORS: dict[str, float] = {
    "far left": 0.05, "left": 0.15, "centre left": 0.33, "center left": 0.33,
    "middle": 0.50, "center": 0.50, "centre": 0.50,
    "centre right": 0.67, "center right": 0.67, "right": 0.85, "far right": 0.95,
}

# Vertical position clues → normalised y
V_ANCHORS: dict[str, float] = {
    "top": 0.10, "upper": 0.20, "above": 0.20,
    "mid": 0.50, "middle": 0.50, "center": 0.50,
    "lower": 0.70, "below": 0.75, "bottom": 0.85,
    "foreground": 0.80, "background": 0.20,
}

# Default grid positions for when no explicit anchor is given (up to 6 objects)
_DEFAULT_POSITIONS = [
    (0.50, 0.50),
    (0.20, 0.60),
    (0.80, 0.60),
    (0.50, 0.20),
    (0.20, 0.30),
    (0.80, 0.30),
]


def _find_h(text: str) -> float | None:
    for phrase, val in sorted(H_ANCHORS.items(), key=lambda kv: -len(kv[0])):
        if phrase in text:
            return val
    return None


def _find_v(text: str) -> float | None:
    for phrase, val in sorted(V_ANCHORS.items(), key=lambda kv: -len(kv[0])):
        if phrase in text:
            return val
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

async def run(data: dict) -> dict:
    """
    Entry-point called by the server.  Returns a dict compatible with the
    Qt app's parse_ai_scene_payload():

        { "objects": [ {"name": str, "type": str, "x": float, "y": float}, ... ] }
    """
    prompt: str = (data.get("prompt") or "").lower()

    # Edge-case: intentionally empty scene
    if any(word in prompt for word in ("empty", "blank", "nothing", "void")):
        return {"objects": []}

    # --- Split prompt into object-bearing clauses ---
    # Split on commas, "and", semicolons so each clause is analysed separately
    clauses = re.split(r",\s*|\band\b|;\s*", prompt)

    objects: list[dict] = []
    used_positions: set[tuple[float, float]] = set()

    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue

        # Find the first matching object keyword in this clause
        matched_name = None
        matched_type = "sprite"
        for keyword, obj_type in OBJECT_KEYWORDS.items():
            if keyword in clause:
                matched_name = keyword.title()
                matched_type = obj_type
                break

        if matched_name is None:
            continue

        # Determine position
        x = _find_h(clause)
        y = _find_v(clause)

        # Fall back to an unused default grid slot
        if x is None or y is None:
            for pos in _DEFAULT_POSITIONS:
                if pos not in used_positions:
                    x = x if x is not None else pos[0]
                    y = y if y is not None else pos[1]
                    used_positions.add(pos)
                    break
            else:
                x = x if x is not None else 0.5
                y = y if y is not None else 0.5

        used_positions.add((round(x, 2), round(y, 2)))

        objects.append({
            "name": matched_name,
            "type": matched_type,
            "x": round(x, 3),
            "y": round(y, 3),
        })

    # If nothing was recognised, return a sensible generic object
    if not objects:
        objects = [{"name": "Sprite", "type": "sprite", "x": 0.5, "y": 0.5}]

    return {"objects": objects}