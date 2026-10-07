"""
Canvas widget for pixel art editing with zoom, pan, grid, drawing, selection,
copy/paste, magic-wand selection, move tool, multiple brush shapes, and onion skinning.

Bugs fixed vs original:
  1. UndoStack.undo() double-pushes: the current state was being pushed to redo inside
     PixelCanvas.undo() AND undo_stack.undo() pops from undo → caused redo corruption.
     Fixed: undo/redo are handled entirely by UndoStack; PixelCanvas delegates cleanly.
  2. setSizePolicy() created a throwaway QWidget() to call sizePolicy() on — memory leak
     and wrong policy source. Fixed with explicit QSizePolicy import.
  3. resize_canvas() only resizes the *active* frame's layers, not all frames. Fixed.
  4. onion_skin_opacity treated as 0–255 in some places and 0–100 in others (timeline
     emits 0–100, canvas divides by 255). Normalised to 0–100 throughout.
  5. flood_fill() uses an unbounded Python stack — deep fills on large canvases cause
     RecursionError. Replaced with an explicit iterative queue (collections.deque).
  6. magic_wand_select tolerance multiplied by 4 without justification; diff calculation
     already sums 4 channels. Corrected to compare directly.
  7. _ctx_move() duplicates the "lift selection" logic already in mousePressEvent move
     handler — they can diverge. Extracted to a shared _lift_selection() helper.
  8. get_flat_frame() divides layer_opacity[i] by 255.0 but layer_opacity stores 0–255,
     which is correct. However if a frame has more layers than layer_visible (can happen
     after project load with mismatched data), index falls off the list. Added guard.
  9. _draw_checker() recalculates and repaints every cell on every repaint even when
     nothing changed. Caches the checker QPixmap and only regenerates on zoom/size change.
  10. pivot drag clamps to canvas bounds (was unclamped — could escape to negative coords).
  11. Right-click eyedropper samples the composited pixel (all layers) not just active layer.
  12. Shape tools (rect, circle) call save_undo_state() on press but if user cancels with
      Escape the undo state is polluted. Undo save moved to finalize.
  13. move_layer() does not update frames — layers in saved frames stay in original order.
      Fixed to reorder in all frames too.
  14. add_layer() / duplicate_layer() / remove_layer() don't update saved frames. Fixed.
  15. _draw_grid() draws (canvas_width+1)*(canvas_height+1) lines even when zoomed out
      far — replaced with viewport-clipped version.

New features:
  • Lasso / freehand selection tool
  • Gradient fill tool (linear, horizontal / vertical / diagonal)
  • Brightness / contrast / hue-shift adjustment via numpy on selection or whole layer
  • clear_frame() — fills active layer with transparent (for timeline integration)
  • insert_frame_before() / insert_frame_after() (for timeline context menu)
  • move_frame() (for timeline drag-reorder)
  • set_onion_skin() convenience method (matches timeline signal signature)
  • Canvas coordinate ruler overlay (optional)
  • Cursor pixel-size preview overlay (brush footprint ghost)
  • keyPressEvent: Escape=deselect/cancel, Delete=clear selection, [ / ] = brush size
  • get_composite_pixel() — samples flattened pixel across all layers (used for eyedropper)
  • Full integration hooks for project.py, timeline.py, preview3d.py documented in methods
"""

import math
import collections
import numpy as np

from app.scene_model import (
    LAYER_TYPE_SLICE,
    normalize_scene_metadata,
)
from PyQt5.QtWidgets import (
    QWidget, QApplication, QPushButton, QHBoxLayout, QVBoxLayout,
    QGraphicsDropShadowEffect, QLabel, QSpinBox, QDialog,
    QDialogButtonBox, QFormLayout, QSizePolicy
)
from PyQt5.QtGui import (
    QPainter, QImage, QColor, QPen, QPixmap, QCursor, QTransform,
    QFont, QBrush, QLinearGradient, QPainterPath, QPolygon
)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal, QTimer, QPointF


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# UndoStack
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class UndoStack:
    """Linear undo/redo stack.

    The caller is responsible for passing the *current in-memory state*
    when calling ``undo`` / ``redo`` so that it can be saved for the
    opposite direction.  ``push`` is called *before* each mutation to
    record the snapshot that undo should restore to.
    """

    def __init__(self, max_size=100):
        self.max_size  = max_size
        self._undo     = []   # stack of "before" snapshots
        self._redo     = []

    def push(self, state):
        """Save *state* (the current snapshot) before a mutation."""
        self._undo.append(state)
        if len(self._undo) > self.max_size:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current_state):
        """Save *current_state* for redo, pop and return the previous state."""
        if not self._undo:
            return None
        self._redo.append(current_state)
        return self._undo.pop()

    def redo(self, current_state):
        """Save *current_state* for undo, pop and return the next state."""
        if not self._redo:
            return None
        self._undo.append(current_state)
        return self._redo.pop()

    def can_undo(self): return bool(self._undo)
    def can_redo(self): return bool(self._redo)
    def clear(self):
        self._undo.clear()
        self._redo.clear()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SelectionContextBar
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class SelectionContextBar(QWidget):
    """Floating toolbar shown above the active selection."""

    move_clicked      = pyqtSignal()
    center_clicked    = pyqtSignal()
    flip_h_clicked    = pyqtSignal()
    flip_v_clicked    = pyqtSignal()
    rotate_cw_clicked = pyqtSignal()
    rotate_ccw_clicked= pyqtSignal()
    scale_clicked     = pyqtSignal()
    deselect_clicked  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        self.setStyleSheet("""
            SelectionContextBar {
                background: #252535;
                border: 1px solid #3a3a4a;
            }
            QPushButton {
                background: #2a2a3c;
                border: 1px solid #3a3a4a;
                color: #c8c8d4;
                font-family: "Courier New";
                font-size: 9pt;
                padding: 3px 7px;
                min-width: 28px;
            }
            QPushButton:hover  { background: #252535; border-color: #44445a; color: #e8e8f0; }
            QPushButton:pressed{ background: #171726; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)
        for text, tip, sig in [
            ("Move",   "Move selection",     self.move_clicked),
            ("Center", "Centre on pivot",    self.center_clicked),
            ("Flip H", "Flip horizontal",    self.flip_h_clicked),
            ("Flip V", "Flip vertical",      self.flip_v_clicked),
            ("Rot CW", "Rotate 90 deg CW",   self.rotate_cw_clicked),
            ("Rot CCW","Rotate 90 deg CCW",  self.rotate_ccw_clicked),
            ("Scale",  "Scale...",           self.scale_clicked),
            ("Done",   "Deselect",           self.deselect_clicked),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedSize(58, 26)
            btn.setFont(QFont("IBM Plex Mono", 9))
            btn.clicked.connect(sig.emit)
            lay.addWidget(btn)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14); shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)
        self.adjustSize()
        self.hide()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PixelCanvas
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class PixelCanvas(QWidget):
    """
    Main pixel-art canvas.

    Integration notes
    -----------------
    • timeline.py  → connect TimelinePanel signals to add_frame / delete_frame /
                      load_frame / insert_frame_before / insert_frame_after /
                      move_frame / clear_frame / set_onion_skin
    • preview3d.py → connect canvas_modified to preview.set_layers(canvas.layers)
                     connect pivot_changed to preview_panel.set_pivot(px/w, py/h)
    • project.py   → save_project(path, canvas) / load_project(path, canvas) work
                     directly on canvas public attributes (frames, layer_*, etc.)
    """

    pixel_clicked       = pyqtSignal(int, int)
    color_picked        = pyqtSignal(object)
    canvas_modified     = pyqtSignal()
    cursor_pos_changed  = pyqtSignal(int, int)
    pivot_changed       = pyqtSignal(int, int)      # normalised pivot for 3D preview
    frame_changed       = pyqtSignal(int, int)      # current_frame, total_frames

    def __init__(self, width=64, height=64, parent=None):
        super().__init__(parent)
        self.canvas_width  = width
        self.canvas_height = height
        self.zoom          = 8.0
        self.min_zoom      = 0.5
        self.max_zoom      = 64.0
        self.offset_x      = 0.0
        self.offset_y      = 0.0

        # Visuals — token-matched to HTML design
        self.show_grid    = True
        self.show_ruler   = False
        self.grid_color   = QColor(58, 58, 74, 48)
        self.bg_color1    = QColor(42, 42, 58)
        self.bg_color2    = QColor(34, 34, 50)
        self.checker_size = 8
        self._checker_cache: QPixmap | None = None
        self._checker_zoom  = -1.0

        # Layers
        self.layers       = []
        self.layer_names  = []
        self.layer_visible= []
        self.layer_opacity= []    # 0–255
        self.layer_locked = []
        self.layer_types = []         # "slice" | "sprite" | "texture"
        self.layer_object_ids = []    # object-group id or None
        self.object_layers = []       # [{"id","name","visible"}]
        self.active_layer = 0
        self._add_initial_layer()

        # Drawing state
        self.current_tool    = "pencil"
        self.primary_color   = QColor(0, 0, 0, 255)
        self.secondary_color = QColor(255, 255, 255, 255)
        self.brush_size      = 1
        self.brush_shape     = "square"   # "square" | "circle" | "diamond"
        self.brush_opacity   = 100          # 0–100 (tool-bar controlled)
        self.brush_hardness  = 100          # 0–100 (tool-bar controlled)
        self.fill_tolerance  = 32           # 0–255 (magic wand / fill)
        self.is_drawing      = False
        self.last_draw_pos   = None
        self.is_panning      = False
        self.pan_start       = None
        self.pan_offset_start= None
        self.mirror_x        = False
        self.mirror_y        = False
        self.symmetry_axis_count = 1
        self.symmetry_inverse = False
        self.symmetry_axis_x = width // 2
        self.symmetry_axis_y = height // 2
        self._drag_symmetry_axis = False
        self._tool_undo_saved= False    # guard: save undo once per stroke

        # Gradient fill
        self.gradient_mode   = "free"   # "free"|"horizontal"|"vertical"|"diagonal"
        self.gradient_start_color = QColor(self.primary_color)
        self.gradient_end_color   = QColor(self.secondary_color)

        # Selection
        self.selection_rect  = None
        self.selection_start = None
        self.is_selecting    = False
        self.selection_mask  = None      # QImage (magic wand / lasso result)
        self._lasso_points   = []        # list[QPoint] for freehand lasso
        self.selection_mode   = "replace" # replace|add|subtract|intersect

        # Pivot
        self.pivot           = (width // 2, height // 2)
        self._is_dragging_pivot = False
        self.show_3d_plane   = False

        # Context bar
        self._context_bar = SelectionContextBar(self)
        self._context_bar.move_clicked.connect(self._ctx_move)
        self._context_bar.center_clicked.connect(self.center_selection_on_pivot)
        self._context_bar.flip_h_clicked.connect(lambda: self.flip_selection(True))
        self._context_bar.flip_v_clicked.connect(lambda: self.flip_selection(False))
        self._context_bar.rotate_cw_clicked.connect(lambda: self.rotate_selection(True))
        self._context_bar.rotate_ccw_clicked.connect(lambda: self.rotate_selection(False))
        self._context_bar.scale_clicked.connect(self._show_scale_dialog)
        self._context_bar.deselect_clicked.connect(self.deselect)

        # Clipboard / floating paste
        self.clipboard_image   = None
        self.clipboard_offset  = (0, 0)
        self._floating_image   = None
        self._floating_offset  = (0, 0)
        self._floating_active  = False

        # Move tool
        self._move_start       = None
        self._move_orig_offset = None
        self._move_layer_content = False
        self._move_original_layer = None

        # Curve tool state
        self._curve_points = []        # list of QPoint for bezier

        # Contour tool (Aseprite-style freehand fill)
        self._contour_points = []

        # Shape preview overlay
        self.preview_overlay   = None
        self.tool_start_pos    = None

        # Onion skinning
        self.onion_skin_enabled = False
        self.onion_skin_frames  = 2
        self.onion_skin_opacity = 50    # 0–100

        # Undo
        self.undo_stack = UndoStack(max_size=100)

        # Widget setup
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Animation frames
        self.frames        = []
        self.current_frame = 0
        self._save_initial_frame()

        # Marching-ants timer
        self._march_offset = 0
        self._march_timer  = QTimer(self)
        self._march_timer.timeout.connect(self._march_ants_tick)
        self._march_timer.start(150)

    # ──────────────────────────────────────────────────────────────────────────
    # Init helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _add_initial_layer(self):
        img = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        self.layers.append(img)
        self.layer_names.append("Layer 1")
        self.layer_visible.append(True)
        self.layer_opacity.append(255)
        self.layer_locked.append(False)
        self.layer_types.append(LAYER_TYPE_SLICE)
        self.layer_object_ids.append(None)

    def _save_initial_frame(self):
        self.frames = [self._copy_layers()]
        # No initial push – save_undo_state() before the first mutation
        # will record the baseline snapshot.

    def sync_scene_metadata(self):
        """Keep typed-layer scene metadata arrays aligned with current layer count."""
        meta = normalize_scene_metadata(
            {
                "layer_types": self.layer_types,
                "layer_object_ids": self.layer_object_ids,
                "object_layers": self.object_layers,
            },
            len(self.layers),
        )
        self.layer_types = meta["layer_types"]
        self.layer_object_ids = meta["layer_object_ids"]
        self.object_layers = meta["object_layers"]

    def _copy_layers(self):
        return [layer.copy() for layer in self.layers]

    def _restore_layers(self, layer_copies):
        restored = [layer.copy() for layer in (layer_copies or []) if layer is not None]

        # Frames should all have the global layer count, but older projects or
        # interrupted edits can leave a saved frame short. Pad instead of
        # restoring an invalid stack so later tools can safely use active_layer.
        expected = max(
            len(restored),
            len(getattr(self, "layer_names", []) or []),
            len(getattr(self, "layer_visible", []) or []),
            len(getattr(self, "layer_opacity", []) or []),
            len(getattr(self, "layer_locked", []) or []),
            len(getattr(self, "layer_types", []) or []),
            len(getattr(self, "layer_object_ids", []) or []),
            1,
        )
        while len(restored) < expected:
            restored.append(self._blank_layer())

        self.layers = restored
        try:
            active = int(self.active_layer)
        except (TypeError, ValueError):
            active = 0
        self.active_layer = max(0, min(active, len(self.layers) - 1))

    # ──────────────────────────────────────────────────────────────────────────
    # Canvas resize
    # ──────────────────────────────────────────────────────────────────────────

    def resize_canvas(self, new_width, new_height):
        """Resize all layers in all frames. Existing pixels kept top-left."""
        def _resize_layer(img):
            new_img = QImage(new_width, new_height, QImage.Format_ARGB32)
            new_img.fill(Qt.transparent)
            p = QPainter(new_img)
            p.drawImage(0, 0, img)
            p.end()
            return new_img

        # Resize active layers
        self.layers = [_resize_layer(l) for l in self.layers]

        # Resize all saved frames
        self.frames = [
            [_resize_layer(l) for l in frame]
            for frame in self.frames
        ]
        # Update active frame reference
        self.frames[self.current_frame] = self._copy_layers()

        self.canvas_width  = new_width
        self.canvas_height = new_height
        self.pivot = (new_width // 2, new_height // 2)
        self._checker_cache = None
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Layer operations  (all keep frames in sync)
    # ──────────────────────────────────────────────────────────────────────────

    def _blank_layer(self):
        img = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img

    def add_layer(self, name=None):
        """Add a blank layer above active_layer. Inserts matching blank in all frames."""
        img = self._blank_layer()
        idx = self.active_layer + 1
        self.layers.insert(idx, img)
        self.layer_names.insert(idx, name or f"Layer {len(self.layers)}")
        self.layer_visible.insert(idx, True)
        self.layer_opacity.insert(idx, 255)
        self.layer_locked.insert(idx, False)
        self.layer_types.insert(idx, LAYER_TYPE_SLICE)
        self.layer_object_ids.insert(idx, None)
        # Insert blank into every other frame too
        for fi, frame in enumerate(self.frames):
            if fi != self.current_frame:
                frame.insert(idx, self._blank_layer())
        self.active_layer = idx
        self.sync_scene_metadata()
        self.update()
        return idx

    def _fit_image_to_canvas(self, image: QImage) -> QImage:
        out = self._blank_layer()
        if image is None or image.isNull():
            return out
        p = QPainter(out)
        if image.width() == self.canvas_width and image.height() == self.canvas_height:
            p.drawImage(0, 0, image)
        else:
            scaled = image.scaled(
                self.canvas_width,
                self.canvas_height,
                Qt.KeepAspectRatio,
                Qt.FastTransformation,
            )
            ox = (self.canvas_width - scaled.width()) // 2
            oy = (self.canvas_height - scaled.height()) // 2
            p.drawImage(ox, oy, scaled)
        p.end()
        return out

    def insert_image_layer(self, image: QImage, name: str = "AI Layer") -> int:
        """Insert an image as a new layer and keep frame/layer structures aligned."""
        if image is None or image.isNull():
            return -1
        self.save_current_frame()
        idx = self.add_layer(name=name)
        if idx < 0:
            return -1
        fitted = self._fit_image_to_canvas(image)
        self.layers[idx] = fitted
        if 0 <= self.current_frame < len(self.frames) and idx < len(self.frames[self.current_frame]):
            self.frames[self.current_frame][idx] = fitted.copy()
        self.active_layer = idx
        self.update()
        self.canvas_modified.emit()
        return idx

    def duplicate_layer(self, index=None):
        if index is None:
            index = self.active_layer
        if not (0 <= index < len(self.layers)):
            return -1
        idx = index + 1
        self.layers.insert(idx, self.layers[index].copy())
        self.layer_names.insert(idx, self.layer_names[index] + " copy")
        self.layer_visible.insert(idx, self.layer_visible[index])
        self.layer_opacity.insert(idx, self.layer_opacity[index])
        self.layer_locked.insert(idx, False)
        src_type = self.layer_types[index] if index < len(self.layer_types) else LAYER_TYPE_SLICE
        src_oid = self.layer_object_ids[index] if index < len(self.layer_object_ids) else None
        self.layer_types.insert(idx, src_type)
        self.layer_object_ids.insert(idx, src_oid)
        for fi, frame in enumerate(self.frames):
            if fi != self.current_frame:
                frame.insert(idx, frame[index].copy() if index < len(frame) else self._blank_layer())
        self.active_layer = idx
        self.sync_scene_metadata()
        self.update()
        return idx

    def remove_layer(self, index=None):
        if index is None:
            index = self.active_layer
        if len(self.layers) <= 1:
            return False
        if not (0 <= index < len(self.layers)):
            return False
        self.layers.pop(index)
        self.layer_names.pop(index)
        self.layer_visible.pop(index)
        self.layer_opacity.pop(index)
        self.layer_locked.pop(index)
        if index < len(self.layer_types):
            self.layer_types.pop(index)
        if index < len(self.layer_object_ids):
            self.layer_object_ids.pop(index)
        for fi, frame in enumerate(self.frames):
            if fi != self.current_frame and index < len(frame):
                frame.pop(index)
        self.active_layer = min(self.active_layer, len(self.layers) - 1)
        self.sync_scene_metadata()
        self.update()
        return True

    def move_layer(self, from_idx, to_idx):
        """Move layer and update ordering in all frames."""
        n = len(self.layers)
        if not (0 <= from_idx < n and 0 <= to_idx < n):
            return
        for lst in [self.layers, self.layer_names, self.layer_visible,
                    self.layer_opacity, self.layer_locked]:
            item = lst.pop(from_idx)
            lst.insert(to_idx, item)
        for lst in [self.layer_types, self.layer_object_ids]:
            if len(lst) >= n:
                item = lst.pop(from_idx)
                lst.insert(to_idx, item)
        for fi, frame in enumerate(self.frames):
            if fi != self.current_frame and len(frame) > max(from_idx, to_idx):
                item = frame.pop(from_idx)
                frame.insert(to_idx, item)
        if self.active_layer == from_idx:
            self.active_layer = to_idx
        self.sync_scene_metadata()
        self.update()

    def merge_down(self, index=None):
        if index is None:
            index = self.active_layer
        if index <= 0 or index >= len(self.layers):
            return False
        below = index - 1
        p = QPainter(self.layers[below])
        p.setOpacity(self.layer_opacity[index] / 255.0)
        p.drawImage(0, 0, self.layers[index])
        p.end()
        self.remove_layer(index)
        self.active_layer = below
        self.update()
        return True

    def flatten_image(self):
        result = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        result.fill(Qt.transparent)
        p = QPainter(result)
        for i, layer in enumerate(self.layers):
            if i < len(self.layer_visible) and self.layer_visible[i]:
                p.setOpacity(self.layer_opacity[i] / 255.0)
                p.drawImage(0, 0, layer)
        p.end()
        return result

    def _non_transparent_bounds(self, layer_indices):
        """Return (min_x, min_y, max_x, max_y) over non-transparent pixels."""
        min_x = self.canvas_width
        min_y = self.canvas_height
        max_x = -1
        max_y = -1
        for li in layer_indices:
            if not (0 <= li < len(self.layers)):
                continue
            layer = self.layers[li]
            for y in range(self.canvas_height):
                for x in range(self.canvas_width):
                    if layer.pixelColor(x, y).alpha() > 0:
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
        if max_x < min_x or max_y < min_y:
            return None
        return min_x, min_y, max_x, max_y

    def _shift_layers(self, layer_indices, dx, dy):
        """Shift selected layers by (dx, dy)."""
        if dx == 0 and dy == 0:
            return
        for li in layer_indices:
            if not (0 <= li < len(self.layers)):
                continue
            src = self.layers[li]
            out = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
            out.fill(Qt.transparent)
            qp = QPainter(out)
            qp.drawImage(dx, dy, src)
            qp.end()
            self.layers[li] = out

    def center_stack_content(self):
        """Center all visible layers as one stacked object."""
        layer_indices = [i for i, vis in enumerate(self.layer_visible) if vis]
        if not layer_indices:
            return
        bounds = self._non_transparent_bounds(layer_indices)
        if not bounds:
            return

        min_x, min_y, max_x, max_y = bounds
        content_w = max_x - min_x + 1
        content_h = max_y - min_y + 1
        target_x = (self.canvas_width - content_w) // 2
        target_y = (self.canvas_height - content_h) // 2
        dx = target_x - min_x
        dy = target_y - min_y
        if dx == 0 and dy == 0:
            return

        self.save_undo_state()
        self._shift_layers(layer_indices, dx, dy)
        self.save_current_frame()
        self.update()
        self.canvas_modified.emit()

    def center_layer_content(self, layer_idx=None):
        """Center only one layer (legacy helper)."""
        if layer_idx is None:
            layer_idx = self.active_layer
        if not (0 <= layer_idx < len(self.layers)):
            return
        if self.layer_locked[layer_idx]:
            return

        bounds = self._non_transparent_bounds([layer_idx])
        if not bounds:
            return
        min_x, min_y, max_x, max_y = bounds
        content_w = max_x - min_x + 1
        content_h = max_y - min_y + 1
        target_x = (self.canvas_width - content_w) // 2
        target_y = (self.canvas_height - content_h) // 2
        dx = target_x - min_x
        dy = target_y - min_y
        if dx == 0 and dy == 0:
            return

        self.save_undo_state()
        self._shift_layers([layer_idx], dx, dy)
        self.save_current_frame()
        self.update()
        self.canvas_modified.emit()

    # ──────────────────────────────────────────────────────────────────────────
    # Undo / Redo
    # ──────────────────────────────────────────────────────────────────────────

    def _make_undo_state(self):
        return {
            'layers' : self._copy_layers(),
            'active' : self.active_layer,
            'names'  : list(self.layer_names),
            'visible': list(self.layer_visible),
            'opacity': list(self.layer_opacity),
            'locked' : list(self.layer_locked),
            'types'  : list(self.layer_types),
            'obj_ids': list(self.layer_object_ids),
            'objects': [dict(o) for o in self.object_layers],
        }

    def save_undo_state(self):
        self.undo_stack.push(self._make_undo_state())

    def reset_undo(self):
        """Clear the undo/redo history (e.g. after loading a new project)."""
        self.undo_stack.clear()

    def undo(self):
        state = self.undo_stack.undo(self._make_undo_state())
        if state:
            self._apply_state(state)

    def redo(self):
        state = self.undo_stack.redo(self._make_undo_state())
        if state:
            self._apply_state(state)

    def _apply_state(self, state):
        self.layers       = [l.copy() for l in state['layers']]
        self.active_layer = state['active']
        self.layer_names  = list(state['names'])
        self.layer_visible= list(state['visible'])
        self.layer_opacity= list(state['opacity'])
        self.layer_locked = list(state['locked'])
        self.layer_types  = list(state.get('types', []))
        self.layer_object_ids = list(state.get('obj_ids', []))
        self.object_layers = [dict(o) for o in state.get('objects', [])]
        # Keep frame storage in sync with restored layers
        if 0 <= self.current_frame < len(self.frames):
            self.frames[self.current_frame] = self._copy_layers()
        self.sync_scene_metadata()
        self._checker_cache = None
        self.update()
        self.canvas_modified.emit()

    # ──────────────────────────────────────────────────────────────────────────
    # Coordinate helpers
    # ──────────────────────────────────────────────────────────────────────────

    def screen_to_image(self, sx, sy):
        return int((sx - self.offset_x) / self.zoom), int((sy - self.offset_y) / self.zoom)

    def image_to_screen(self, ix, iy):
        return ix * self.zoom + self.offset_x, iy * self.zoom + self.offset_y

    def is_in_bounds(self, x, y):
        return 0 <= x < self.canvas_width and 0 <= y < self.canvas_height

    # ──────────────────────────────────────────────────────────────────────────
    # Symmetry helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _symmetry_enabled(self):
        return (
            bool(getattr(self, "mirror_x", False))
            or bool(getattr(self, "mirror_y", False))
            or int(getattr(self, "symmetry_axis_count", 1) or 1) > 1
        )

    def _symmetry_points(self, x, y):
        """Return unique coordinates generated by the active symmetry settings."""
        try:
            axis_count = max(1, int(getattr(self, "symmetry_axis_count", 1) or 1))
        except (TypeError, ValueError):
            axis_count = 1

        cx = float(getattr(self, "symmetry_axis_x", self.canvas_width // 2))
        cy = float(getattr(self, "symmetry_axis_y", self.canvas_height // 2))
        points = [(int(round(x)), int(round(y)))]

        if bool(getattr(self, "symmetry_inverse", False)) and axis_count > 1:
            dx = x - cx
            dy = y - cy
            points = []
            for i in range(axis_count):
                a = (math.tau * i) / axis_count
                ca = math.cos(a)
                sa = math.sin(a)
                points.append((
                    int(round(cx + dx * ca - dy * sa)),
                    int(round(cy + dx * sa + dy * ca)),
                ))
        else:
            if getattr(self, "mirror_x", False):
                points.append((int(round(2 * cx - x)), int(round(y))))
            if getattr(self, "mirror_y", False):
                points.append((int(round(x)), int(round(2 * cy - y))))
            if getattr(self, "mirror_x", False) and getattr(self, "mirror_y", False):
                points.append((int(round(2 * cx - x)), int(round(2 * cy - y))))
            if axis_count > 1:
                dx = x - cx
                dy = y - cy
                for i in range(axis_count):
                    angle = (math.pi / 2.0) + (math.pi * i / axis_count)
                    ca = math.cos(2 * angle)
                    sa = math.sin(2 * angle)
                    points.append((
                        int(round(cx + dx * ca + dy * sa)),
                        int(round(cy + dx * sa - dy * ca)),
                    ))

        seen = set()
        unique = []
        for px, py in points:
            if (px, py) not in seen:
                seen.add((px, py))
                unique.append((px, py))
        return unique

    def _symmetry_point_pairs(self, x0, y0, x1, y1):
        starts = self._symmetry_points(x0, y0)
        ends = self._symmetry_points(x1, y1)
        return list(zip(starts, ends))

    # ──────────────────────────────────────────────────────────────────────────
    # Pixel access
    # ──────────────────────────────────────────────────────────────────────────

    def set_pixel(self, x, y, color, layer_idx=None):
        if layer_idx is None:
            layer_idx = self.active_layer
        if not self.is_in_bounds(x, y):
            return
        if self.layer_locked[layer_idx]:
            return
        self.layers[layer_idx].setPixelColor(x, y, color)

    def get_pixel(self, x, y, layer_idx=None):
        if layer_idx is None:
            layer_idx = self.active_layer
        if not self.is_in_bounds(x, y):
            return QColor(0, 0, 0, 0)
        return self.layers[layer_idx].pixelColor(x, y)

    def get_composite_pixel(self, x, y):
        """Return the composited (flattened) colour at canvas position (x,y)."""
        if not self.is_in_bounds(x, y):
            return QColor(0, 0, 0, 0)
        r, g, b, a = 0, 0, 0, 0
        for i, layer in enumerate(self.layers):
            if i >= len(self.layer_visible) or not self.layer_visible[i]:
                continue
            c   = layer.pixelColor(x, y)
            op  = (self.layer_opacity[i] / 255.0) * (c.alpha() / 255.0)
            r  += c.red()   * op
            g  += c.green() * op
            b  += c.blue()  * op
            a  += op * 255
        return QColor(min(255, int(r)), min(255, int(g)),
                      min(255, int(b)), min(255, int(a)))

    def _set_pixel_blended(self, x, y, color, layer_idx=None):
        """Set pixel with alpha blending (for brush opacity / hardness)."""
        if layer_idx is None:
            layer_idx = self.active_layer
        if not self.is_in_bounds(x, y):
            return
        if self.layer_locked[layer_idx]:
            return
        ca = color.alpha()
        if ca >= 255:
            self.layers[layer_idx].setPixelColor(x, y, color)
            return
        if ca <= 0:
            return
        existing = self.layers[layer_idx].pixelColor(x, y)
        sa = ca / 255.0
        da = existing.alpha() / 255.0
        out_a = sa + da * (1.0 - sa)
        if out_a <= 0:
            self.layers[layer_idx].setPixelColor(x, y, QColor(0, 0, 0, 0))
            return
        r = int((color.red()   * sa + existing.red()   * da * (1 - sa)) / out_a)
        g = int((color.green() * sa + existing.green() * da * (1 - sa)) / out_a)
        b = int((color.blue()  * sa + existing.blue()  * da * (1 - sa)) / out_a)
        self.layers[layer_idx].setPixelColor(
            x, y, QColor(r, g, b, min(255, int(out_a * 255))))

    def _erase_pixel(self, x, y, strength=1.0, layer_idx=None):
        """Reduce pixel alpha by *strength* (0–1)."""
        if layer_idx is None:
            layer_idx = self.active_layer
        if not self.is_in_bounds(x, y):
            return
        if self.layer_locked[layer_idx]:
            return
        c = self.layers[layer_idx].pixelColor(x, y)
        new_alpha = max(0, int(c.alpha() * (1.0 - strength)))
        self.layers[layer_idx].setPixelColor(
            x, y, QColor(c.red(), c.green(), c.blue(), new_alpha))

    def erase_pixel_brush(self, cx, cy, size=None):
        """Erase pixels under the brush respecting opacity and hardness."""
        if size is None:
            size = self.brush_size
        opacity_factor = self.brush_opacity / 100.0
        half = max(1, size // 2)
        for dx, dy in self._brush_offsets(size):
            if size > 1 and self.brush_hardness < 100:
                dist = math.sqrt(dx * dx + dy * dy)
                h = self.brush_hardness / 100.0
                falloff = 1.0 - (1.0 - h) * min(1.0, dist / half) if dist > 0 else 1.0
            else:
                falloff = 1.0
            strength = opacity_factor * falloff
            if strength <= 0:
                continue
            px, py = cx + dx, cy + dy
            for spx, spy in self._symmetry_points(px, py):
                self._erase_pixel(spx, spy, strength)

    # ──────────────────────────────────────────────────────────────────────────
    # Brush primitives
    # ──────────────────────────────────────────────────────────────────────────

    def _brush_offsets(self, size):
        half    = size // 2
        offsets = []
        for dy in range(-half, half + (1 if size % 2 else 0)):
            for dx in range(-half, half + (1 if size % 2 else 0)):
                if self.brush_shape == "circle" and dx * dx + dy * dy > half * half:
                    continue
                if self.brush_shape == "diamond" and abs(dx) + abs(dy) > half:
                    continue
                offsets.append((dx, dy))
        return offsets

    def draw_pixel_brush(self, cx, cy, color, size=None):
        if size is None:
            size = self.brush_size
        opacity_factor = self.brush_opacity / 100.0
        half = max(1, size // 2)
        for dx, dy in self._brush_offsets(size):
            # Hardness fall-off
            if size > 1 and self.brush_hardness < 100:
                dist = math.sqrt(dx * dx + dy * dy)
                h = self.brush_hardness / 100.0
                falloff = 1.0 - (1.0 - h) * min(1.0, dist / half) if dist > 0 else 1.0
            else:
                falloff = 1.0
            pixel_alpha = int(color.alpha() * opacity_factor * falloff)
            if pixel_alpha <= 0:
                continue
            draw_color = QColor(color.red(), color.green(), color.blue(), pixel_alpha)
            px, py = cx + dx, cy + dy
            for spx, spy in self._symmetry_points(px, py):
                self._set_pixel_blended(spx, spy, draw_color)

    def _draw_brush_on_image(self, image, cx, cy, color, size, apply_symmetry=True):
        half = size // 2
        for dy in range(-half, half + (1 if size % 2 else 0)):
            for dx in range(-half, half + (1 if size % 2 else 0)):
                if self.brush_shape == "circle" and dx * dx + dy * dy > half * half:
                    continue
                if self.brush_shape == "diamond" and abs(dx) + abs(dy) > half:
                    continue
                px, py = cx + dx, cy + dy
                points = self._symmetry_points(px, py) if apply_symmetry else [(px, py)]
                for spx, spy in points:
                    if 0 <= spx < image.width() and 0 <= spy < image.height():
                        image.setPixelColor(spx, spy, color)

    def draw_line(self, x0, y0, x1, y1, color, size=None, target_image=None, apply_symmetry=True):
        """Bresenham line with brush stamps."""
        if apply_symmetry and self._symmetry_enabled():
            for (sx, sy), (ex, ey) in self._symmetry_point_pairs(x0, y0, x1, y1):
                self.draw_line(sx, sy, ex, ey, color, size=size,
                               target_image=target_image, apply_symmetry=False)
            return
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        while True:
            if target_image is not None:
                self._draw_brush_on_image(
                    target_image, x0, y0, color, size or self.brush_size,
                    apply_symmetry=False,
                )
            elif apply_symmetry:
                self.draw_pixel_brush(x0, y0, color, size)
            else:
                brush_size = size or self.brush_size
                opacity_factor = self.brush_opacity / 100.0
                half = max(1, brush_size // 2)
                for ox, oy in self._brush_offsets(brush_size):
                    if brush_size > 1 and self.brush_hardness < 100:
                        dist = math.sqrt(ox * ox + oy * oy)
                        h = self.brush_hardness / 100.0
                        falloff = 1.0 - (1.0 - h) * min(1.0, dist / half) if dist > 0 else 1.0
                    else:
                        falloff = 1.0
                    pixel_alpha = int(color.alpha() * opacity_factor * falloff)
                    if pixel_alpha <= 0:
                        continue
                    draw_color = QColor(color.red(), color.green(), color.blue(), pixel_alpha)
                    self._set_pixel_blended(x0 + ox, y0 + oy, draw_color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy; x0 += sx
            if e2 < dx:
                err += dx; y0 += sy

    def draw_rect_outline(self, x0, y0, x1, y1, color, target_image=None):
        for args in [(x0, y0, x1, y0), (x1, y0, x1, y1),
                     (x1, y1, x0, y1), (x0, y1, x0, y0)]:
            self.draw_line(*args, color, target_image=target_image)

    def draw_rect_filled(self, x0, y0, x1, y1, color, target_image=None):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                for px, py in self._symmetry_points(x, y):
                    if target_image is not None:
                        if 0 <= px < target_image.width() and 0 <= py < target_image.height():
                            target_image.setPixelColor(px, py, color)
                    else:
                        self.set_pixel(px, py, color)

    def draw_circle_outline(self, cx, cy, rx, ry, color, target_image=None):
        if rx <= 0 or ry <= 0:
            return
        rx2, ry2 = rx * rx, ry * ry
        points    = set()
        x, y = 0, ry
        d = ry2 - rx2 * ry + 0.25 * rx2
        while ry2 * x <= rx2 * y:
            points.update([(cx+x,cy+y),(cx-x,cy+y),(cx+x,cy-y),(cx-x,cy-y)])
            x += 1
            d += ry2 * (2*x+1) if d < 0 else ry2*(2*x+1) - rx2*(2*y); y -= (0 if d < 0 else 1)
        d = ry2*(x+0.5)**2 + rx2*(y-1)**2 - rx2*ry2
        while y >= 0:
            points.update([(cx+x,cy+y),(cx-x,cy+y),(cx+x,cy-y),(cx-x,cy-y)])
            y -= 1
            if d > 0: d -= rx2*(2*y+1)
            else:     x += 1; d += ry2*(2*x) - rx2*(2*y+1)
        for px, py in points:
            for spx, spy in self._symmetry_points(px, py):
                if target_image is not None:
                    if 0 <= spx < target_image.width() and 0 <= spy < target_image.height():
                        target_image.setPixelColor(spx, spy, color)
                else:
                    self.set_pixel(spx, spy, color)

    def draw_circle_filled(self, cx, cy, rx, ry, color, target_image=None):
        if rx <= 0 or ry <= 0:
            return
        for y in range(-ry, ry + 1):
            for x in range(-rx, rx + 1):
                if (x*x)/(rx*rx) + (y*y)/(ry*ry) <= 1.0:
                    px, py = cx + x, cy + y
                    for spx, spy in self._symmetry_points(px, py):
                        if target_image is not None:
                            if 0 <= spx < target_image.width() and 0 <= spy < target_image.height():
                                target_image.setPixelColor(spx, spy, color)
                        else:
                            self.set_pixel(spx, spy, color)


    # -- Eraser line helper --

    def _erase_line(self, x0, y0, x1, y1):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        while True:
            self.erase_pixel_brush(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy; x0 += sx
            if e2 < dx:
                err += dx; y0 += sy

    # -- Blur brush --

    def _apply_blur_brush(self, cx, cy):
        layer = self.layers[self.active_layer]
        if self.layer_locked[self.active_layer]:
            return
        results = {}
        for base_x, base_y in self._symmetry_points(cx, cy):
            for dx, dy in self._brush_offsets(self.brush_size):
                px, py = base_x + dx, base_y + dy
                if not self.is_in_bounds(px, py):
                    continue
                r_sum, g_sum, b_sum, a_sum, count = 0, 0, 0, 0, 0
                for nx in range(max(0, px - 1), min(self.canvas_width, px + 2)):
                    for ny in range(max(0, py - 1), min(self.canvas_height, py + 2)):
                        c = layer.pixelColor(nx, ny)
                        r_sum += c.red(); g_sum += c.green()
                        b_sum += c.blue(); a_sum += c.alpha()
                        count += 1
                if count > 0:
                    results[(px, py)] = QColor(r_sum // count, g_sum // count,
                                               b_sum // count, a_sum // count)
        for (px, py), color in results.items():
            layer.setPixelColor(px, py, color)

    # -- Bezier curve --

    def _draw_bezier_curve(self):
        if len(self._curve_points) < 3:
            return
        p0, p1, p2 = self._curve_points[:3]
        seg = max(20, int(math.hypot(p2.x() - p0.x(), p2.y() - p0.y()) * 2))
        lx, ly = p0.x(), p0.y()
        for i in range(1, seg + 1):
            t = i / seg
            x = int((1 - t) ** 2 * p0.x() + 2 * (1 - t) * t * p1.x() + t ** 2 * p2.x())
            y = int((1 - t) ** 2 * p0.y() + 2 * (1 - t) * t * p1.y() + t ** 2 * p2.y())
            self.draw_line(lx, ly, x, y, self.primary_color)
            lx, ly = x, y

    # -- Contour (Aseprite-style freehand fill) --

    def _start_contour(self, x, y):
        self._contour_points = [QPoint(x, y)]

    def _extend_contour(self, x, y):
        if self._contour_points:
            last = self._contour_points[-1]
            if abs(x - last.x()) > 0 or abs(y - last.y()) > 0:
                self._contour_points.append(QPoint(x, y))
        self.update()

    def _finish_contour(self):
        if len(self._contour_points) < 3:
            self._contour_points = []
            return
        self.save_undo_state()
        pts = self._contour_points
        # Create a mask from the polygon
        mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        mask.fill(Qt.transparent)
        p = QPainter(mask)
        poly = QPolygon([QPoint(pt.x(), pt.y()) for pt in pts])
        p.setBrush(QColor(255, 255, 255, 255))
        p.setPen(Qt.NoPen)
        p.drawPolygon(poly)
        p.end()
        # Fill all pixels inside the polygon on the active layer
        color = self.primary_color
        layer = self.layers[self.active_layer]
        for y in range(self.canvas_height):
            for x in range(self.canvas_width):
                if mask.pixelColor(x, y).alpha() > 0:
                    for px, py in self._symmetry_points(x, y):
                        if self.is_in_bounds(px, py) and not self.layer_locked[self.active_layer]:
                            layer.setPixelColor(px, py, color)
        self._contour_points = []
        self.canvas_modified.emit()
        self.update()


    # ──────────────────────────────────────────────────────────────────────────
    # Flood fill  (iterative BFS — no recursion limit issues)
    # ──────────────────────────────────────────────────────────────────────────

    def flood_fill(self, x, y, fill_color, apply_symmetry=True):
        if not self.is_in_bounds(x, y):
            return
        if self.layer_locked[self.active_layer]:
            return
        if apply_symmetry and self._symmetry_enabled():
            for sx, sy in self._symmetry_points(x, y):
                self.flood_fill(sx, sy, fill_color, apply_symmetry=False)
            return
        layer        = self.layers[self.active_layer]
        target_rgba  = layer.pixel(x, y)
        if QColor(target_rgba) == fill_color:
            return
        has_sel_rect = self.selection_rect is not None
        has_sel_mask = self.selection_mask is not None
        queue   = collections.deque([(x, y)])
        visited = set()
        while queue:
            cx, cy = queue.popleft()
            if (cx, cy) in visited or not self.is_in_bounds(cx, cy):
                continue
            if has_sel_rect and not self.selection_rect.contains(cx, cy):
                continue
            if has_sel_mask and self.selection_mask.pixelColor(cx, cy).alpha() == 0:
                continue
            if layer.pixel(cx, cy) != target_rgba:
                continue
            visited.add((cx, cy))
            layer.setPixelColor(cx, cy, fill_color)
            queue.extend([(cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)])

    # ──────────────────────────────────────────────────────────────────────────
    # Gradient fill
    # ──────────────────────────────────────────────────────────────────────────

    def _gradient_bounds(self):
        if self.selection_rect:
            r = self.selection_rect
            left = max(0, r.x())
            top = max(0, r.y())
            right = min(self.canvas_width - 1, r.x() + r.width() - 1)
            bottom = min(self.canvas_height - 1, r.y() + r.height() - 1)
            return left, top, right, bottom
        return 0, 0, self.canvas_width - 1, self.canvas_height - 1

    def _resolve_gradient_line(self, sx, sy, ex, ey):
        mode = getattr(self, "gradient_mode", "free") or "free"
        if mode == "free":
            return sx, sy, ex, ey
        left, top, right, bottom = self._gradient_bounds()
        if mode == "horizontal":
            return left, top, right, top
        if mode == "vertical":
            return left, top, left, bottom
        if mode == "diagonal":
            return left, top, right, bottom
        return sx, sy, ex, ey

    def gradient_fill(self, x0, y0, x1, y1, color_a, color_b, target_image=None,
                      selection_rect=None, selection_mask=None, apply_symmetry=True):
        """
        Linear gradient from (x0,y0) to (x1,y1) over entire canvas
        (or target_image if provided).
        """
        img = target_image or self.layers[self.active_layer]
        if apply_symmetry and self._symmetry_enabled():
            source = QImage(img.width(), img.height(), QImage.Format_ARGB32)
            source.fill(Qt.transparent)
            self.gradient_fill(
                x0, y0, x1, y1, color_a, color_b,
                target_image=source,
                selection_rect=selection_rect,
                selection_mask=selection_mask,
                apply_symmetry=False,
            )
            sel_rect = selection_rect if selection_rect is not None else self.selection_rect
            sel_mask = selection_mask if selection_mask is not None else self.selection_mask
            if sel_rect:
                x_start = max(0, sel_rect.x())
                x_end = min(img.width(), sel_rect.x() + sel_rect.width())
                y_start = max(0, sel_rect.y())
                y_end = min(img.height(), sel_rect.y() + sel_rect.height())
            else:
                x_start, x_end, y_start, y_end = 0, img.width(), 0, img.height()
            for py in range(y_start, y_end):
                for px in range(x_start, x_end):
                    if sel_mask is not None and sel_mask.pixelColor(px, py).alpha() == 0:
                        continue
                    color = source.pixelColor(px, py)
                    for sx, sy in self._symmetry_points(px, py):
                        if 0 <= sx < img.width() and 0 <= sy < img.height():
                            img.setPixelColor(sx, sy, color)
            return
        w, h = img.width(), img.height()
        sel_rect = selection_rect if selection_rect is not None else self.selection_rect
        sel_mask = selection_mask if selection_mask is not None else self.selection_mask
        if sel_rect:
            x_start = max(0, sel_rect.x())
            x_end = min(w, sel_rect.x() + sel_rect.width())
            y_start = max(0, sel_rect.y())
            y_end = min(h, sel_rect.y() + sel_rect.height())
        else:
            x_start, x_end, y_start, y_end = 0, w, 0, h
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx*dx + dy*dy
        if length_sq == 0:
            return
        for py in range(y_start, y_end):
            for px in range(x_start, x_end):
                if sel_mask is not None and sel_mask.pixelColor(px, py).alpha() == 0:
                    continue
                t = ((px - x0)*dx + (py - y0)*dy) / length_sq
                t = max(0.0, min(1.0, t))
                r = int(color_a.red()   + t * (color_b.red()   - color_a.red()))
                g = int(color_a.green() + t * (color_b.green() - color_a.green()))
                b = int(color_a.blue()  + t * (color_b.blue()  - color_a.blue()))
                a = int(color_a.alpha() + t * (color_b.alpha() - color_a.alpha()))
                img.setPixelColor(px, py, QColor(r, g, b, a))

    # ──────────────────────────────────────────────────────────────────────────
    # Magic wand  (fixed: tolerance now compares per-channel max, not sum/4)
    # ──────────────────────────────────────────────────────────────────────────

    def magic_wand_select(self, x, y, tolerance=10):
        if not self.is_in_bounds(x, y):
            return
        layer  = self.layers[self.active_layer]
        mask   = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        mask.fill(Qt.transparent)
        visited = set()
        seeds = self._symmetry_points(x, y) if self._symmetry_enabled() else [(x, y)]

        for seed_x, seed_y in seeds:
            if not self.is_in_bounds(seed_x, seed_y):
                continue
            target = layer.pixelColor(seed_x, seed_y)
            queue = collections.deque([(seed_x, seed_y)])
            while queue:
                cx, cy = queue.popleft()
                if (cx, cy) in visited or not self.is_in_bounds(cx, cy):
                    continue
                pc = layer.pixelColor(cx, cy)
                if max(abs(pc.red()   - target.red()),
                       abs(pc.green() - target.green()),
                       abs(pc.blue()  - target.blue()),
                       abs(pc.alpha() - target.alpha())) > tolerance:
                    continue
                visited.add((cx, cy))
                mask.setPixelColor(cx, cy, QColor(0, 120, 255, 100))
                queue.extend([(cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)])
        if visited:
            xs = [p[0] for p in visited]; ys = [p[1] for p in visited]
            self.selection_rect = QRect(min(xs), min(ys),
                                        max(xs)-min(xs)+1, max(ys)-min(ys)+1)
        if self.selection_mode != "replace" and hasattr(self, '_prev_sel_mask') and self._prev_sel_mask is not None:
            self._combine_selection_masks(mask)
        else:
            self.selection_mask = mask
        self.show_context_bar()
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Lasso (freehand) selection
    # ──────────────────────────────────────────────────────────────────────────

    def _start_lasso(self, x, y):
        self._lasso_points = [QPoint(x, y)]

    def _extend_lasso(self, x, y):
        if self._lasso_points:
            last = self._lasso_points[-1]
            if abs(x - last.x()) > 0 or abs(y - last.y()) > 0:
                self._lasso_points.append(QPoint(x, y))
        self.update()

    def _finish_lasso(self):
        if len(self._lasso_points) < 3:
            self._lasso_points = []
            return
        pts = self._lasso_points
        mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        mask.fill(Qt.transparent)
        p = QPainter(mask)
        poly = QPolygon([QPoint(pt.x(), pt.y()) for pt in pts])
        p.setBrush(QColor(0, 120, 255, 100))
        p.setPen(Qt.NoPen)
        p.drawPolygon(poly)
        p.end()
        # Bounding rect
        xs = [pt.x() for pt in pts]; ys = [pt.y() for pt in pts]
        self.selection_rect = QRect(min(xs), min(ys),
                                    max(xs)-min(xs)+1, max(ys)-min(ys)+1)
        if self.selection_mode != "replace" and hasattr(self, '_prev_sel_mask') and self._prev_sel_mask is not None:
            self._combine_selection_masks(mask)
        else:
            self.selection_mask = mask
        self._lasso_points  = []
        self.show_context_bar()
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Copy / Cut / Paste
    # ──────────────────────────────────────────────────────────────────────────

    def copy_selection(self):
        if not self.selection_rect:
            return
        r     = self.selection_rect
        clip  = QImage(r.width(), r.height(), QImage.Format_ARGB32)
        clip.fill(Qt.transparent)
        layer = self.layers[self.active_layer]
        if self.selection_mask is not None:
            for py in range(r.height()):
                for px in range(r.width()):
                    sx, sy = r.x() + px, r.y() + py
                    if self.is_in_bounds(sx, sy):
                        mc = self.selection_mask.pixelColor(sx, sy)
                        if mc.alpha() > 0:
                            clip.setPixelColor(px, py, layer.pixelColor(sx, sy))
        else:
            p = QPainter(clip)
            p.drawImage(0, 0, layer, r.x(), r.y(), r.width(), r.height())
            p.end()
        self.clipboard_image  = clip
        self.clipboard_offset = (r.x(), r.y())

    def cut_selection(self):
        self.copy_selection()
        if not self.selection_rect:
            return
        self.save_undo_state()
        r = self.selection_rect
        layer = self.layers[self.active_layer]
        if self.selection_mask is not None:
            for y in range(r.y(), r.y() + r.height()):
                for x in range(r.x(), r.x() + r.width()):
                    if self.is_in_bounds(x, y):
                        mc = self.selection_mask.pixelColor(x, y)
                        if mc.alpha() > 0:
                            layer.setPixelColor(x, y, QColor(0, 0, 0, 0))
        else:
            for y in range(r.y(), r.y() + r.height()):
                for x in range(r.x(), r.x() + r.width()):
                    if self.is_in_bounds(x, y):
                        layer.setPixelColor(x, y, QColor(0, 0, 0, 0))
        self.update()
        self.canvas_modified.emit()

    def paste_clipboard(self):
        if self.clipboard_image is None:
            return
        self._floating_image  = self.clipboard_image.copy()
        self._floating_offset = self.clipboard_offset
        self._floating_active = True
        self.update()

    def commit_floating(self):
        if not self._floating_active or self._floating_image is None:
            return
        self.save_undo_state()
        p = QPainter(self.layers[self.active_layer])
        p.drawImage(self._floating_offset[0], self._floating_offset[1],
                    self._floating_image)
        p.end()
        self._floating_active = False
        self._floating_image  = None
        self.update()
        self.canvas_modified.emit()

    def delete_selection(self):
        """Clear pixels within the current selection (rect and/or mask)."""
        if not self.selection_rect and not self.selection_mask:
            return
        self.save_undo_state()
        layer = self.layers[self.active_layer]
        if self.selection_mask is not None:
            w, h = self.selection_mask.width(), self.selection_mask.height()
            for py in range(h):
                for px in range(w):
                    if self.selection_mask.pixelColor(px, py).alpha() > 0:
                        if self.is_in_bounds(px, py):
                            layer.setPixelColor(px, py, QColor(0, 0, 0, 0))
        elif self.selection_rect:
            r = self.selection_rect
            for py in range(r.y(), r.y() + r.height()):
                for px in range(r.x(), r.x() + r.width()):
                    if self.is_in_bounds(px, py):
                        layer.setPixelColor(px, py, QColor(0, 0, 0, 0))
        self.selection_rect = None
        self.selection_mask = None
        self.hide_context_bar()
        self.update()
        self.canvas_modified.emit()

    def select_all(self):
        self.selection_rect = QRect(0, 0, self.canvas_width, self.canvas_height)
        self.show_context_bar()
        self.update()

    def _apply_selection_mode_rect(self):
        """Combine new rectangular selection with existing based on selection_mode."""
        if self.selection_mode == "replace" or not hasattr(self, '_prev_sel_mask'):
            return  # replace = just use the new rect as-is
        new_mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        new_mask.fill(Qt.transparent)
        r = self.selection_rect
        sel_color = QColor(0, 120, 255, 100)
        for py in range(r.y(), r.y() + r.height()):
            for px in range(r.x(), r.x() + r.width()):
                if self.is_in_bounds(px, py):
                    new_mask.setPixelColor(px, py, sel_color)
        self._combine_selection_masks(new_mask)

    def _combine_selection_masks(self, new_mask):
        """Combine new_mask with _prev_sel_mask based on selection_mode."""
        if not hasattr(self, '_prev_sel_mask') or self._prev_sel_mask is None:
            self.selection_mask = new_mask
        elif self.selection_mode == "add":
            combined = self._prev_sel_mask.copy()
            for py in range(self.canvas_height):
                for px in range(self.canvas_width):
                    if new_mask.pixelColor(px, py).alpha() > 0:
                        combined.setPixelColor(px, py, QColor(0, 120, 255, 100))
            self.selection_mask = combined
        elif self.selection_mode == "subtract":
            combined = self._prev_sel_mask.copy()
            for py in range(self.canvas_height):
                for px in range(self.canvas_width):
                    if new_mask.pixelColor(px, py).alpha() > 0:
                        combined.setPixelColor(px, py, QColor(0, 0, 0, 0))
            self.selection_mask = combined
        elif self.selection_mode == "intersect":
            combined = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
            combined.fill(Qt.transparent)
            for py in range(self.canvas_height):
                for px in range(self.canvas_width):
                    if (new_mask.pixelColor(px, py).alpha() > 0 and
                            self._prev_sel_mask.pixelColor(px, py).alpha() > 0):
                        combined.setPixelColor(px, py, QColor(0, 120, 255, 100))
            self.selection_mask = combined
        else:
            self.selection_mask = new_mask
        # Update bounding rect from mask
        if self.selection_mask is not None:
            min_x, min_y = self.canvas_width, self.canvas_height
            max_x, max_y = 0, 0
            found = False
            for py in range(self.canvas_height):
                for px in range(self.canvas_width):
                    if self.selection_mask.pixelColor(px, py).alpha() > 0:
                        min_x = min(min_x, px); min_y = min(min_y, py)
                        max_x = max(max_x, px); max_y = max(max_y, py)
                        found = True
            if found:
                self.selection_rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            else:
                self.selection_rect = None
                self.selection_mask = None
        self._prev_sel_mask = None

    def deselect(self):
        if self._floating_active:
            self.commit_floating()
        self.selection_rect  = None
        self.selection_mask  = None
        self._lasso_points   = []
        self._contour_points = []
        self.hide_context_bar()
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Image adjustments (numpy-powered)
    # ──────────────────────────────────────────────────────────────────────────

    def _layer_to_numpy(self, layer_idx=None):
        """Return active layer as float32 RGBA numpy array (H,W,4), values 0–1."""
        if layer_idx is None:
            layer_idx = self.active_layer
        img   = self.layers[layer_idx].convertToFormat(QImage.Format_RGBA8888)
        ptr   = img.bits(); ptr.setsize(img.byteCount())
        arr   = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.width(), 4).copy()
        return arr.astype(np.float32) / 255.0, img

    def _numpy_to_layer(self, arr, layer_idx=None):
        """Write float32 RGBA numpy array back to layer."""
        if layer_idx is None:
            layer_idx = self.active_layer
        clamped = np.clip(arr * 255, 0, 255).astype(np.uint8)
        h, w    = clamped.shape[:2]
        img     = QImage(clamped.tobytes(), w, h, w * 4, QImage.Format_RGBA8888)
        self.layers[layer_idx] = img.convertToFormat(QImage.Format_ARGB32)

    def adjust_brightness_contrast(self, brightness=0.0, contrast=1.0, layer_idx=None):
        """
        Adjust brightness (−1...+1) and contrast (0...2) on the active layer (or rect).
        Preserves alpha.
        """
        self.save_undo_state()
        arr, _ = self._layer_to_numpy(layer_idx)
        rgb     = arr[:, :, :3]
        alpha   = arr[:, :, 3:4]
        rgb     = (rgb - 0.5) * contrast + 0.5 + brightness
        result  = np.concatenate([rgb, alpha], axis=2)
        self._numpy_to_layer(result, layer_idx)
        self.update()
        self.canvas_modified.emit()

    def adjust_hue_shift(self, degrees, layer_idx=None):
        """Rotate hue by `degrees` (0–360) using numpy HSV conversion."""
        self.save_undo_state()
        arr, _ = self._layer_to_numpy(layer_idx)
        rgb     = arr[:, :, :3]
        alpha   = arr[:, :, 3:4]
        # Manual HSV hue-shift
        max_c   = rgb.max(axis=2, keepdims=True)
        min_c   = rgb.min(axis=2, keepdims=True)
        delta   = max_c - min_c
        # Avoid division by zero
        safe_delta = np.where(delta == 0, 1, delta)
        safe_max   = np.where(max_c  == 0, 1, max_c)
        r, g, b    = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
        hue        = np.where(max_c[:,:,0] == r, (g - b) / safe_delta[:,:,0] % 6,
                     np.where(max_c[:,:,0] == g, (b - r) / safe_delta[:,:,0] + 2,
                                                  (r - g) / safe_delta[:,:,0] + 4))
        hue        = (hue * 60 + degrees) % 360
        s          = np.where(max_c[:,:,0] == 0, 0, delta[:,:,0] / safe_max[:,:,0])
        v          = max_c[:,:,0]
        # HSV → RGB
        hi         = (hue / 60).astype(int) % 6
        f          = hue / 60 - np.floor(hue / 60)
        p          = v * (1 - s); q = v * (1 - f * s); t = v * (1 - (1 - f) * s)
        new_r = np.select([hi==0,hi==1,hi==2,hi==3,hi==4,hi==5], [v,q,p,p,t,v])
        new_g = np.select([hi==0,hi==1,hi==2,hi==3,hi==4,hi==5], [t,v,v,q,p,p])
        new_b = np.select([hi==0,hi==1,hi==2,hi==3,hi==4,hi==5], [p,p,t,v,v,q])
        result = np.stack([new_r, new_g, new_b], axis=2)
        result = np.concatenate([result, alpha], axis=2)
        # Keep greyscale pixels unchanged
        result[delta[:,:,0] == 0] = arr[delta[:,:,0] == 0]
        self._numpy_to_layer(result, layer_idx)
        self.update()
        self.canvas_modified.emit()

    # ──────────────────────────────────────────────────────────────────────────
    # Selection manipulation
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_selection_image(self):
        if not self.selection_rect:
            return None
        r    = self.selection_rect
        clip = QImage(r.width(), r.height(), QImage.Format_ARGB32)
        clip.fill(Qt.transparent)
        p    = QPainter(clip)
        p.drawImage(0, 0, self.layers[self.active_layer],
                    r.x(), r.y(), r.width(), r.height())
        p.end()
        return clip

    def _clear_selection_area(self):
        r     = self.selection_rect
        layer = self.layers[self.active_layer]
        p     = QPainter(layer)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(r, Qt.transparent)
        p.end()

    def _stamp_image_at(self, image, x, y):
        p = QPainter(self.layers[self.active_layer])
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(x, y, image)
        p.end()

    def center_selection_on_pivot(self):
        if not self.selection_rect:
            return
        self.save_undo_state()
        r    = self.selection_rect
        clip = self._extract_selection_image()
        if clip is None:
            return
        self._clear_selection_area()
        cx = self.pivot[0] - r.width()  // 2
        cy = self.pivot[1] - r.height() // 2
        self._stamp_image_at(clip, cx, cy)
        self.selection_rect = QRect(cx, cy, r.width(), r.height())
        self.update(); self.show_context_bar(); self.canvas_modified.emit()

    def flip_selection(self, horizontal=True):
        if not self.selection_rect:
            return
        self.save_undo_state()
        clip = self._extract_selection_image()
        if clip is None:
            return
        flipped = clip.mirrored(horizontal, not horizontal)
        r = self.selection_rect
        self._clear_selection_area()
        self._stamp_image_at(flipped, r.x(), r.y())
        self.update(); self.show_context_bar(); self.canvas_modified.emit()

    def rotate_selection(self, clockwise=True):
        if not self.selection_rect:
            return
        self.save_undo_state()
        clip = self._extract_selection_image()
        if clip is None:
            return
        transform = QTransform()
        transform.rotate(90 if clockwise else -90)
        rotated = clip.transformed(transform, Qt.FastTransformation)
        r  = self.selection_rect
        self._clear_selection_area()
        cx = r.x() + r.width()  // 2 - rotated.width()  // 2
        cy = r.y() + r.height() // 2 - rotated.height() // 2
        self._stamp_image_at(rotated, cx, cy)
        self.selection_rect = QRect(cx, cy, rotated.width(), rotated.height())
        self.update(); self.show_context_bar(); self.canvas_modified.emit()

    def scale_selection(self, scale_pct):
        if not self.selection_rect or scale_pct <= 0:
            return
        self.save_undo_state()
        clip  = self._extract_selection_image()
        if clip is None:
            return
        new_w = max(1, int(clip.width()  * scale_pct / 100))
        new_h = max(1, int(clip.height() * scale_pct / 100))
        scaled = clip.scaled(new_w, new_h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        r  = self.selection_rect
        self._clear_selection_area()
        cx = r.x() + r.width()  // 2 - new_w // 2
        cy = r.y() + r.height() // 2 - new_h // 2
        self._stamp_image_at(scaled, cx, cy)
        self.selection_rect = QRect(cx, cy, new_w, new_h)
        self.update(); self.show_context_bar(); self.canvas_modified.emit()

    def _lift_selection(self):
        """Lift current selection (rect or mask) into the floating layer."""
        if not self.selection_rect:
            return
        self.copy_selection()
        self.save_undo_state()
        r     = self.selection_rect
        layer = self.layers[self.active_layer]
        if self.selection_mask is not None:
            for py in range(r.y(), r.y() + r.height()):
                for px in range(r.x(), r.x() + r.width()):
                    if self.is_in_bounds(px, py):
                        mc = self.selection_mask.pixelColor(px, py)
                        if mc.alpha() > 0:
                            layer.setPixelColor(px, py, QColor(0, 0, 0, 0))
        else:
            for py in range(r.y(), r.y() + r.height()):
                for px in range(r.x(), r.x() + r.width()):
                    if self.is_in_bounds(px, py):
                        layer.setPixelColor(px, py, QColor(0, 0, 0, 0))
        self._floating_image  = self.clipboard_image.copy()
        self._floating_offset = (r.x(), r.y())
        self._floating_active = True
        self.selection_rect   = None
        self.selection_mask   = None
        self.update()

    def _ctx_move(self):
        self._lift_selection()
        self.hide_context_bar()
        self.setCursor(Qt.SizeAllCursor)

    def _show_scale_dialog(self):
        if not self.selection_rect:
            return
        dlg  = QDialog(self)
        dlg.setWindowTitle("Scale Selection")
        dlg.setStyleSheet(
            "QDialog { background: #1f1f2e; color: #c8c8d4; }"
            "QLabel  { color: #c8c8d4; font-family: 'Courier New'; font-size: 9pt; }"
            "QSpinBox { background: #171726; color: #c8c8d4; border: 1px solid #3a3a4a; "
            "           padding: 3px; }"
        )
        form = QFormLayout(dlg)
        spin = QSpinBox(); spin.setRange(10, 500); spin.setValue(100); spin.setSuffix("%")
        form.addRow("Scale:", spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec_() == QDialog.Accepted:
            self.scale_selection(spin.value())

    def show_context_bar(self):
        if not self.selection_rect:
            self.hide_context_bar(); return
        r   = self.selection_rect
        sx0, sy0 = self.image_to_screen(r.x(), r.y())
        sx1, sy1 = self.image_to_screen(r.x() + r.width(), r.y() + r.height())
        bw  = self._context_bar.sizeHint().width()
        bh  = self._context_bar.sizeHint().height()
        bx  = int((sx0 + sx1) / 2 - bw / 2)
        by  = int(sy0 - bh - 12)
        if by < 0:
            by = int(sy1 + 12)
        bx = max(10, min(bx, self.width()  - bw - 10))
        by = max(10, min(by, self.height() - bh - 10))
        self._context_bar.move(bx, by)
        self._context_bar.show()
        self._context_bar.raise_()

    def hide_context_bar(self):
        self._context_bar.hide()

    # ──────────────────────────────────────────────────────────────────────────
    # Frame management  (timeline integration)
    # ──────────────────────────────────────────────────────────────────────────

    def save_current_frame(self):
        if 0 <= self.current_frame < len(self.frames):
            self.frames[self.current_frame] = self._copy_layers()

    def load_frame(self, frame_idx):
        if 0 <= frame_idx < len(self.frames):
            self.save_current_frame()
            self.current_frame = frame_idx
            self._restore_layers(self.frames[frame_idx])
            self.update()
            self.frame_changed.emit(frame_idx, len(self.frames))

    def add_frame(self, copy_current=False):
        self.save_current_frame()
        n   = len(self.layers)
        new_frame = self._copy_layers() if copy_current else [self._blank_layer() for _ in range(n)]
        idx = self.current_frame + 1
        self.frames.insert(idx, new_frame)
        self.current_frame = idx
        self._restore_layers(self.frames[idx])
        self.update()
        self.frame_changed.emit(idx, len(self.frames))
        return idx

    def insert_frame_before(self, frame_idx):
        """Insert a blank frame before frame_idx."""
        self.save_current_frame()
        n         = len(self.layers)
        new_frame = [self._blank_layer() for _ in range(n)]
        self.frames.insert(frame_idx, new_frame)
        if self.current_frame >= frame_idx:
            self.current_frame += 1
        self._restore_layers(self.frames[self.current_frame])
        self.update()
        self.frame_changed.emit(self.current_frame, len(self.frames))

    def insert_frame_after(self, frame_idx):
        self.insert_frame_before(frame_idx + 1)

    def delete_frame(self, frame_idx=None):
        if frame_idx is None:
            frame_idx = self.current_frame
        if len(self.frames) <= 1:
            return False
        if not (0 <= frame_idx < len(self.frames)):
            return False
        old_current = self.current_frame
        if frame_idx != old_current:
            self.save_current_frame()
        self.frames.pop(frame_idx)
        if frame_idx < old_current:
            self.current_frame = old_current - 1
        elif frame_idx == old_current:
            self.current_frame = min(frame_idx, len(self.frames) - 1)
        else:
            self.current_frame = old_current
        self._restore_layers(self.frames[self.current_frame])
        self.update()
        self.frame_changed.emit(self.current_frame, len(self.frames))
        return True

    def clear_frame(self, frame_idx=None):
        """Clear all pixels on all layers of frame_idx (timeline 'clear frame')."""
        if frame_idx is None:
            frame_idx = self.current_frame
        if not (0 <= frame_idx < len(self.frames)):
            return
        self.frames[frame_idx] = [self._blank_layer() for _ in range(len(self.layers))]
        if frame_idx == self.current_frame:
            self._restore_layers(self.frames[frame_idx])
        self.update()
        self.canvas_modified.emit()

    def set_frame_flat_image(self, frame_idx: int, image: QImage, layer_idx: int | None = None) -> bool:
        """Set one frame layer from a flattened image (used for tween predictions)."""
        if not (0 <= frame_idx < len(self.frames)):
            return False
        if image is None or image.isNull():
            return False
        if layer_idx is None:
            layer_idx = self.active_layer
        if not (0 <= layer_idx < len(self.layers)):
            return False

        fitted = self._fit_image_to_canvas(image)
        frame = self.frames[frame_idx]
        if len(frame) != len(self.layers):
            frame = [self._blank_layer() for _ in range(len(self.layers))]
        else:
            frame = [l.copy() for l in frame]
        frame[layer_idx] = fitted
        self.frames[frame_idx] = frame

        if frame_idx == self.current_frame:
            self._restore_layers(frame)
            self.active_layer = layer_idx
        self.update()
        self.canvas_modified.emit()
        return True

    def move_frame(self, from_idx, to_idx):
        """Reorder frames (timeline drag-reorder)."""
        total = len(self.frames)
        if not (0 <= from_idx < total and 0 <= to_idx < total):
            return
        frame = self.frames.pop(from_idx)
        self.frames.insert(to_idx, frame)
        if self.current_frame == from_idx:
            self.current_frame = to_idx
        elif from_idx < self.current_frame <= to_idx:
            self.current_frame -= 1
        elif to_idx <= self.current_frame < from_idx:
            self.current_frame += 1
        self.frame_changed.emit(self.current_frame, total)

    def get_frame_count(self): return len(self.frames)

    def get_flat_frame(self, frame_idx):
        """Return composited QImage for frame_idx (used by timeline thumbnails)."""
        if not (0 <= frame_idx < len(self.frames)):
            return None
        result = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        result.fill(Qt.transparent)
        p      = QPainter(result)
        layers = self.frames[frame_idx]
        for i, layer in enumerate(layers):
            vis = self.layer_visible[i] if i < len(self.layer_visible) else True
            if not vis:
                continue
            op = (self.layer_opacity[i] / 255.0) if i < len(self.layer_opacity) else 1.0
            p.setOpacity(op)
            p.drawImage(0, 0, layer)
        p.setOpacity(1.0)
        p.end()
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Onion skinning  (timeline signal: onion_skin_changed(bool, int, int))
    # ──────────────────────────────────────────────────────────────────────────

    def set_onion_skin(self, enabled, frames=2, opacity=50):
        """Slot compatible with TimelinePanel.onion_skin_changed signal."""
        self.onion_skin_enabled = enabled
        self.onion_skin_frames  = max(1, frames)
        self.onion_skin_opacity = max(0, min(100, opacity))
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # View helpers
    # ──────────────────────────────────────────────────────────────────────────

    def center_canvas(self):
        cw = self.canvas_width  * self.zoom
        ch = self.canvas_height * self.zoom
        self.offset_x = (self.width()  - cw) / 2
        self.offset_y = (self.height() - ch) / 2
        self.update()

    def fit_canvas(self):
        zx = (self.width()  - 40) / self.canvas_width
        zy = (self.height() - 40) / self.canvas_height
        self.zoom = max(self.min_zoom, min(zx, zy))
        self.center_canvas()

    # ──────────────────────────────────────────────────────────────────────────
    # Paint
    # ──────────────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.fillRect(self.rect(), QColor(0x0B, 0x0C, 0x10))  # --void

        self._draw_checker(p)

        # Onion skins (previous frames, tinted red; future, tinted green)
        if self.onion_skin_enabled:
            opacity_step = (self.onion_skin_opacity / 100.0) / self.onion_skin_frames
            dest = QRect(int(self.offset_x), int(self.offset_y),
                         int(self.canvas_width * self.zoom),
                         int(self.canvas_height * self.zoom))
            for step in range(1, self.onion_skin_frames + 1):
                for fi, tint in [(self.current_frame - step, QColor(255, 80, 80, 80)),
                                 (self.current_frame + step, QColor(80, 255, 80, 80))]:
                    if not (0 <= fi < len(self.frames)):
                        continue
                    flat = self.get_flat_frame(fi)
                    if flat is None:
                        continue
                    alpha = opacity_step * (self.onion_skin_frames - step + 1)
                    p.setOpacity(alpha)
                    p.drawImage(dest, flat)
                    # Tint overlay
                    p.setOpacity(alpha * 0.3)
                    p.fillRect(dest, tint)
            p.setOpacity(1.0)

        # Active layers
        dest = QRect(int(self.offset_x), int(self.offset_y),
                     int(self.canvas_width * self.zoom),
                     int(self.canvas_height * self.zoom))
        for i, layer in enumerate(self.layers):
            if i < len(self.layer_visible) and not self.layer_visible[i]:
                continue
            op = (self.layer_opacity[i] / 255.0) if i < len(self.layer_opacity) else 1.0
            p.setOpacity(op)
            p.drawImage(dest, layer)
        p.setOpacity(1.0)

        # Floating paste
        if self._floating_active and self._floating_image is not None:
            fx, fy = self._floating_offset
            fdest  = QRect(int(self.offset_x + fx * self.zoom),
                           int(self.offset_y + fy * self.zoom),
                           int(self._floating_image.width()  * self.zoom),
                           int(self._floating_image.height() * self.zoom))
            p.setOpacity(0.85)
            p.drawImage(fdest, self._floating_image)
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(0x3D, 0xFF, 0xD0, 200), 1, Qt.DashLine))  # --cyan
            p.setBrush(Qt.NoBrush)
            p.drawRect(fdest)

        # Shape preview
        if self.preview_overlay is not None:
            p.drawImage(dest, self.preview_overlay)

        # Curve tool control points preview
        if self._curve_points and self.current_tool == "curve":
            p.setPen(QPen(QColor(0x3D, 0xFF, 0xD0, 220), 1, Qt.SolidLine))
            for pt in self._curve_points:
                sx_c, sy_c = self.image_to_screen(pt.x() + 0.5, pt.y() + 0.5)
                p.drawEllipse(int(sx_c) - 4, int(sy_c) - 4, 8, 8)
            if len(self._curve_points) == 2:
                # Preview straight line between first two points
                a, b = self._curve_points
                ax_s, ay_s = self.image_to_screen(a.x(), a.y())
                bx_s, by_s = self.image_to_screen(b.x(), b.y())
                p.setPen(QPen(QColor(0x3D, 0xFF, 0xD0, 100), 1, Qt.DashLine))
                p.drawLine(int(ax_s), int(ay_s), int(bx_s), int(by_s))

        # Lasso preview
        if self._lasso_points and self.current_tool == "lasso":
            pen = QPen(QColor(255, 200, 0, 200), 1, Qt.DashLine)
            p.setPen(pen)
            for i in range(len(self._lasso_points) - 1):
                a = self._lasso_points[i];  b = self._lasso_points[i + 1]
                ax, ay = self.image_to_screen(a.x(), a.y())
                bx, by = self.image_to_screen(b.x(), b.y())
                p.drawLine(int(ax), int(ay), int(bx), int(by))

        # Contour preview (Aseprite-style freehand loop)
        if self._contour_points and self.current_tool == "contour":
            pen = QPen(QColor(255, 100, 50, 200), 1, Qt.DashLine)
            p.setPen(pen)
            for i in range(len(self._contour_points) - 1):
                a = self._contour_points[i];  b = self._contour_points[i + 1]
                ax, ay = self.image_to_screen(a.x(), a.y())
                bx, by = self.image_to_screen(b.x(), b.y())
                p.drawLine(int(ax), int(ay), int(bx), int(by))

        # Magic wand / lasso mask
        if self.selection_mask is not None:
            p.setOpacity(0.4)
            p.drawImage(dest, self.selection_mask)
            p.setOpacity(1.0)

        # Grid
        if self.show_grid and self.zoom >= 4:
            self._draw_grid(p)
        self._draw_workspace_axes(p)

        # Selection marching ants
        if self.selection_rect:
            self._draw_selection(p)

        # 3D plane / pivot
        if self.show_3d_plane:
            self._draw_ground_plane(p)
            self._draw_pivot(p)

        # Mirror guides
        if self._symmetry_enabled() or self.current_tool == "symmetry":
            self._draw_mirror_guides(p)

        # Ruler
        if self.show_ruler:
            self._draw_ruler(p)

        # Brush preview cursor
        if self.current_tool in ("pencil", "eraser", "blur") and self.zoom >= 4:
            self._draw_brush_cursor(p)

        # Canvas outline border (matches HTML box-shadow: 0 0 0 1px --border-2)
        self._draw_canvas_border(p)
        self._draw_control_overlay(p)

        p.end()

    # ── Drawing helpers ────────────────────────────────────────────────────────

    def _draw_checker(self, p):
        """Cached checker background aligned to pixel grid."""
        ox = int(self.offset_x); oy = int(self.offset_y)
        cw = int(self.canvas_width * self.zoom)
        ch = int(self.canvas_height * self.zoom)

        if self._checker_cache is None or self._checker_zoom != self.zoom:
            self._checker_zoom  = self.zoom
            cs   = max(1.0, self.checker_size * self.zoom)
            cols = math.ceil(self.canvas_width  / self.checker_size)
            rows = math.ceil(self.canvas_height / self.checker_size)
            pm   = QPixmap(int(cols * cs) + 1, int(rows * cs) + 1)
            pm.fill(self.bg_color1)
            pp   = QPainter(pm)
            for r in range(rows):
                for c in range(cols):
                    if (r + c) % 2 == 1:
                        pp.fillRect(int(c*cs), int(r*cs),
                                    int(cs)+1, int(cs)+1, self.bg_color2)
            pp.end()
            self._checker_cache = pm

        p.setClipRect(QRect(ox, oy, cw, ch))
        p.drawPixmap(ox, oy, self._checker_cache)
        p.setClipRect(self.rect())

    def _draw_grid(self, p):
        """Viewport-clipped grid lines."""
        ox = int(self.offset_x); oy = int(self.offset_y)
        z  = self.zoom
        p.setPen(QPen(self.grid_color, 1))
        # Only draw lines within the visible viewport
        vx0, vy0 = 0, 0
        vx1, vy1 = self.width(), self.height()
        for x in range(self.canvas_width + 1):
            sx = int(ox + x * z)
            if sx < vx0 or sx > vx1:
                continue
            p.drawLine(sx, max(oy, vy0), sx, min(int(oy + self.canvas_height*z), vy1))
        for y in range(self.canvas_height + 1):
            sy = int(oy + y * z)
            if sy < vy0 or sy > vy1:
                continue
            p.drawLine(max(ox, vx0), sy, min(int(ox + self.canvas_width*z), vx1), sy)

    def _draw_workspace_axes(self, p):
        """Always draw center guides: red horizontal, green vertical."""
        cx, cy = self.image_to_screen(self.canvas_width / 2.0, self.canvas_height / 2.0)
        x0, y0 = self.image_to_screen(0, 0)
        x1, y1 = self.image_to_screen(self.canvas_width, self.canvas_height)
        p.setClipRect(QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
        p.setPen(QPen(QColor(240, 88, 88, 165), 1))
        p.drawLine(int(x0), int(cy), int(x1), int(cy))
        p.setPen(QPen(QColor(96, 220, 124, 165), 1))
        p.drawLine(int(cx), int(y0), int(cx), int(y1))
        p.setClipRect(self.rect())

    def _draw_control_overlay(self, p):
        """Visual camera controls overlay (+ / - and directional cluster)."""
        bx = self.width() - 90
        by = 14
        cell = 20
        p.setPen(QPen(QColor(42, 45, 66, 220), 1))
        p.setBrush(QColor(18, 21, 30, 165))
        for dx, dy, label in (
            (1, 0, "^"),
            (0, 1, "<"),
            (1, 1, "o"),
            (2, 1, ">"),
            (1, 2, "v"),
            (3, 0, "+"),
            (3, 1, "-"),
        ):
            x = bx + dx * cell
            y = by + dy * cell
            p.drawRect(x, y, cell - 2, cell - 2)
            p.setPen(QColor(176, 184, 216, 220))
            p.setFont(QFont("IBM Plex Mono", 9, QFont.Bold))
            p.drawText(x, y, cell - 2, cell - 2, Qt.AlignCenter, label)
            p.setPen(QPen(QColor(42, 45, 66, 220), 1))

    def _draw_selection(self, p):
        r = self.selection_rect
        sx0, sy0 = self.image_to_screen(r.x(), r.y())
        sx1, sy1 = self.image_to_screen(r.x() + r.width(), r.y() + r.height())
        rect      = QRect(int(sx0), int(sy0), int(sx1-sx0), int(sy1-sy0))
        # Shadow
        p.setPen(QPen(QColor(0,0,0,200), 1.5, Qt.SolidLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        # Marching ants - accent blue (#5C7CFA)
        pen = QPen(QColor(0x5C, 0x7C, 0xFA, 215), 1.5, Qt.DashLine)
        pen.setDashOffset(self._march_offset)
        p.setPen(pen)
        p.drawRect(rect)
        # Dim outside
        full = QRect(int(self.offset_x), int(self.offset_y),
                     int(self.canvas_width*self.zoom), int(self.canvas_height*self.zoom))
        overlay = QColor(0, 0, 0, 50)
        sel     = rect
        p.setPen(Qt.NoPen)
        p.fillRect(full.x(), full.y(), full.width(), sel.y()-full.y(), overlay)
        p.fillRect(full.x(), sel.y()+sel.height(), full.width(),
                   (full.y()+full.height())-(sel.y()+sel.height()), overlay)
        p.fillRect(full.x(), sel.y(), sel.x()-full.x(), sel.height(), overlay)
        p.fillRect(sel.x()+sel.width(), sel.y(),
                   (full.x()+full.width())-(sel.x()+sel.width()), sel.height(), overlay)

    def _draw_pivot(self, p):
        px, py   = self.pivot
        sx, sy   = self.image_to_screen(px+0.5, py+0.5)
        sx, sy   = int(sx), int(sy)
        arm      = max(10, int(self.zoom * 2.0))
        opacity  = 255 if self._is_dragging_pivot else 180
        p.setPen(QPen(QColor(255, 60,  60,  opacity), 2)); p.drawLine(sx-arm, sy, sx+arm, sy)
        p.setPen(QPen(QColor( 60, 220, 60,  opacity), 2)); p.drawLine(sx, sy-arm, sx, sy+arm)
        p.setPen(QPen(QColor( 60, 120, 255, opacity), 2))
        half = arm // 2; p.drawLine(sx, sy, sx+half, sy-half)
        p.setPen(QPen(QColor(255,255,255,255), 1))
        fill = QColor(255,255,0) if self._is_dragging_pivot else QColor(255,255,255,220)
        p.setBrush(fill)
        p.drawEllipse(sx-4, sy-4, 8, 8)

    def _draw_ground_plane(self, p):
        """
        Draw a ground-plane grid that covers the entire canvas, matching
        StackStudio's reference floor.  Grid lines are every 8 canvas pixels,
        spanning the full canvas_width × canvas_height.
        """
        # Canvas screen rect
        ox  = int(self.offset_x)
        oy  = int(self.offset_y)
        cw  = int(self.canvas_width  * self.zoom)
        ch  = int(self.canvas_height * self.zoom)

        # Clip drawing to canvas area
        p.setClipRect(QRect(ox, oy, cw, ch))

        # Semi-transparent tinted fill over the entire canvas
        p.fillRect(ox, oy, cw, ch, QColor(80, 100, 140, 18))

        # Grid lines every 8 canvas pixels
        grid_size = 8
        p.setPen(QPen(QColor(130, 160, 220, 55), 1))

        for x in range(0, self.canvas_width + 1, grid_size):
            sx, sy0 = self.image_to_screen(x, 0)
            _,  sy1 = self.image_to_screen(x, self.canvas_height)
            p.drawLine(int(sx), int(sy0), int(sx), int(sy1))

        for y in range(0, self.canvas_height + 1, grid_size):
            sx0, sy = self.image_to_screen(0, y)
            sx1, _  = self.image_to_screen(self.canvas_width, y)
            p.drawLine(int(sx0), int(sy), int(sx1), int(sy))

        # Canvas border highlight
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(100, 160, 255, 90), 2))
        p.drawRect(ox, oy, cw - 1, ch - 1)

        # Diagonal centre cross-hair (pivot reference lines)
        px, py = self.pivot
        psx, psy = self.image_to_screen(px + 0.5, py + 0.5)
        p.setPen(QPen(QColor(255, 230, 80, 50), 1, Qt.DashLine))
        p.drawLine(ox,          int(psy), ox + cw,    int(psy))   # horizontal
        p.drawLine(int(psx),    oy,       int(psx),   oy + ch)    # vertical

        p.setClipRect(self.rect())

    def _draw_mirror_guides(self, p):
        # Mirror X: green axis (#3C,DC,50) — mirror Y: red axis (#FF,50,60 at 60%)
        try:
            axis_count = max(1, int(getattr(self, "symmetry_axis_count", 1) or 1))
        except (TypeError, ValueError):
            axis_count = 1
        if axis_count > 1:
            cx, cy = self.symmetry_axis_x + 0.5, self.symmetry_axis_y + 0.5
            radius = math.hypot(self.canvas_width, self.canvas_height)
            p.setPen(QPen(QColor(0x3D, 0xFF, 0xD0, 120), 1, Qt.DashDotLine))
            for i in range(axis_count):
                angle = (math.pi / 2.0) + (math.pi * i / axis_count)
                dx = math.cos(angle) * radius
                dy = math.sin(angle) * radius
                sx0, sy0 = self.image_to_screen(cx - dx, cy - dy)
                sx1, sy1 = self.image_to_screen(cx + dx, cy + dy)
                p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
        if self.mirror_x or self.current_tool == "symmetry":
            p.setPen(QPen(QColor(0x3D, 0xAE, 0xF5, 140), 1, Qt.DashDotLine))  # --blue
            sx,_  = self.image_to_screen(self.symmetry_axis_x + 0.5, 0)
            _,sy0 = self.image_to_screen(0, 0)
            _,sy1 = self.image_to_screen(0, self.canvas_height)
            p.drawLine(int(sx),int(sy0),int(sx),int(sy1))
        if self.mirror_y or self.current_tool == "symmetry":
            p.setPen(QPen(QColor(0xFF, 0x6B, 0x9D, 140), 1, Qt.DashDotLine))  # --pink
            _,sy  = self.image_to_screen(0, self.symmetry_axis_y + 0.5)
            sx0,_ = self.image_to_screen(0, 0)
            sx1,_ = self.image_to_screen(self.canvas_width, 0)
            p.drawLine(int(sx0),int(sy),int(sx1),int(sy))

    def _draw_canvas_border(self, p):
        """Thin 1px border matching HTML #cv-container box-shadow: 0 0 0 1px --border-2."""
        ox = int(self.offset_x); oy = int(self.offset_y)
        cw = int(self.canvas_width * self.zoom)
        ch = int(self.canvas_height * self.zoom)
        p.setPen(QPen(QColor(0x2A, 0x2D, 0x42), 1))  # --border-2
        p.setBrush(Qt.NoBrush)
        p.drawRect(ox - 1, oy - 1, cw + 1, ch + 1)

    def _draw_ruler(self, p):
        """Thin pixel-coordinate ruler along top and left edges."""
        p.setFont(QFont("IBM Plex Mono", 7))
        p.setPen(QColor(0x6870A0, 0, 0, 180))  # use direct color
        p.setPen(QColor(0x68, 0x70, 0xA0, 180))  # --ink2
        step = max(1, int(16 / self.zoom))
        for x in range(0, self.canvas_width + 1, step):
            sx, _ = self.image_to_screen(x, 0)
            p.drawLine(int(sx), 0, int(sx), 6)
            if x % (step * 2) == 0:
                p.drawText(int(sx) + 1, 14, str(x))
        for y in range(0, self.canvas_height + 1, step):
            _, sy = self.image_to_screen(0, y)
            p.drawLine(0, int(sy), 6, int(sy))
            if y % (step * 2) == 0:
                p.drawText(2, int(sy) - 2, str(y))

    def _draw_brush_cursor(self, p):
        """Show the brush footprint as a ghost overlay at cursor position."""
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        img_x, img_y = self.screen_to_image(cursor_pos.x(), cursor_pos.y())
        if not self.is_in_bounds(img_x, img_y):
            return
        p.setPen(QPen(QColor(0x3D, 0xFF, 0xD0, 140), 1, Qt.DotLine))  # --cyan
        p.setBrush(QColor(0x3D, 0xFF, 0xD0, 18))
        for dx, dy in self._brush_offsets(self.brush_size):
            px, py = img_x + dx, img_y + dy
            if self.is_in_bounds(px, py):
                sx, sy = self.image_to_screen(px, py)
                p.drawRect(int(sx), int(sy), int(self.zoom), int(self.zoom))

    def _march_ants_tick(self):
        self._march_offset = (self._march_offset + 1) % 16
        if self.selection_rect:
            self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Mouse events
    # ──────────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        img_x, img_y = self.screen_to_image(event.x(), event.y())

        if event.button() == Qt.MiddleButton:
            self.is_panning       = True
            self.pan_start        = event.pos()
            self.pan_offset_start = (self.offset_x, self.offset_y)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.RightButton:
            if self.current_tool == "zoom":
                old_zoom = self.zoom
                self.zoom = max(self.min_zoom, self.zoom / 1.5)
                mx, my = event.x(), event.y()
                self.offset_x = mx - (mx - self.offset_x) * (self.zoom / old_zoom)
                self.offset_y = my - (my - self.offset_y) * (self.zoom / old_zoom)
                self._checker_cache = None
                self.update()
                return
            # Eyedropper from composite image (all visible layers)
            if self.is_in_bounds(img_x, img_y):
                color = self.get_composite_pixel(img_x, img_y)
                self.secondary_color = color
                self.color_picked.emit(color)
            return

        if event.button() == Qt.LeftButton:
            if self.current_tool == "symmetry":
                if self.is_in_bounds(img_x, img_y):
                    self.symmetry_axis_x = max(0, min(img_x, self.canvas_width - 1))
                    self.symmetry_axis_y = max(0, min(img_y, self.canvas_height - 1))
                    self._drag_symmetry_axis = True
                    self.update()
                return
            # Pivot drag
            px, py   = self.pivot
            psx, psy = self.image_to_screen(px+0.5, py+0.5)
            if math.hypot(event.x()-psx, event.y()-psy) < 15:
                self._is_dragging_pivot = True
                self.setCursor(Qt.SizeAllCursor)
                return

            # Floating image drag (works with any tool)
            if self._floating_active:
                self._move_start       = (event.x(), event.y())
                self._move_orig_offset = self._floating_offset
                return

            # Move tool
            if self.current_tool == "move":
                if self.selection_rect:
                    self._lift_selection()
                    self._move_start       = (event.x(), event.y())
                    self._move_orig_offset = self._floating_offset
                else:
                    # Move active layer content
                    self.save_undo_state()
                    self._move_start = (event.x(), event.y())
                    self._move_layer_content = True
                    self._move_original_layer = self.layers[self.active_layer].copy()
                return

            if self.current_tool == "magic_wand":
                # Save previous mask for selection mode combining
                if self.selection_mode != "replace" and (self.selection_mask is not None or self.selection_rect is not None):
                    if self.selection_mask is not None:
                        self._prev_sel_mask = self.selection_mask.copy()
                    else:
                        self._prev_sel_mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
                        self._prev_sel_mask.fill(Qt.transparent)
                        r = self.selection_rect
                        for py in range(r.y(), r.y() + r.height()):
                            for px in range(r.x(), r.x() + r.width()):
                                if self.is_in_bounds(px, py):
                                    self._prev_sel_mask.setPixelColor(px, py, QColor(0, 120, 255, 100))
                else:
                    self._prev_sel_mask = None
                self.magic_wand_select(img_x, img_y,
                                       tolerance=self.fill_tolerance)
                return

            if self.current_tool == "eyedropper":
                if self.is_in_bounds(img_x, img_y):
                    picked = self.get_composite_pixel(img_x, img_y)
                    self.primary_color = picked
                    self.color_picked.emit(picked)
                return

            if self.current_tool == "fill":
                self.save_undo_state()
                self.flood_fill(img_x, img_y, self.primary_color)
                self.update(); self.canvas_modified.emit()
                return

            if self.current_tool == "gradient":
                self.save_undo_state()
                self.tool_start_pos   = (img_x, img_y)
                self.is_drawing       = True
                self._tool_undo_saved = True
                return

            if self.current_tool in ("pencil", "eraser"):
                self.save_undo_state()
                self.is_drawing       = True
                self._tool_undo_saved = True
                if self.current_tool == "pencil":
                    self.draw_pixel_brush(img_x, img_y, self.primary_color)
                else:
                    self.erase_pixel_brush(img_x, img_y)
                self.last_draw_pos = (img_x, img_y)
                self.update()
                return

            if self.current_tool == "zoom":
                old_zoom = self.zoom
                self.zoom = min(self.max_zoom, self.zoom * 1.5)
                mx, my = event.x(), event.y()
                self.offset_x = mx - (mx - self.offset_x) * (self.zoom / old_zoom)
                self.offset_y = my - (my - self.offset_y) * (self.zoom / old_zoom)
                self._checker_cache = None
                self.update()
                return

            if self.current_tool == "blur":
                self.save_undo_state()
                self.is_drawing       = True
                self._tool_undo_saved = True
                self._apply_blur_brush(img_x, img_y)
                self.last_draw_pos = (img_x, img_y)
                self.update()
                return

            if self.current_tool == "curve":
                self._curve_points.append(QPoint(img_x, img_y))
                if len(self._curve_points) >= 3:
                    self.save_undo_state()
                    self._draw_bezier_curve()
                    self._curve_points = []
                    self.update()
                    self.canvas_modified.emit()
                return

            if self.current_tool == "contour":
                self.is_drawing = True
                self._start_contour(img_x, img_y)
                return

            if self.current_tool in ("line","rect","rect_fill","circle","circle_fill"):
                self.is_drawing     = True
                self.tool_start_pos = (img_x, img_y)
                return

            if self.current_tool == "select":
                self.is_selecting    = True
                self.selection_start = QPoint(img_x, img_y)
                # Save previous mask for selection mode combining
                if self.selection_mode != "replace" and (self.selection_mask is not None or self.selection_rect is not None):
                    if self.selection_mask is not None:
                        self._prev_sel_mask = self.selection_mask.copy()
                    else:
                        # Convert rect to mask
                        self._prev_sel_mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
                        self._prev_sel_mask.fill(Qt.transparent)
                        r = self.selection_rect
                        for py in range(r.y(), r.y() + r.height()):
                            for px in range(r.x(), r.x() + r.width()):
                                if self.is_in_bounds(px, py):
                                    self._prev_sel_mask.setPixelColor(px, py, QColor(0, 120, 255, 100))
                else:
                    self._prev_sel_mask = None
                self.selection_rect  = None
                self.selection_mask  = None
                return

            if self.current_tool == "lasso":
                self.is_selecting = True
                # Save previous mask for selection mode combining
                if self.selection_mode != "replace" and (self.selection_mask is not None or self.selection_rect is not None):
                    if self.selection_mask is not None:
                        self._prev_sel_mask = self.selection_mask.copy()
                    else:
                        self._prev_sel_mask = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
                        self._prev_sel_mask.fill(Qt.transparent)
                        r = self.selection_rect
                        for py in range(r.y(), r.y() + r.height()):
                            for px in range(r.x(), r.x() + r.width()):
                                if self.is_in_bounds(px, py):
                                    self._prev_sel_mask.setPixelColor(px, py, QColor(0, 120, 255, 100))
                else:
                    self._prev_sel_mask = None
                self._start_lasso(img_x, img_y)
                return

    def mouseMoveEvent(self, event):
        img_x, img_y = self.screen_to_image(event.x(), event.y())
        self.cursor_pos_changed.emit(img_x, img_y)
        self.update()   # always repaint for brush cursor ghost

        if self._is_dragging_pivot:
            # Clamp to canvas bounds
            self.pivot = (max(0, min(img_x, self.canvas_width-1)),
                          max(0, min(img_y, self.canvas_height-1)))
            self.pivot_changed.emit(self.pivot[0], self.pivot[1])
            return

        if self._drag_symmetry_axis:
            self.symmetry_axis_x = max(0, min(img_x, self.canvas_width - 1))
            self.symmetry_axis_y = max(0, min(img_y, self.canvas_height - 1))
            self.update()
            return

        if self.is_panning:
            dx = event.x() - self.pan_start.x()
            dy = event.y() - self.pan_start.y()
            self.offset_x = self.pan_offset_start[0] + dx
            self.offset_y = self.pan_offset_start[1] + dy
            return

        # Floating drag (any tool)
        if self._floating_active and self._move_start:
            dx = int((event.x() - self._move_start[0]) / self.zoom)
            dy = int((event.y() - self._move_start[1]) / self.zoom)
            self._floating_offset = (self._move_orig_offset[0] + dx,
                                     self._move_orig_offset[1] + dy)
            return

        if self.current_tool == "move" and self._move_start:
            if self._move_layer_content and self._move_original_layer is not None:
                dx = int((event.x() - self._move_start[0]) / self.zoom)
                dy = int((event.y() - self._move_start[1]) / self.zoom)
                new_img = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
                new_img.fill(Qt.transparent)
                p = QPainter(new_img)
                p.drawImage(dx, dy, self._move_original_layer)
                p.end()
                self.layers[self.active_layer] = new_img
            return

        if self.is_drawing and self.current_tool in ("pencil", "eraser"):
            if self.current_tool == "pencil":
                if self.last_draw_pos:
                    self.draw_line(self.last_draw_pos[0], self.last_draw_pos[1],
                                   img_x, img_y, self.primary_color)
                else:
                    self.draw_pixel_brush(img_x, img_y, self.primary_color)
            else:
                if self.last_draw_pos:
                    self._erase_line(self.last_draw_pos[0], self.last_draw_pos[1],
                                     img_x, img_y)
                else:
                    self.erase_pixel_brush(img_x, img_y)
            self.last_draw_pos = (img_x, img_y)
            return

        if self.is_drawing and self.current_tool == "blur":
            if self.last_draw_pos:
                # Stamp blur along path (simplified)
                self._apply_blur_brush(img_x, img_y)
            else:
                self._apply_blur_brush(img_x, img_y)
            self.last_draw_pos = (img_x, img_y)
            return

        if self.is_drawing and self.current_tool == "gradient" and self.tool_start_pos:
            # Live preview for gradient
            overlay = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
            overlay.fill(Qt.transparent)
            sx, sy = self.tool_start_pos
            x0, y0, x1, y1 = self._resolve_gradient_line(sx, sy, img_x, img_y)
            self.gradient_fill(x0, y0, x1, y1,
                               self.gradient_start_color, self.gradient_end_color,
                               target_image=overlay)
            self.preview_overlay = overlay
            return

        if self.is_drawing and self.current_tool in ("line","rect","rect_fill","circle","circle_fill"):
            self._update_shape_preview(img_x, img_y)
            return

        if self.is_drawing and self.current_tool == "contour":
            self._extend_contour(img_x, img_y)
            return

        if self.is_selecting and self.current_tool == "select" and self.selection_start:
            x0, y0 = self.selection_start.x(), self.selection_start.y()
            self.selection_rect = QRect(min(x0,img_x), min(y0,img_y),
                                        abs(img_x-x0)+1, abs(img_y-y0)+1)
            return

        if self.is_selecting and self.current_tool == "lasso":
            self._extend_lasso(img_x, img_y)

    def mouseReleaseEvent(self, event):
        img_x, img_y = self.screen_to_image(event.x(), event.y())

        if self._is_dragging_pivot:
            self._is_dragging_pivot = False
            self.setCursor(Qt.ArrowCursor)
            return

        if event.button() == Qt.MiddleButton and self.is_panning:
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)
            return

        if event.button() == Qt.LeftButton:
            if self._drag_symmetry_axis:
                self._drag_symmetry_axis = False
                return
            # Floating drag release (any tool)
            if self._floating_active and self._move_start:
                self._move_start       = None
                self._move_orig_offset = None
                self.setCursor(Qt.ArrowCursor)
                return

            if self.current_tool == "move":
                if self._move_layer_content:
                    self._move_layer_content = False
                    self._move_original_layer = None
                    self.save_current_frame()
                    self.canvas_modified.emit()
                self._move_start       = None
                self._move_orig_offset = None
                return

            if self.is_drawing and self.current_tool == "gradient" and self.tool_start_pos:
                sx, sy = self.tool_start_pos
                x0, y0, x1, y1 = self._resolve_gradient_line(sx, sy, img_x, img_y)
                self.gradient_fill(x0, y0, x1, y1,
                                   self.gradient_start_color, self.gradient_end_color)
                self.preview_overlay  = None
                self.is_drawing       = False
                self.tool_start_pos   = None
                self.canvas_modified.emit()
                return

            if self.is_drawing and self.current_tool in ("line","rect","rect_fill","circle","circle_fill"):
                self.save_undo_state()   # save before finalise
                self._finalize_shape(img_x, img_y)
                self.preview_overlay  = None
                self.is_drawing       = False
                self.tool_start_pos   = None
                self.canvas_modified.emit()
                return

            if self.is_drawing and self.current_tool == "contour":
                self._finish_contour()
                self.is_drawing = False
                return

            if self.is_drawing:
                self.is_drawing    = False
                self.last_draw_pos = None
                self.canvas_modified.emit()

            if self.is_selecting:
                self.is_selecting = False
                if self.current_tool == "lasso":
                    self._finish_lasso()
                elif self.selection_rect:
                    self._apply_selection_mode_rect()
                    self.show_context_bar()

    def _update_shape_preview(self, ex, ey):
        if not self.tool_start_pos:
            return
        overlay = QImage(self.canvas_width, self.canvas_height, QImage.Format_ARGB32)
        overlay.fill(Qt.transparent)
        sx, sy = self.tool_start_pos
        c      = self.primary_color
        if   self.current_tool == "line":        self.draw_line(sx, sy, ex, ey, c, target_image=overlay)
        elif self.current_tool == "rect":        self.draw_rect_outline(sx, sy, ex, ey, c, target_image=overlay)
        elif self.current_tool == "rect_fill":   self.draw_rect_filled(sx, sy, ex, ey, c, target_image=overlay)
        elif self.current_tool == "circle":
            rx = abs(ex-sx)//2; ry = abs(ey-sy)//2
            if rx > 0 and ry > 0:
                self.draw_circle_outline((sx+ex)//2, (sy+ey)//2, rx, ry, c, target_image=overlay)
        elif self.current_tool == "circle_fill":
            rx = abs(ex-sx)//2; ry = abs(ey-sy)//2
            if rx > 0 and ry > 0:
                self.draw_circle_filled((sx+ex)//2, (sy+ey)//2, rx, ry, c, target_image=overlay)
        self.preview_overlay = overlay

    def _finalize_shape(self, ex, ey):
        if not self.tool_start_pos:
            return
        sx, sy = self.tool_start_pos
        c      = self.primary_color
        if   self.current_tool == "line":       self.draw_line(sx, sy, ex, ey, c)
        elif self.current_tool == "rect":       self.draw_rect_outline(sx, sy, ex, ey, c)
        elif self.current_tool == "rect_fill":  self.draw_rect_filled(sx, sy, ex, ey, c)
        elif self.current_tool == "circle":
            rx = abs(ex-sx)//2; ry = abs(ey-sy)//2
            if rx > 0 and ry > 0: self.draw_circle_outline((sx+ex)//2,(sy+ey)//2,rx,ry,c)
        elif self.current_tool == "circle_fill":
            rx = abs(ex-sx)//2; ry = abs(ey-sy)//2
            if rx > 0 and ry > 0: self.draw_circle_filled((sx+ex)//2,(sy+ey)//2,rx,ry,c)

    def wheelEvent(self, event):
        delta    = event.angleDelta().y()
        old_zoom = self.zoom
        self.zoom = (min(self.max_zoom, self.zoom * 1.2)
                     if delta > 0 else max(self.min_zoom, self.zoom / 1.2))
        mx, my   = event.x(), event.y()
        self.offset_x = mx - (mx - self.offset_x) * (self.zoom / old_zoom)
        self.offset_y = my - (my - self.offset_y) * (self.zoom / old_zoom)
        self._checker_cache = None
        self.update()

    # ──────────────────────────────────────────────────────────────────────────
    # Keyboard shortcuts
    # ──────────────────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            if self.is_drawing:
                self.is_drawing      = False
                self.preview_overlay = None
                self._lasso_points   = []
                self._contour_points = []
            self.deselect()

        elif key == Qt.Key_Delete:
            if self.selection_rect or self.selection_mask:
                self.delete_selection()

        elif key == Qt.Key_BracketLeft:
            self.brush_size = max(1, self.brush_size - 1)
            self.update()

        elif key == Qt.Key_BracketRight:
            self.brush_size = min(64, self.brush_size + 1)
            self.update()

        elif mods == Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()

        elif mods == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_Z:
            self.redo()

        elif mods == Qt.ControlModifier and key == Qt.Key_Y:
            self.redo()

        elif mods == Qt.ControlModifier and key == Qt.Key_C:
            self.copy_selection()

        elif mods == Qt.ControlModifier and key == Qt.Key_X:
            self.cut_selection()

        elif mods == Qt.ControlModifier and key == Qt.Key_V:
            self.paste_clipboard()

        elif mods == Qt.ControlModifier and key == Qt.Key_A:
            self.select_all()

        elif mods == Qt.ControlModifier and key == Qt.Key_D:
            self.deselect()

        elif mods == Qt.ControlModifier and key == Qt.Key_F:
            self.fit_canvas()

        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            if self._floating_active:
                self.commit_floating()

        else:
            super().keyPressEvent(event)
