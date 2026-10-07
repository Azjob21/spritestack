"""
Scene model (schema v3) — hierarchical scene with typed objects.

Each SceneObject holds its own canvas data (layers, dimensions).
The SceneModel manages the full collection and active-object state.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, List, Optional

from PyQt5.QtGui import QImage, QColor
from PyQt5.QtCore import Qt


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OBJECT_TYPE_STACK   = "stack"
OBJECT_TYPE_SPRITE  = "sprite"
OBJECT_TYPE_TEXTURE = "texture"
OBJECT_TYPES = {OBJECT_TYPE_STACK, OBJECT_TYPE_SPRITE, OBJECT_TYPE_TEXTURE}

# Layer-type constants (backward compat with canvas.py)
LAYER_TYPE_SLICE   = "slice"
LAYER_TYPE_SPRITE  = "sprite"
LAYER_TYPE_TEXTURE = "texture"

SCHEMA_VERSION = 4  # Bumped for multi-scene support

_ANCHOR_TO_NORMALIZED = {
    "left": (0.15, 0.5),
    "center": (0.5, 0.5),
    "middle": (0.5, 0.5),
    "right": (0.85, 0.5),
    "top": (0.5, 0.15),
    "bottom": (0.5, 0.85),
    "top-left": (0.15, 0.15),
    "top-right": (0.85, 0.15),
    "bottom-left": (0.15, 0.85),
    "bottom-right": (0.85, 0.85),
}

_H_ANCHORS = {
    "left": 0.15,
    "center": 0.5,
    "middle": 0.5,
    "right": 0.85,
}
_V_ANCHORS = {
    "top": 0.15,
    "center": 0.5,
    "middle": 0.5,
    "bottom": 0.85,
}


def _new_object_id() -> str:
    return f"obj_{uuid.uuid4().hex[:8]}"


def _new_scene_id() -> str:
    return f"scn_{uuid.uuid4().hex[:8]}"


def normalize_scene_metadata(meta: dict, layer_count: int) -> dict:
    """
    Ensure layer_types, layer_object_ids, and object_layers arrays are
    the correct length and contain valid values.  Returns the cleaned dict.
    """
    lt = meta.get("layer_types") or []
    while len(lt) < layer_count:
        lt.append(LAYER_TYPE_SLICE)
    lt = lt[:layer_count]

    lo = meta.get("layer_object_ids") or []
    while len(lo) < layer_count:
        lo.append(None)
    lo = lo[:layer_count]

    ol = meta.get("object_layers")
    if not isinstance(ol, list):
        ol = []

    return {"layer_types": lt, "layer_object_ids": lo, "object_layers": ol}


def default_scene_metadata(layer_count: int) -> dict:
    """
    Return a default scene metadata dict for *layer_count* layers.
    Used when loading v1 projects that have no scene block.
    """
    oid = _new_object_id()
    return {
        "layer_types":     [LAYER_TYPE_SLICE] * layer_count,
        "layer_object_ids": [oid] * layer_count,
        "object_layers":   [{"id": oid, "name": "Stack 1", "type": "stack"}],
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _layout_dimensions(payload: dict | list) -> tuple[float, float]:
    if not isinstance(payload, dict):
        return 1.0, 1.0
    layout = payload.get("level") or payload.get("layout") or payload.get("map") or payload.get("scene") or {}
    if not isinstance(layout, dict):
        layout = {}
    width = (
        payload.get("width")
        or payload.get("level_width")
        or layout.get("width")
        or layout.get("level_width")
        or 1.0
    )
    height = (
        payload.get("height")
        or payload.get("level_height")
        or layout.get("height")
        or layout.get("level_height")
        or 1.0
    )
    return max(1.0, _to_float(width, 1.0)), max(1.0, _to_float(height, 1.0))


def _normalize_axis_value(value: Any, extent: float, default: float) -> float:
    raw = _to_float(value, default)
    if abs(raw) > 1.0 and extent > 1.0:
        raw = raw / extent
    return _clamp01(raw)


def _normalize_position(item: dict, layout_width: float = 1.0, layout_height: float = 1.0) -> tuple[float, float]:
    x = item.get("x", item.get("normalized_x"))
    y = item.get("y", item.get("normalized_y"))
    position = item.get("position", item.get("anchor"))
    rect = item.get("rect") or item.get("bbox") or item.get("bounds")

    if isinstance(rect, dict):
        x = rect.get("x", rect.get("left", x))
        y = rect.get("y", rect.get("top", y))
    elif isinstance(rect, (list, tuple)) and len(rect) >= 2:
        x, y = rect[0], rect[1]

    if isinstance(position, str):
        key = position.strip().lower()
        if key in _ANCHOR_TO_NORMALIZED:
            return _ANCHOR_TO_NORMALIZED[key]
        if "," in key:
            parts = [p.strip() for p in key.split(",")]
            if len(parts) == 2:
                x, y = parts[0], parts[1]
    elif isinstance(position, dict):
        x = position.get("x", x)
        y = position.get("y", y)

    if isinstance(x, str):
        x = _H_ANCHORS.get(x.strip().lower(), x)
    if isinstance(y, str):
        y = _V_ANCHORS.get(y.strip().lower(), y)

    nx = _normalize_axis_value(x, layout_width, 0.5)
    ny = _normalize_axis_value(y, layout_height, 0.5)
    return nx, ny


def _normalize_size(item: dict, layout_width: float = 1.0, layout_height: float = 1.0) -> tuple[float, float]:
    rect = item.get("rect") or item.get("bbox") or item.get("bounds")
    size = item.get("size") or item.get("dimensions")
    w = item.get("w", item.get("width"))
    h = item.get("h", item.get("height"))

    if isinstance(rect, dict):
        w = rect.get("w", rect.get("width", w))
        h = rect.get("h", rect.get("height", h))
    elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
        if item.get("bbox") is rect:
            x0 = _to_float(rect[0], 0.0)
            y0 = _to_float(rect[1], 0.0)
            x1 = _to_float(rect[2], 0.0)
            y1 = _to_float(rect[3], 0.0)
            if x1 > x0 and y1 > y0:
                w, h = x1 - x0, y1 - y0
            else:
                w, h = rect[2], rect[3]
        else:
            w, h = rect[2], rect[3]

    if isinstance(size, dict):
        w = size.get("w", size.get("width", w))
        h = size.get("h", size.get("height", h))
    elif isinstance(size, (list, tuple)) and len(size) >= 2:
        w, h = size[0], size[1]

    nw = _normalize_axis_value(w, layout_width, 0.12)
    nh = _normalize_axis_value(h, layout_height, 0.12)
    return max(0.001, min(1.0, nw)), max(0.001, min(1.0, nh))


def _extract_layout_items(payload: dict | list) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    candidates = [
        payload.get("placements"),
        payload.get("objects"),
        payload.get("entities"),
        payload.get("sprites"),
        payload.get("tiles"),
        payload.get("platforms"),
        payload.get("items"),
    ]
    for key in ("level", "layout", "map", "scene", "level_layout"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("placements"),
                nested.get("objects"),
                nested.get("entities"),
                nested.get("sprites"),
                nested.get("tiles"),
                nested.get("platforms"),
                nested.get("items"),
            ])
        elif isinstance(nested, list):
            candidates.append(nested)
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def parse_ai_scene_payload(payload: dict | list) -> list[dict]:
    """
    Parse a /parse-scene response into normalised placement items.
    Supports both named-entity scene parser payloads and level-layout payloads.
    Each result includes: name, type, normalized_x, normalized_y, size_w, size_h,
    depth, scale, rotation, opacity, visible.
    """
    layout_width, layout_height = _layout_dimensions(payload)
    raw_items = _extract_layout_items(payload)

    parsed: list[dict] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name")
            or item.get("object")
            or item.get("sprite")
            or item.get("label")
            or item.get("tile")
            or item.get("prefab")
            or item.get("asset")
            or item.get("class")
            or item.get("category")
            or f"Sprite {idx + 1}"
        ).strip()
        obj_type = str(item.get("type") or "sprite").strip().lower()
        nx, ny = _normalize_position(item, layout_width, layout_height)
        nw, nh = _normalize_size(item, layout_width, layout_height)
        if item.get("rect") is not None or item.get("bbox") is not None or item.get("bounds") is not None:
            nx = _clamp01(nx + nw / 2.0)
            ny = _clamp01(ny + nh / 2.0)
        parsed.append({
            "name": name or f"Sprite {idx + 1}",
            "type": obj_type if obj_type in OBJECT_TYPES else OBJECT_TYPE_SPRITE,
            "normalized_x": nx,
            "normalized_y": ny,
            "size_w": nw,
            "size_h": nh,
            "depth": _to_float(item.get("depth", item.get("z", item.get("layer", idx))), float(idx)),
            "scale": max(0.01, _to_float(item.get("scale", 1.0), 1.0)),
            "rotation": _to_float(item.get("rotation", 0.0), 0.0),
            "opacity": max(0, min(255, _to_int(item.get("opacity", 255), 255))),
            "visible": bool(item.get("visible", True)),
            "scene_type": str(item.get("scene_type") or item.get("theme") or "default").strip().lower(),
        })
    return parsed


def apply_ai_scene_layout(
    manager: "SceneManager",
    scene_id: str | None,
    placements: list[dict],
    resolve_object_id: Callable[[dict], str | None],
    canvas_width: int,
    canvas_height: int,
    target_screen: int = 0,
    num_screens: int = 1,
) -> list["ObjectPlacement"]:
    """
    Apply parsed AI placement data to a scene. Positions are interpreted as
    normalized coordinates (0..1) and converted to scene offsets.
    """
    scene = manager.get_scene(scene_id) if scene_id else manager.get_active_scene()
    if scene is None:
        return []

    target_screen = max(0, int(target_screen or 0))
    num_screens = max(1, int(num_screens or 1))
    if num_screens > 1:
        remaining_placements = []
        for p in scene.placements:
            nx = max(0.0, min(1.0, 0.5 + p.offset_x / max(1.0, float(canvas_width))))
            col_global = int(nx * 16 * num_screens)
            obj_screen = max(0, min(num_screens - 1, col_global // 16))
            if obj_screen != target_screen:
                remaining_placements.append(p)
        scene.placements = remaining_placements

    applied: list[ObjectPlacement] = []
    for item in placements:
        object_id = resolve_object_id(item)
        if not object_id:
            continue
        should_create_new_placement = (
            num_screens > 1
            or item.get("size_w") is not None
            or item.get("size_h") is not None
        )
        if should_create_new_placement:
            placement = scene.add_object(object_id)
        else:
            placement = scene.get_placement(object_id)
            if placement is None:
                placement = scene.add_object(object_id)

        local_x = _clamp01(_to_float(item.get("normalized_x", 0.5), 0.5))
        nx = (target_screen + local_x) / float(num_screens)
        ny = _clamp01(_to_float(item.get("normalized_y", 0.5), 0.5))
        placement.offset_x = (nx - 0.5) * float(canvas_width)
        placement.offset_y = (ny - 0.5) * float(canvas_height)
        default_w = 0.0625 / float(num_screens) if num_screens > 1 else 0.12
        default_h = 0.0625 if num_screens > 1 else 0.12
        placement.size_w = max(0.001, min(1.0, _to_float(item.get("size_w", default_w), default_w)))
        placement.size_h = max(0.001, min(1.0, _to_float(item.get("size_h", default_h), default_h)))
        placement.offset_z = _to_float(item.get("depth", item.get("offset_z", 0.0)), 0.0)
        placement.scale = max(0.01, _to_float(item.get("scale", 1.0), 1.0))
        placement.rotation = _to_float(item.get("rotation", 0.0), 0.0)
        placement.opacity = max(0, min(255, _to_int(item.get("opacity", 255), 255)))
        placement.visible = bool(item.get("visible", True))
        applied.append(placement)

    return applied


# ---------------------------------------------------------------------------
# LayerData — one layer inside an object
# ---------------------------------------------------------------------------

class LayerData:
    """Serialisable data for a single layer / slice."""

    __slots__ = ("name", "image", "visible", "opacity", "locked", "blend_mode")

    def __init__(
        self,
        name: str = "Base",
        image: QImage | None = None,
        visible: bool = True,
        opacity: int = 255,
        locked: bool = False,
        blend_mode: str = "Normal",
    ):
        self.name = name
        self.image = image
        self.visible = visible
        self.opacity = opacity
        self.locked = locked
        self.blend_mode = blend_mode

    def copy(self) -> "LayerData":
        return LayerData(
            name=self.name,
            image=self.image.copy() if self.image else None,
            visible=self.visible,
            opacity=self.opacity,
            locked=self.locked,
            blend_mode=self.blend_mode,
        )


# ---------------------------------------------------------------------------
# SceneObject — sprite, texture, or stack
# ---------------------------------------------------------------------------

class SceneObject:
    """One object in the scene hierarchy."""

    def __init__(
        self,
        obj_id: str | None = None,
        name: str = "Object",
        obj_type: str = OBJECT_TYPE_SPRITE,
        canvas_width: int = 64,
        canvas_height: int = 64,
    ):
        self.id: str = obj_id or _new_object_id()
        self.name: str = name
        self.obj_type: str = obj_type if obj_type in OBJECT_TYPES else OBJECT_TYPE_SPRITE
        self.canvas_width: int = canvas_width
        self.canvas_height: int = canvas_height
        self.layers: List[LayerData] = []
        self.active_layer: int = 0
        self.visible: bool = True
        # Animation frames: list of list-of-QImage snapshots
        self.frames: list = []
        self.current_frame: int = 0

    # -- helpers --

    def add_default_layer(self, name: str = "Base"):
        """Append a blank transparent layer to this object."""
        img = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        self.layers.append(LayerData(name=name, image=img))

    def layer_names(self) -> List[str]:
        return [l.name for l in self.layers]

    def layer_images(self) -> List[QImage]:
        return [l.image for l in self.layers]

    def layer_visible_list(self) -> List[bool]:
        return [l.visible for l in self.layers]

    def layer_opacity_list(self) -> List[int]:
        return [l.opacity for l in self.layers]

    def layer_locked_list(self) -> List[bool]:
        return [l.locked for l in self.layers]

    def layer_blend_list(self) -> List[str]:
        return [l.blend_mode for l in self.layers]

    @property
    def type_label(self) -> str:
        return {"stack": "Stack", "sprite": "Sprite", "texture": "Texture"}.get(
            self.obj_type, "Object"
        )

    @property
    def layer_label(self) -> str:
        """Label for layers depending on type ('Slices' for stack, else 'Layers')."""
        return "Slices" if self.obj_type == OBJECT_TYPE_STACK else "Layers"


# ---------------------------------------------------------------------------
# SceneModel — full scene
# ---------------------------------------------------------------------------

class SceneModel:
    """
    Manages multiple SceneObjects and tracks the active one.
    """

    def __init__(self, project_name: str = "Untitled Project"):
        self.project_name: str = project_name
        self.objects: List[SceneObject] = []
        self.active_object_id: Optional[str] = None

    # -- object CRUD --

    def add_object(
        self,
        name: str,
        obj_type: str,
        width: int,
        height: int,
        initial_layers: int = 1,
    ) -> SceneObject:
        obj = SceneObject(
            name=name,
            obj_type=obj_type,
            canvas_width=width,
            canvas_height=height,
        )
        for i in range(max(1, initial_layers)):
            lbl = "Base" if i == 0 else f"{'Slice' if obj_type == OBJECT_TYPE_STACK else 'Layer'} {i + 1}"
            obj.add_default_layer(lbl)
        self.objects.append(obj)
        if self.active_object_id is None:
            self.active_object_id = obj.id
        return obj

    def remove_object(self, obj_id: str) -> bool:
        idx = self._index_of(obj_id)
        if idx is None:
            return False
        self.objects.pop(idx)
        if self.active_object_id == obj_id:
            self.active_object_id = self.objects[0].id if self.objects else None
        return True

    def get_object(self, obj_id: str) -> Optional[SceneObject]:
        for o in self.objects:
            if o.id == obj_id:
                return o
        return None

    def get_active_object(self) -> Optional[SceneObject]:
        return self.get_object(self.active_object_id) if self.active_object_id else None

    def rename_object(self, obj_id: str, new_name: str) -> bool:
        obj = self.get_object(obj_id)
        if obj:
            obj.name = new_name.strip() or obj.name
            return True
        return False

    def move_object(self, from_idx: int, to_idx: int) -> bool:
        if 0 <= from_idx < len(self.objects) and 0 <= to_idx < len(self.objects):
            o = self.objects.pop(from_idx)
            self.objects.insert(to_idx, o)
            return True
        return False

    def convert_object_type(self, obj_id: str, new_type: str) -> bool:
        if new_type not in OBJECT_TYPES:
            return False
        obj = self.get_object(obj_id)
        if not obj:
            return False
        # Only sprite <-> texture conversion allowed directly
        if obj.obj_type == OBJECT_TYPE_STACK and new_type != OBJECT_TYPE_STACK:
            return False  # stack conversion not supported (would lose 3D data)
        if new_type == OBJECT_TYPE_STACK and obj.obj_type != OBJECT_TYPE_STACK:
            return False
        obj.obj_type = new_type
        return True

    # -- layer operations (delegate to object) --

    def add_layer(self, obj_id: str, name: str = "Layer") -> bool:
        obj = self.get_object(obj_id)
        if not obj:
            return False
        obj.add_default_layer(name)
        return True

    def remove_layer(self, obj_id: str, layer_idx: int) -> bool:
        obj = self.get_object(obj_id)
        if not obj or len(obj.layers) <= 1:
            return False
        if 0 <= layer_idx < len(obj.layers):
            obj.layers.pop(layer_idx)
            if obj.active_layer >= len(obj.layers):
                obj.active_layer = len(obj.layers) - 1
            return True
        return False

    def rename_layer(self, obj_id: str, layer_idx: int, new_name: str) -> bool:
        obj = self.get_object(obj_id)
        if obj and 0 <= layer_idx < len(obj.layers):
            obj.layers[layer_idx].name = new_name.strip() or obj.layers[layer_idx].name
            return True
        return False

    def move_layer(self, obj_id: str, from_idx: int, to_idx: int) -> bool:
        obj = self.get_object(obj_id)
        if not obj:
            return False
        if 0 <= from_idx < len(obj.layers) and 0 <= to_idx < len(obj.layers):
            layer = obj.layers.pop(from_idx)
            obj.layers.insert(to_idx, layer)
            return True
        return False

    def duplicate_layer(self, obj_id: str, layer_idx: int) -> bool:
        obj = self.get_object(obj_id)
        if not obj or not (0 <= layer_idx < len(obj.layers)):
            return False
        dup = obj.layers[layer_idx].copy()
        dup.name = dup.name + " copy"
        obj.layers.insert(layer_idx + 1, dup)
        return True

    # -- query --

    def _index_of(self, obj_id: str) -> Optional[int]:
        for i, o in enumerate(self.objects):
            if o.id == obj_id:
                return i
        return None

    def object_count(self) -> int:
        return len(self.objects)

    def object_ids(self) -> List[str]:
        return [o.id for o in self.objects]


# ---------------------------------------------------------------------------
# ObjectPlacement — represents an object's state within a scene
# ---------------------------------------------------------------------------

class ObjectPlacement:
    """
    Stores a reference to a global object along with its transform state
    within a specific scene (position, rotation, scale, visibility).
    The actual object data (layers, images) lives in the Create section.
    """

    def __init__(
        self,
        object_id: str,
        placement_id: str | None = None,
        visible: bool = True,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        offset_z: float = 0.0,
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: int = 255,
        size_w: float = 0.12,
        size_h: float = 0.12,
    ):
        self.id: str = placement_id or f"pmt_{uuid.uuid4().hex[:8]}"
        self.object_id: str = object_id  # Reference to global object
        self.visible: bool = visible
        self.offset_x: float = offset_x
        self.offset_y: float = offset_y
        self.offset_z: float = offset_z  # For depth ordering
        self.scale: float = scale
        self.rotation: float = rotation  # In degrees
        self.opacity: int = opacity
        self.size_w: float = size_w
        self.size_h: float = size_h

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "object_id": self.object_id,
            "visible": self.visible,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "offset_z": self.offset_z,
            "scale": self.scale,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "size_w": self.size_w,
            "size_h": self.size_h,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ObjectPlacement":
        return cls(
            object_id=data.get("object_id", ""),
            placement_id=data.get("id"),
            visible=data.get("visible", True),
            offset_x=data.get("offset_x", 0.0),
            offset_y=data.get("offset_y", 0.0),
            offset_z=data.get("offset_z", 0.0),
            scale=data.get("scale", 1.0),
            rotation=data.get("rotation", 0.0),
            opacity=data.get("opacity", 255),
            size_w=data.get("size_w", 0.12),
            size_h=data.get("size_h", 0.12),
        )

    def copy(self) -> "ObjectPlacement":
        """Create a deep copy of this placement with a new unique placement ID."""
        return ObjectPlacement(
            object_id=self.object_id,
            visible=self.visible,
            offset_x=self.offset_x,
            offset_y=self.offset_y,
            offset_z=self.offset_z,
            scale=self.scale,
            rotation=self.rotation,
            opacity=self.opacity,
            size_w=self.size_w,
            size_h=self.size_h,
        )


# ---------------------------------------------------------------------------
# Scene — saved arrangement of objects in the sandbox
# ---------------------------------------------------------------------------

class Scene:
    """
    A scene represents a saved state of the sandbox.
    It contains placements (references + transforms) for global objects.
    Objects themselves are defined in the Create section.
    """

    def __init__(
        self,
        scene_id: str | None = None,
        name: str = "Scene",
        description: str = "",
    ):
        self.id: str = scene_id or _new_scene_id()
        self.name: str = name
        self.description: str = description
        self.placements: List[ObjectPlacement] = []  # Object placements in this scene
        # Scene camera/view settings
        self.camera_rotation: float = 45.0
        self.camera_tilt: float = 30.0
        self.camera_zoom: float = 1.0
        self.background_color: Optional[tuple] = None

    def add_object(self, object_id: str, **kwargs) -> ObjectPlacement:
        """Add an object placement to this scene."""
        placement = ObjectPlacement(object_id=object_id, **kwargs)
        self.placements.append(placement)
        return placement

    def remove_object(self, object_id: str) -> bool:
        """Remove an object placement from this scene."""
        idx = self._index_of(object_id)
        if idx is None:
            return False
        self.placements.pop(idx)
        return True

    def remove_placement_by_id(self, placement_id: str) -> bool:
        """Remove a placement by its unique ID."""
        for idx, p in enumerate(self.placements):
            if p.id == placement_id:
                self.placements.pop(idx)
                return True
        return False

    def get_placement(self, object_id: str) -> Optional[ObjectPlacement]:
        """Get the placement for a specific object."""
        for p in self.placements:
            if p.object_id == object_id:
                return p
        return None

    def get_placement_by_id(self, placement_id: str) -> Optional[ObjectPlacement]:
        """Get the placement by its unique placement ID."""
        for p in self.placements:
            if p.id == placement_id:
                return p
        return None

    def set_placement(self, object_id: str, **kwargs) -> bool:
        """Update placement values for an object."""
        p = self.get_placement(object_id)
        if not p:
            return False
        for key, value in kwargs.items():
            if hasattr(p, key):
                setattr(p, key, value)
        return True

    def _index_of(self, object_id: str) -> Optional[int]:
        """Get the index of a placement by object ID."""
        for i, p in enumerate(self.placements):
            if p.object_id == object_id:
                return i
        return None

    def to_dict(self) -> dict:
        """Serialize scene to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "placements": [p.to_dict() for p in self.placements],
            "camera_rotation": self.camera_rotation,
            "camera_tilt": self.camera_tilt,
            "camera_zoom": self.camera_zoom,
            "background_color": self.background_color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scene":
        """Deserialize scene from dictionary."""
        scene = cls(
            scene_id=data.get("id"),
            name=data.get("name", "Scene"),
            description=data.get("description", ""),
        )
        scene.camera_rotation = data.get("camera_rotation", 45.0)
        scene.camera_tilt = data.get("camera_tilt", 30.0)
        scene.camera_zoom = data.get("camera_zoom", 1.0)
        scene.background_color = data.get("background_color")
        for p_data in data.get("placements", []):
            scene.placements.append(ObjectPlacement.from_dict(p_data))
        return scene


# ---------------------------------------------------------------------------
# SceneManager — manages multiple sandbox scenes
# ---------------------------------------------------------------------------

class SceneManager:
    """
    Manages multiple scenes (saved sandbox arrangements).
    Objects are defined globally in the Create section;
    scenes only store their placement/transform state.
    """

    def __init__(self):
        self.scenes: List[Scene] = []
        self.active_scene_id: Optional[str] = None
        self._project_name: str = "Untitled Project"

    @property
    def project_name(self) -> str:
        return self._project_name

    @project_name.setter
    def project_name(self, value: str):
        self._project_name = value.strip() or "Untitled Project"

    def add_scene(self, name: str = "Scene", description: str = "") -> Scene:
        """Add a new scene."""
        scene = Scene(name=name, description=description)
        self.scenes.append(scene)
        if self.active_scene_id is None:
            self.active_scene_id = scene.id
        return scene

    def remove_scene(self, scene_id: str) -> bool:
        """Remove a scene."""
        idx = self._index_of(scene_id)
        if idx is None:
            return False
        self.scenes.pop(idx)
        if self.active_scene_id == scene_id:
            self.active_scene_id = self.scenes[0].id if self.scenes else None
        return True

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """Get a scene by ID."""
        for s in self.scenes:
            if s.id == scene_id:
                return s
        return None

    def get_active_scene(self) -> Optional[Scene]:
        """Get the active scene."""
        return self.get_scene(self.active_scene_id) if self.active_scene_id else None

    def set_active_scene(self, scene_id: str) -> bool:
        """Set the active scene."""
        if self.get_scene(scene_id):
            self.active_scene_id = scene_id
            return True
        return False

    def rename_scene(self, scene_id: str, new_name: str) -> bool:
        """Rename a scene."""
        scene = self.get_scene(scene_id)
        if scene:
            scene.name = new_name.strip() or scene.name
            return True
        return False

    def duplicate_scene(self, scene_id: str) -> Optional[Scene]:
        """Duplicate a scene with all its placements."""
        scene = self.get_scene(scene_id)
        if not scene:
            return None
        new_scene = Scene(name=f"{scene.name} Copy", description=scene.description)
        new_scene.camera_rotation = scene.camera_rotation
        new_scene.camera_tilt = scene.camera_tilt
        new_scene.camera_zoom = scene.camera_zoom
        new_scene.background_color = scene.background_color
        # Copy placements
        for p in scene.placements:
            new_scene.placements.append(p.copy())
        self.scenes.append(new_scene)
        return new_scene

    def scene_count(self) -> int:
        return len(self.scenes)

    def _index_of(self, scene_id: str) -> Optional[int]:
        for i, s in enumerate(self.scenes):
            if s.id == scene_id:
                return i
        return None

    def to_dict(self) -> dict:
        """Serialize all scenes."""
        return {
            "version": SCHEMA_VERSION,
            "project_name": self._project_name,
            "active_scene_id": self.active_scene_id,
            "scenes": [s.to_dict() for s in self.scenes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SceneManager":
        """Deserialize SceneManager."""
        manager = cls()
        manager._project_name = data.get("project_name", "Untitled Project")
        manager.active_scene_id = data.get("active_scene_id")
        for scene_data in data.get("scenes", []):
            manager.scenes.append(Scene.from_dict(scene_data))
        return manager
