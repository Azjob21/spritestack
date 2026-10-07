"""
Project save/load system for SpriteStack Studio.
Saves/loads .sss (SpriteStack Studio) project files using JSON + PNG layers.
"""

import os
import json
import zipfile
import tempfile
from PyQt5.QtGui import QImage, QColor, QPainter
from PyQt5.QtCore import Qt, QBuffer, QByteArray, QIODevice
from app.scene_model import SCHEMA_VERSION, default_scene_metadata, normalize_scene_metadata


PROJECT_VERSION = 3
PROJECT_EXTENSION = ".sss"


def save_project(filepath, canvas, scene_manager=None, sandbox_state=None):
    """
    Save entire project state to a .sss file (ZIP archive).
    Contains:
      - project.json : metadata, layer info, animation info, scene data
      - layers/frame_XXXX_layer_YYYY.png : layer images for each frame
      - layers/source_layer_YYYY.png : untransformed source images (sandbox)

    Writes to a temporary file first, then renames atomically so that an
    error (e.g. disk full) never corrupts the existing save file.
    """
    canvas.save_current_frame()

    project_data = {
        "version": PROJECT_VERSION,
        "canvas_width": canvas.canvas_width,
        "canvas_height": canvas.canvas_height,
        "layer_names": canvas.layer_names,
        "layer_visible": canvas.layer_visible,
        "layer_opacity": canvas.layer_opacity,
        "layer_locked": canvas.layer_locked,
        "active_layer": canvas.active_layer,
        "current_frame": canvas.current_frame,
        "frame_count": len(canvas.frames),
    }

    # Store project-level metadata from SceneManager
    if scene_manager is not None:
        project_data["project_name"] = getattr(scene_manager, "project_name", "Untitled Project")
        # NEW: Save multi-scene data
        project_data["scenes"] = scene_manager.to_dict()
    else:
        project_data["project_name"] = "Untitled Project"

    scene_meta = normalize_scene_metadata(
        {
            "layer_types": getattr(canvas, "layer_types", []),
            "layer_object_ids": getattr(canvas, "layer_object_ids", []),
            "object_layers": getattr(canvas, "object_layers", []),
        },
        len(canvas.layer_names),
    )
    project_data["scene"] = scene_meta
    project_data["scene_schema"] = SCHEMA_VERSION

    # Save sandbox transform state
    if sandbox_state:
        transforms = {}
        for layer_idx, st in sandbox_state.items():
            transforms[str(layer_idx)] = {
                "tx": st.get("tx", 0.0),
                "ty": st.get("ty", 0.0),
                "scale": st.get("scale", 1.0),
                "rot": st.get("rot", 0.0),
                "opacity": st.get("opacity", 255),
            }
        project_data["sandbox_transforms"] = transforms

    # Write to a sibling temp file; rename into place only on full success.
    dir_name = os.path.dirname(os.path.abspath(filepath))
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".sss.tmp")
    try:
        os.close(tmp_fd)
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(project_data, indent=2))

            for frame_idx, frame_layers in enumerate(canvas.frames):
                for layer_idx, layer_img in enumerate(frame_layers):
                    png_data = _qimage_to_png_bytes(layer_img)
                    zf.writestr(
                        f"layers/frame_{frame_idx:04d}_layer_{layer_idx:04d}.png",
                        png_data
                    )

            # Save untransformed source images for sandbox transforms
            if sandbox_state:
                for layer_idx, st in sandbox_state.items():
                    source_img = st.get("source")
                    if source_img is not None and not source_img.isNull():
                        has_transform = (
                            abs(st.get("tx", 0)) > 1e-9 or
                            abs(st.get("ty", 0)) > 1e-9 or
                            abs(st.get("rot", 0)) > 1e-9 or
                            abs(st.get("scale", 1) - 1.0) > 1e-9
                        )
                        if has_transform:
                            png_data = _qimage_to_png_bytes(source_img)
                            zf.writestr(
                                f"layers/source_layer_{int(layer_idx):04d}.png",
                                png_data
                            )

        os.replace(tmp_path, filepath)   # atomic on POSIX; best-effort on Windows
    except Exception:
        # Clean up the partial temp file before re-raising
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_project(filepath, canvas, scene_manager=None):
    """
    Load project state from a .sss file.
    Returns a dict with 'success' (bool) and optionally 'sandbox_transforms'.

    Canvas state is only mutated after the entire archive has been read
    successfully, so a corrupt or truncated file leaves the canvas intact.
    """
    if not os.path.exists(filepath):
        return {"success": False}

    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            project_data = json.loads(zf.read("project.json"))

            file_version = project_data.get("version", 1)
            if file_version > PROJECT_VERSION:
                print(f"Warning: project was saved with a newer format version "
                      f"({file_version} > {PROJECT_VERSION}). Some data may be lost.")

            cw = project_data["canvas_width"]
            ch = project_data["canvas_height"]
            layer_names = project_data["layer_names"]
            layer_visible = project_data["layer_visible"]
            layer_opacity = project_data["layer_opacity"]
            layer_locked = project_data.get("layer_locked", [False] * len(layer_names))
            active_layer = project_data["active_layer"]
            current_frame = project_data["current_frame"]
            frame_count = project_data["frame_count"]
            num_layers = len(layer_names)

            # Load multi-scene data if present (new format)
            scenes_data = project_data.get("scenes")

            if "scene" in project_data:
                scene_meta = normalize_scene_metadata(project_data.get("scene"), num_layers)
            else:
                # v1 migration path
                scene_meta = default_scene_metadata(num_layers)

            # Read all frame images before touching canvas state
            frames = []
            for frame_idx in range(frame_count):
                frame_layers = []
                for layer_idx in range(num_layers):
                    png_path = (f"layers/frame_{frame_idx:04d}"
                                f"_layer_{layer_idx:04d}.png")
                    try:
                        png_data = zf.read(png_path)
                        img = _png_bytes_to_qimage(png_data)
                    except (KeyError, ValueError):
                        # Missing or corrupt layer -> blank image
                        img = QImage(cw, ch, QImage.Format_ARGB32)
                        img.fill(QColor(0, 0, 0, 0))
                    frame_layers.append(img)
                frames.append(frame_layers)

            # Read sandbox transforms and source images
            sandbox_transforms = {}
            raw_transforms = project_data.get("sandbox_transforms", {})
            for layer_key, tdata in raw_transforms.items():
                layer_idx = int(layer_key)
                source_path = f"layers/source_layer_{layer_idx:04d}.png"
                source_img = None
                try:
                    source_data = zf.read(source_path)
                    source_img = _png_bytes_to_qimage(source_data)
                except (KeyError, ValueError):
                    pass
                sandbox_transforms[layer_idx] = {
                    "tx": tdata.get("tx", 0.0),
                    "ty": tdata.get("ty", 0.0),
                    "scale": tdata.get("scale", 1.0),
                    "rot": tdata.get("rot", 0.0),
                    "opacity": tdata.get("opacity", 255),
                    "source": source_img,
                }

        # ---- All data loaded; now mutate canvas ----
        canvas.canvas_width = cw
        canvas.canvas_height = ch
        canvas.layer_names = layer_names
        canvas.layer_visible = layer_visible
        canvas.layer_opacity = layer_opacity
        canvas.layer_locked = layer_locked
        canvas.layer_types = list(scene_meta["layer_types"])
        canvas.layer_object_ids = list(scene_meta["layer_object_ids"])
        canvas.object_layers = [dict(o) for o in scene_meta["object_layers"]]
        canvas.frames = frames

        # Clamp indices to valid ranges before using them
        canvas.current_frame = max(0, min(current_frame, len(frames) - 1))
        canvas.active_layer = max(0, min(active_layer, num_layers - 1))

        canvas._restore_layers(canvas.frames[canvas.current_frame])
        if hasattr(canvas, "sync_scene_metadata"):
            canvas.sync_scene_metadata()

        # Restore project-level metadata to SceneManager
        if scene_manager is not None:
            scene_manager.project_name = project_data.get("project_name", "Untitled Project")
            # NEW: Restore multi-scene data if present
            if scenes_data:
                from app.scene_model import SceneManager as SM, Scene as SC
                # Create new SceneManager from saved data
                new_manager = SM.from_dict(scenes_data)
                # Copy data to the provided scene_manager
                scene_manager.scenes = new_manager.scenes
                scene_manager.active_scene_id = new_manager.active_scene_id
                scene_manager.project_name = new_manager.project_name

        canvas.update()
        return {"success": True, "sandbox_transforms": sandbox_transforms}

    except Exception as e:
        print(f"Error loading project: {e}")
        return {"success": False}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _qimage_to_png_bytes(qimage):
    """Convert QImage to PNG bytes. Raises ValueError on a null or save-failed image."""
    if qimage is None or qimage.isNull():
        raise ValueError("Cannot serialise a null QImage")
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    ok = qimage.save(buf, "PNG")
    buf.close()
    if not ok:
        raise ValueError("QImage.save() failed — image may be invalid")
    return bytes(ba)


def _png_bytes_to_qimage(png_bytes):
    """Convert PNG bytes to QImage. Raises ValueError if the data cannot be decoded."""
    ba = QByteArray(png_bytes)
    img = QImage()
    ok = img.loadFromData(ba, "PNG")
    if not ok or img.isNull():
        raise ValueError("Failed to decode PNG data")
    return img.convertToFormat(QImage.Format_ARGB32)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_layers_as_stack_image(canvas, filepath, scale=1):
    """
    Export the current frame's layers as a single vertical strip PNG.
    Each layer occupies one tile of (canvas_width*scale) × (canvas_height*scale).
    Returns True on success, False on failure.
    """
    # Use the current frame's layers, not the ambiguous canvas.layers attribute
    if not canvas.frames:
        return False
    layers = canvas.frames[canvas.current_frame]
    if not layers:
        return False

    w = canvas.canvas_width * scale
    h = canvas.canvas_height * scale
    total_h = h * len(layers)

    result = QImage(w, total_h, QImage.Format_ARGB32)
    result.fill(QColor(0, 0, 0, 0))

    painter = QPainter(result)
    for i, layer in enumerate(layers):
        # IgnoreAspectRatio + FastTransformation preserves pixel-art fidelity
        scaled = layer.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        painter.drawImage(0, i * h, scaled)
    painter.end()

    ok = result.save(filepath, "PNG")
    return ok
