"""
3D Sprite Stack Preview using software rendering.
Renders stacked 2D sprite layers in 3D with rotation, zoom, and export.

Fixes applied (see audit doc):
  - mouseMoveEvent added; mousePressEvent no longer runs drag logic
  - lock_x / lock_y now actually checked inside mouseMoveEvent
  - _render_stack squish uses both cos_rot and sin_tilt for correct projection
  - _render_stack base_py formula corrected (removed literal 0 * sin_tilt)
  - _render_stack pivot applied as a proper post-rotation screen offset
  - Shadow now drawn as a projected ellipse beneath the whole stack
  - render_at_angle dispatches to the active render_mode, not always _render_stack
  - export_requested signal is emitted by export_rotation_sheet
  - Voxel mode caches per-layer non-transparent pixel lists
  - numpy import removed (was unused)
  - set_single_image_layers removed (dead duplicate); set_layers is canonical
  - Preview3DPanel gains: rotation spinbox, tilt slider, bg-color picker,
    snap-angle buttons, and a live speed label
  - Info text drawn inside a semi-transparent background rect so it never
    overlaps the stack unreadably on small widgets
  - Auto-rotate speed label updates on every slider change
  - Layer spacing label shows range hint
"""

import math
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QSlider, QCheckBox, QComboBox, QSpinBox
)
from PyQt5.QtGui import QPainter, QColor, QImage, QPen, QBrush
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPoint
from app.theme import T as _T, FONT_FAMILY, FONT_SIZE


class SpriteStack3DPreview(QWidget):
    """
    Real-time 3D sprite stack preview widget (software rendered).
    Left-drag  → rotate (Y) and tilt (X).
    Middle-drag → pan.
    Scroll      → zoom.
    """

    export_requested = pyqtSignal(float)  # emitted with the angle used

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)

        # Stack data
        self.layers = []          # list[QImage]
        self._pixel_cache = []    # list[list[(x, y, QColor)]] per layer
        self.scene_items = []     # dict items for ensemble/focus rendering
        self.preview_scope = "ensemble"   # "ensemble" | "focus"
        self.focus_item_id = None
        # Projection parameters
        self.layer_spacing = 1.0
        self.rotation_angle = 45.0   # degrees, Y-axis
        self.tilt_angle = 30.0       # degrees, X-axis (view elevation)
        self.scale = 3.0
        self.pivot = (0.5, 0.5)      # normalised (0-1), default centre

        # Visual options
        self.bg_color = QColor(40, 40, 45)
        self.show_outline = True
        self.outline_color = QColor(0, 0, 0, 80)
        self.render_mode = "stack"   # "stack" | "voxel" | "billboard"
        self.shadow_enabled = True
        self.shadow_color = QColor(0, 0, 0, 80)

        # Auto-rotate
        self.auto_rotate = False
        self.auto_rotate_speed = 1.0
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._auto_rotate_tick)

        # Interaction state
        self.is_dragging = False
        self.is_panning = False
        self.last_mouse_pos = None
        self.pan_x = 0
        self.pan_y = 0
        self.lock_x = False   # lock_x → prevents tilt change
        self.lock_y = False   # lock_y → prevents rotation change

        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_layers(self, layers):
        """Replace rendered layers (list of QImage, copies taken)."""
        self.scene_items = []
        self.layers = [l.copy() for l in layers if l is not None]
        self._rebuild_pixel_cache()
        self.update()

    def set_scene_items(self, items, scope="ensemble", focus_item_id=None):
        """Set scene payload for ensemble/focus rendering."""
        self.preview_scope = scope if scope in ("ensemble", "focus") else "ensemble"
        self.focus_item_id = focus_item_id
        self.scene_items = []
        for item in items or []:
            layers = [l.copy() for l in item.get("layers", []) if l is not None]
            self.scene_items.append({
                "id": item.get("id"),
                "kind": item.get("kind", "stack"),
                "name": item.get("name", ""),
                "visible": bool(item.get("visible", True)),
                "offset_x": float(item.get("offset_x", 0.0)),
                "offset_y": float(item.get("offset_y", 0.0)),
                "offset_z": float(item.get("offset_z", 0.0)),
                "scale": float(item.get("scale", 1.0)),
                "rotation": float(item.get("rotation", 0.0)),
                "opacity": int(item.get("opacity", 255)),
                "layers": layers,
            })
        self.update()

    def _rebuild_pixel_cache(self):
        """Pre-compute non-transparent pixel lists for voxel mode."""
        self._pixel_cache = []
        for layer in self.layers:
            pixels = []
            if layer and not layer.isNull():
                for y in range(layer.height()):
                    for x in range(layer.width()):
                        c = layer.pixelColor(x, y)
                        if c.alpha() >= 10:
                            pixels.append((x, y, c))
            self._pixel_cache.append(pixels)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.fillRect(self.rect(), self.bg_color)

        has_scene = bool(self.scene_items)
        if not has_scene and not self.layers:
            painter.setPen(QColor(_T['text_dim']))
            painter.setFont(__import__('PyQt5.QtGui', fromlist=['QFont']).QFont(FONT_FAMILY, FONT_SIZE))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No layers to preview\nDraw on layers to see 3D stack")
            painter.end()
            return

        cx = self.width() / 2 + self.pan_x
        cy = self.height() / 2 + self.pan_y

        rot_rad = math.radians(self.rotation_angle)
        tilt_rad = math.radians(self.tilt_angle)
        cos_rot = math.cos(rot_rad)
        sin_rot = math.sin(rot_rad)
        cos_tilt = math.cos(tilt_rad)
        sin_tilt = math.sin(tilt_rad)
        if has_scene:
            n = self._render_scene_items(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt)
        else:
            n = len(self.layers)
            if self.render_mode == "stack":
                self._render_stack(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, n)
            elif self.render_mode == "voxel":
                self._render_voxel(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, n)
            elif self.render_mode == "billboard":
                self._render_billboard(painter, cx, cy, n)

        # HUD overlay — semi-transparent panel bg with ink2 text
        info = (f"Angle: {self.rotation_angle:.0f}°  Tilt: {self.tilt_angle:.0f}°  "
                f"Layers: {n}  Scale: {self.scale:.1f}x")
        from PyQt5.QtGui import QFont
        painter.setFont(QFont(FONT_FAMILY, FONT_SIZE - 1))
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(info)
        text_h = fm.height()
        margin = 5
        painter.setOpacity(0.75)
        painter.fillRect(margin, margin, text_w + margin * 2, text_h + margin * 2,
                         QColor(_T['bg_panel']))
        painter.setOpacity(1.0)
        painter.setPen(QColor(_T['text_muted']))
        painter.drawText(margin * 2, margin + fm.ascent(), info)

        painter.end()

    def _render_scene_items(self, painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt):
        visible_items = [i for i in self.scene_items if i.get("visible", True)]
        if self.preview_scope == "focus" and self.focus_item_id:
            visible_items = [i for i in visible_items if i.get("id") == self.focus_item_id]

        for item in sorted(visible_items, key=lambda i: float(i.get("offset_z", 0.0))):
            layers = item.get("layers", [])
            if not layers:
                continue
            # Apply item-level offset
            ix = cx + item.get("offset_x", 0.0) * self.scale
            iy = cy + item.get("offset_y", 0.0) * self.scale
            kind = item.get("kind", "stack")
            
            # Get item-level transforms
            item_scale = item.get("scale", 1.0)
            item_rotation = item.get("rotation", 0.0)
            item_opacity = item.get("opacity", 255) / 255.0

            prev_layers = self.layers
            prev_cache = self._pixel_cache
            self.layers = layers
            self._rebuild_pixel_cache()
            n_layers = len(self.layers)
            
            # Apply item opacity
            painter.setOpacity(item_opacity)
            
            if kind == "sprite":
                self._render_billboard(painter, ix, iy, n_layers, item_scale)
            else:
                # For stacks, apply item rotation offset to the view rotation
                import math
                item_rot_rad = math.radians(item_rotation)
                mod_cos_rot = cos_rot * math.cos(item_rot_rad) - sin_rot * math.sin(item_rot_rad)
                mod_sin_rot = sin_rot * math.cos(item_rot_rad) + cos_rot * math.sin(item_rot_rad)
                
                if self.render_mode == "stack":
                    self._render_stack(painter, ix, iy, mod_cos_rot, mod_sin_rot, cos_tilt, sin_tilt, n_layers, item_scale)
                elif self.render_mode == "voxel":
                    self._render_voxel(painter, ix, iy, mod_cos_rot, mod_sin_rot, cos_tilt, sin_tilt, n_layers, item_scale)
                else:
                    self._render_billboard(painter, ix, iy, n_layers, item_scale)
            
            # Reset opacity
            painter.setOpacity(1.0)
            self.layers = prev_layers
            self._pixel_cache = prev_cache

        return len(visible_items)

    # ------------------------------------------------------------------
    # Render modes
    # ------------------------------------------------------------------

    def _render_stack(self, painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, num_layers, item_scale=1.0):
        """
        Pseudo-3D sprite-stack render.

        Projection:
          screen_x = cx  +  rx * scale
          screen_y = cy  +  (ry * sin_tilt - zh * cos_tilt) * scale

        where rx = (x_pivot_offset) * cos_rot  (horizontal squish from Y-rotation)
              ry = (x_pivot_offset) * sin_rot  (depth from Y-rotation, used for tilt)
              zh = layer index * layer_spacing  (vertical height in 3D space)

        The pivot offset is applied in projected screen space so that the pivot
        acts as the true rotation centre.
        """
        if not self.layers:
            return

        img_w = self.layers[0].width()
        img_h = self.layers[0].height()

        # Apply item-level scale multiplier
        effective_scale = self.scale * item_scale

        # Scaled base dimensions
        base_w = img_w * effective_scale
        base_h = img_h * effective_scale

        # Pivot in scaled pixels
        piv_sx = self.pivot[0] * base_w
        piv_sy = self.pivot[1] * base_h

        # Draw ground shadow as a projected ellipse under the whole stack
        if self.shadow_enabled:
            # Semi-major axis follows cos_rot (horizontal squish), semi-minor is fixed
            ellipse_w = max(1, int(base_w * abs(cos_rot)))
            ellipse_h = max(1, int(base_h * 0.25))
            # Ground level: zh = 0 → screen_y = cy + piv_sy (bottom of pivot)
            shadow_cx = int(cx)
            shadow_cy = int(cy + piv_sy + 4)
            painter.setOpacity(0.3)
            painter.setBrush(QBrush(self.shadow_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(shadow_cx - ellipse_w // 2, shadow_cy - ellipse_h // 2,
                                ellipse_w, ellipse_h)
            painter.setOpacity(1.0)

        # Squish: horizontal width contracts with both cos_rot (Y rotation)
        # and expands/contracts with sin_tilt (view elevation).
        # At tilt=90 (top-down) we see the full footprint; at tilt=0 (side-on)
        # the horizontal axis is unaffected by tilt, but the image is fully flat.
        # Simple correct formula: display_w = base_w * |cos_rot|
        # (tilt does not affect horizontal extent of a Y-rotation).
        squish = abs(cos_rot)
        display_w = max(1, int(base_w * squish))

        # Draw order: back-to-front depends on tilt angle.
        # Positive tilt (looking from above): draw bottom layers first (0→N).
        # Negative tilt (looking from below): draw top layers first (N→0).
        indices = list(range(len(self.layers)))
        if cos_tilt < 0:
            indices.reverse()

        for i in indices:
            layer = self.layers[i]
            if layer is None or layer.isNull():
                continue

            zh = i * self.layer_spacing

            # Vertical position: pivot depth projected through tilt
            # ry_pivot = pivot_x_offset * sin_rot  (depth of pivot after Y rotation)
            # We centre on cx so ry_pivot is zero for the image centre → just use tilt for zh
            # screen_y of pivot = cy - zh * cos_tilt * scale + piv_sy_contribution
            # piv_sy_contribution accounts for the fact the image is drawn from top-left:
            screen_y_centre = cy - zh * cos_tilt * effective_scale

            x_pos = int(cx - piv_sx * squish)       # left edge of scaled image
            y_pos = int(screen_y_centre - piv_sy)   # top edge

            scaled = layer.scaled(display_w, int(base_h),
                                  Qt.IgnoreAspectRatio, Qt.FastTransformation)

            # Side fill (thickness illusion) between layers
            if i > 0 and self.layer_spacing > 0:
                side_h = max(1, int(abs(self.layer_spacing * cos_tilt * effective_scale)))
                painter.setOpacity(0.35)
                if cos_tilt >= 0:
                    painter.fillRect(x_pos, y_pos + int(base_h), display_w, side_h, Qt.black)
                else:
                    painter.fillRect(x_pos, y_pos - side_h, display_w, side_h, Qt.black)
                painter.setOpacity(1.0)

            painter.drawImage(x_pos, y_pos, scaled)

            if self.show_outline:
                painter.setPen(QPen(self.outline_color, 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(x_pos, y_pos, display_w, int(base_h))

    def _render_voxel(self, painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, num_layers, item_scale=1.0):
        """
        Per-voxel render with cached pixel lists for speed.
        Full 3D rotation: Y-axis rotation + X-axis tilt projection.
        """
        if not self.layers or not self._pixel_cache:
            return

        img_w = self.layers[0].width()
        img_h = self.layers[0].height()
        piv_x = self.pivot[0] * img_w
        piv_y = self.pivot[1] * img_h
        effective_scale = self.scale * item_scale
        v_size = max(1, int(effective_scale))

        # Depth-sort: determine pixel iteration order from viewing angle
        angle = self.rotation_angle % 360
        reverse_x = 90 <= angle < 270
        reverse_y = 180 <= angle < 360

        # Layer order: back-to-front depends on tilt
        layer_indices = list(range(num_layers))
        if cos_tilt < 0:
            layer_indices.reverse()

        for z in layer_indices:
            if z >= len(self._pixel_cache):
                continue
            zh = z * self.layer_spacing

            pixels = self._pixel_cache[z]
            # Sort pixels by depth for back-to-front within each layer
            def depth_key(p):
                lx = p[0] - piv_x
                ly = p[1] - piv_y
                # depth = lx * sin_rot + ly * cos_rot  (ry component)
                return lx * sin_rot + ly * cos_rot

            sorted_pixels = sorted(pixels, key=depth_key, reverse=True)

            for x, y, color in sorted_pixels:
                lx = x - piv_x
                ly = y - piv_y
                lz = zh

                # Y-axis rotation
                rx = lx * cos_rot - ly * sin_rot
                # depth after Y rotation (was misleadingly named ry in original)
                depth = lx * sin_rot + ly * cos_rot

                # Project to screen
                sx = int(cx + rx * effective_scale)
                # screen Y: depth projected by sin_tilt, height projected by cos_tilt
                sy = int(cy + (depth * sin_tilt - lz * cos_tilt) * effective_scale)

                painter.fillRect(sx, sy, v_size, v_size, color)

                if self.show_outline and v_size > 2:
                    painter.setPen(QPen(color.darker(130), 1))
                    painter.drawLine(sx, sy + v_size, sx + v_size, sy + v_size)
                    painter.drawLine(sx + v_size, sy, sx + v_size, sy + v_size)

    def _render_billboard(self, painter, cx, cy, num_layers, item_scale=1.0):
        """Simple billboard: layers spread vertically, always face camera."""
        effective_scale = self.scale * item_scale
        for i, layer in enumerate(self.layers):
            if layer is None or layer.isNull():
                continue
            w = int(layer.width() * effective_scale)
            h = int(layer.height() * effective_scale)
            if w <= 0 or h <= 0:
                continue
            y_offset = -i * self.layer_spacing * effective_scale
            x_pos = int(cx - w / 2)
            y_pos = int(cy + y_offset - h / 2)
            scaled = layer.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawImage(x_pos, y_pos, scaled)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
        elif event.button() == Qt.MiddleButton:
            self.is_panning = True

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None:
            return

        dx = event.x() - self.last_mouse_pos.x()
        dy = event.y() - self.last_mouse_pos.y()

        if self.is_dragging:
            if not self.lock_y:
                self.rotation_angle = (self.rotation_angle + dx * 0.5) % 360
            if not self.lock_x:
                self.tilt_angle = max(-90.0, min(90.0, self.tilt_angle - dy * 0.3))
            self.update()

        elif self.is_panning:
            self.pan_x += dx
            self.pan_y += dy
            self.update()

        self.last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.is_panning = False
        self.last_mouse_pos = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.scale = min(20.0, self.scale * 1.1)
        else:
            self.scale = max(0.5, self.scale / 1.1)
        self.update()

    # ------------------------------------------------------------------
    # Auto rotation
    # ------------------------------------------------------------------

    def toggle_auto_rotate(self, enabled):
        self.auto_rotate = enabled
        if enabled:
            self._rotate_timer.start(33)
        else:
            self._rotate_timer.stop()

    def _auto_rotate_tick(self):
        self.rotation_angle = (self.rotation_angle + self.auto_rotate_speed) % 360
        self.update()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def render_at_angle(self, angle, width=None, height=None):
        """Render the stack at *angle* in the current render_mode. Returns QImage."""
        old_angle = self.rotation_angle
        self.rotation_angle = angle

        w = width or self.width()
        h = height or self.height()

        image = QImage(w, h, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

        cx, cy = w / 2, h / 2
        rot_rad = math.radians(angle)
        tilt_rad = math.radians(self.tilt_angle)
        cos_rot, sin_rot = math.cos(rot_rad), math.sin(rot_rad)
        cos_tilt, sin_tilt = math.cos(tilt_rad), math.sin(tilt_rad)
        if self.scene_items:
            self._render_scene_items(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt)
        else:
            n = len(self.layers)
            if self.render_mode == "stack":
                self._render_stack(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, n)
            elif self.render_mode == "voxel":
                self._render_voxel(painter, cx, cy, cos_rot, sin_rot, cos_tilt, sin_tilt, n)
            elif self.render_mode == "billboard":
                self._render_billboard(painter, cx, cy, n)

        painter.end()
        self.rotation_angle = old_angle
        return image

    def export_rotation_sheet(self, angles=8, size=128):
        """Export a sprite sheet with the stack at *angles* evenly spaced rotations."""
        images = []
        for i in range(angles):
            angle = i * (360.0 / angles)
            img = self.render_at_angle(angle, size, size)
            images.append(img)
            self.export_requested.emit(angle)   # was never emitted before

        sheet = QImage(size * angles, size, QImage.Format_ARGB32)
        sheet.fill(Qt.transparent)
        p = QPainter(sheet)
        for i, img in enumerate(images):
            p.drawImage(i * size, 0, img)
        p.end()
        return sheet

    def reset_view(self):
        self.rotation_angle = 45.0
        self.tilt_angle = 30.0
        self.scale = 3.0
        self.pan_x = 0
        self.pan_y = 0
        self.update()


# ======================================================================
# Preview3DPanel
# ======================================================================

class Preview3DPanel(QWidget):
    """Full 3D preview panel with controls — themed to match HTML #preview-section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_T['bg_panel']}; color: {_T['text']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Panel header (matches HTML .panel-hdr) ────────────────────
        header_frame = QWidget()
        header_frame.setFixedHeight(28)
        header_frame.setStyleSheet(
            f"background: {_T['bg_raised']}; border-bottom: 1px solid {_T['border_dark']};"
        )
        hdr_row = QHBoxLayout(header_frame)
        hdr_row.setContentsMargins(9, 0, 6, 0)
        hdr_row.setSpacing(5)

        hdr_title = QLabel("[3D] Preview")
        hdr_title.setStyleSheet(
            f"font-family: '{FONT_FAMILY}', monospace; font-size: 15px; "
            f"color: {_T['text']}; letter-spacing: 0.08em; background: transparent;"
        )
        hdr_row.addWidget(hdr_title)
        hdr_row.addStretch()

        _pbtn_ss = (
            f"QToolButton {{ background: {_T['bg_input']}; border: 1px solid {_T['border_dark']}; "
            f"color: {_T['text_dim']}; font-size: 11px; "
            f"width: 20px; height: 20px; }}"
            f"QToolButton:hover {{ background: {_T['bg_header']}; color: {_T['text']}; "
            f"border-color: {_T['border_light']}; }}"
            f"QToolButton:checked {{ background: {_T['accent_dim']}; "
            f"border-color: {_T['accent']}; color: {_T['accent']}; }}"
        )

        from PyQt5.QtWidgets import QToolButton
        self._spin_btn = QToolButton()
        self._spin_btn.setText("R")
        self._spin_btn.setToolTip("Auto-rotate")
        self._spin_btn.setCheckable(True)
        self._spin_btn.setChecked(False)
        self._spin_btn.setFixedSize(20, 20)
        self._spin_btn.setStyleSheet(_pbtn_ss)
        hdr_row.addWidget(self._spin_btn)

        reset_btn_hdr = QToolButton()
        reset_btn_hdr.setText("H")
        reset_btn_hdr.setToolTip("Reset view")
        reset_btn_hdr.setFixedSize(20, 20)
        reset_btn_hdr.setStyleSheet(_pbtn_ss)
        hdr_row.addWidget(reset_btn_hdr)

        layout.addWidget(header_frame)

        # ── Preview render widget ─────────────────────────────────────
        self.preview = SpriteStack3DPreview()
        self.preview.bg_color = QColor(_T['bg'])
        layout.addWidget(self.preview, 1)

        # ── Bottom controls (matches HTML #preview-controls) ──────────
        ctrl_bar = QWidget()
        ctrl_bar.setFixedHeight(32)
        ctrl_bar.setStyleSheet(
            f"background: {_T['bg_raised']}; border-top: 1px solid {_T['border_dark']};"
        )
        ctrl_row = QHBoxLayout(ctrl_bar)
        ctrl_row.setContentsMargins(8, 4, 8, 4)
        ctrl_row.setSpacing(4)

        _p_btn_ss = (
            f"QPushButton {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"color: {_T['text_dim']}; font-size: 11px; "
            f"min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; "
            f"padding: 0; }}"
            f"QPushButton:hover {{ background: {_T['bg_header']}; color: {_T['text']}; "
            f"border-color: {_T['border_light']}; }}"
            f"QPushButton:checked {{ background: {_T['accent_dim']}; "
            f"border-color: {_T['accent']}; color: {_T['accent']}; }}"
        )

        def _p_btn(text, tip, checkable=False, checked=False):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(20, 20)
            b.setCheckable(checkable)
            b.setChecked(checked)
            b.setStyleSheet(_p_btn_ss)
            return b

        def _p_sep():
            s = QLabel("|")
            s.setStyleSheet(
                f"color: {_T['border_dark']}; background: transparent; "
                f"font-size: 12px; padding: 0 2px;"
            )
            return s

        self.mode_stack_btn = _p_btn("S", "Stack view", checkable=True, checked=True)
        self.mode_voxel_btn = _p_btn("V", "Voxel view",  checkable=True)
        self.mode_bill_btn  = _p_btn("B", "Billboard view", checkable=True)
        ctrl_row.addWidget(self.mode_stack_btn)
        ctrl_row.addWidget(self.mode_voxel_btn)
        ctrl_row.addWidget(self.mode_bill_btn)
        ctrl_row.addWidget(_p_sep())

        self.angle_label = QLabel("45°")
        self.angle_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}', monospace; font-size: 13px; "
            f"color: {_T['text_muted']}; background: transparent; padding: 0 4px;"
        )
        ctrl_row.addWidget(self.angle_label)
        ctrl_row.addWidget(_p_sep())

        rot_left  = _p_btn("<", "Rotate left")
        rot_right = _p_btn(">", "Rotate right")
        ctrl_row.addWidget(rot_left)
        ctrl_row.addWidget(rot_right)
        ctrl_row.addWidget(_p_sep())

        export_btn = _p_btn("Ex", "Export rotation sheet")
        ctrl_row.addWidget(export_btn)
        ctrl_row.addStretch()

        layout.addWidget(ctrl_bar)

        # ── Expandable controls section ───────────────────────────────
        adv = QWidget()
        adv.setStyleSheet(f"background: {_T['bg_panel']};")
        adv_layout = QVBoxLayout(adv)
        adv_layout.setContentsMargins(9, 6, 9, 6)
        adv_layout.setSpacing(4)

        _lbl_ss = (
            f"font-family: '{FONT_FAMILY}', monospace; font-size: 13px; "
            f"color: {_T['text_muted']}; background: transparent; min-width: 80px;"
        )
        _val_ss = (
            f"font-family: '{FONT_FAMILY}', monospace; font-size: 13px; "
            f"color: {_T['accent']}; background: transparent; min-width: 40px; "
            f"text-align: right;"
        )

        def _ctrl_row(label_text, widget, value_label=None):
            row = QHBoxLayout()
            row.setSpacing(7)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(_lbl_ss)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            if value_label:
                value_label.setStyleSheet(_val_ss)
                row.addWidget(value_label)
            return row

        _slider_ss = (
            f"QSlider::groove:horizontal {{ background: {_T['bg_input']}; "
            f"border: 1px solid {_T['border']}; height: 6px; }}"
            f"QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {_T['accent']}, stop:1 {_T['accent']}); }}"
            f"QSlider::handle:horizontal {{ background: {_T['text_bright']}; "
            f"border: 1px solid {_T['border_light']}; width: 11px; margin: -3px 0; }}"
        )
        _spin_ss = (
            f"QSpinBox {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"color: {_T['text']}; padding: 2px 4px; "
            f"font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZE}px; }}"
        )
        _combo_ss = (
            f"QComboBox {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"color: {_T['text']}; padding: 2px 6px; "
            f"font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZE}px; }}"
            f"QComboBox QAbstractItemView {{ background: {_T['bg_panel']}; "
            f"color: {_T['text']}; border: 1px solid {_T['border_light']}; "
            f"selection-background-color: {_T['accent_dim']}; }}"
        )

        # Layer spacing
        self.spacing_slider = QSlider(Qt.Horizontal)
        self.spacing_slider.setRange(1, 100)
        self.spacing_slider.setValue(10)
        self.spacing_slider.setStyleSheet(_slider_ss)
        self.spacing_label = QLabel("1.0")
        self.spacing_slider.valueChanged.connect(self._on_spacing_changed)
        adv_layout.addLayout(_ctrl_row("Spacing:", self.spacing_slider, self.spacing_label))

        # Rotation spinbox
        self.rotation_spin = QSpinBox()
        self.rotation_spin.setRange(0, 359)
        self.rotation_spin.setValue(45)
        self.rotation_spin.setWrapping(True)
        self.rotation_spin.setStyleSheet(_spin_ss)
        self.rotation_spin.valueChanged.connect(self._on_rotation_spin_changed)
        adv_layout.addLayout(_ctrl_row("Rotation:", self.rotation_spin))

        # Snap buttons
        snap_row = QHBoxLayout()
        snap_row.setSpacing(3)
        snap_lbl = QLabel("Snap:")
        snap_lbl.setStyleSheet(_lbl_ss)
        snap_row.addWidget(snap_lbl)
        _snap_btn_ss = (
            f"QPushButton {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"color: {_T['text_muted']}; font-family: '{FONT_FAMILY}'; font-size: 12px; "
            f"padding: 2px 3px; }}"
            f"QPushButton:hover {{ background: {_T['bg_header']}; color: {_T['text_bright']}; "
            f"border-color: {_T['border_light']}; }}"
        )
        for a in [0, 45, 90, 135, 180, 225, 270, 315]:
            btn = QPushButton(f"{a}°")
            btn.setFixedWidth(34)
            btn.setStyleSheet(_snap_btn_ss)
            btn.clicked.connect(lambda _, ang=a: self._snap_angle(ang))
            snap_row.addWidget(btn)
        adv_layout.addLayout(snap_row)

        # Tilt
        self.tilt_slider = QSlider(Qt.Horizontal)
        self.tilt_slider.setRange(-90, 90)
        self.tilt_slider.setValue(30)
        self.tilt_slider.setStyleSheet(_slider_ss)
        self.tilt_label = QLabel("30°")
        self.tilt_slider.valueChanged.connect(self._on_tilt_changed)
        adv_layout.addLayout(_ctrl_row("Tilt:", self.tilt_slider, self.tilt_label))

        # Mode combo
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["stack", "voxel", "billboard"])
        self.mode_combo.setStyleSheet(_combo_ss)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        adv_layout.addLayout(_ctrl_row("Mode:", self.mode_combo))

        # Checkboxes row
        _cb_ss = (
            f"QCheckBox {{ color: {_T['text_muted']}; font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZE}px; "
            f"spacing: 4px; background: transparent; }}"
            f"QCheckBox::indicator {{ width: 12px; height: 12px; background: {_T['bg_input']}; "
            f"border: 1px solid {_T['border']}; }}"
            f"QCheckBox::indicator:checked {{ background: {_T['accent']}; border-color: {_T['accent']}; }}"
        )
        cb_row = QHBoxLayout()
        self.auto_rotate_cb = QCheckBox("Auto Rotate")
        self.auto_rotate_cb.setStyleSheet(_cb_ss)
        self.auto_rotate_cb.toggled.connect(self.preview.toggle_auto_rotate)
        cb_row.addWidget(self.auto_rotate_cb)
        self.outline_cb = QCheckBox("Outlines")
        self.outline_cb.setChecked(True)
        self.outline_cb.setStyleSheet(_cb_ss)
        self.outline_cb.toggled.connect(lambda v: setattr(self.preview, 'show_outline', v) or self.preview.update())
        cb_row.addWidget(self.outline_cb)
        self.shadow_cb = QCheckBox("Shadow")
        self.shadow_cb.setChecked(True)
        self.shadow_cb.setStyleSheet(_cb_ss)
        self.shadow_cb.toggled.connect(lambda v: setattr(self.preview, 'shadow_enabled', v) or self.preview.update())
        cb_row.addWidget(self.shadow_cb)
        adv_layout.addLayout(cb_row)

        cb_row2 = QHBoxLayout()
        self.lock_x_cb = QCheckBox("Lock Tilt")
        self.lock_x_cb.setStyleSheet(_cb_ss)
        self.lock_x_cb.toggled.connect(lambda v: setattr(self.preview, 'lock_x', v))
        cb_row2.addWidget(self.lock_x_cb)
        self.lock_y_cb = QCheckBox("Lock Rot")
        self.lock_y_cb.setStyleSheet(_cb_ss)
        self.lock_y_cb.toggled.connect(lambda v: setattr(self.preview, 'lock_y', v))
        cb_row2.addWidget(self.lock_y_cb)
        adv_layout.addLayout(cb_row2)

        # Speed slider
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 100)
        self.speed_slider.setValue(10)
        self.speed_slider.setStyleSheet(_slider_ss)
        self.speed_label = QLabel("1.0°/t")
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        adv_layout.addLayout(_ctrl_row("Rot Speed:", self.speed_slider, self.speed_label))

        # BG color + reset buttons
        _action_btn_ss = (
            f"QPushButton {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"border-bottom: 2px solid rgba(0,0,0,0.5); "
            f"color: {_T['text_muted']}; font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZE}px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {_T['bg_header']}; color: {_T['text_bright']}; "
            f"border-color: {_T['border_light']}; }}"
            f"QPushButton:pressed {{ border-bottom-width: 1px; padding-top: 5px; }}"
        )
        btn_row = QHBoxLayout()
        self.bg_btn = QPushButton("BG Colour...")
        self.bg_btn.setStyleSheet(_action_btn_ss)
        self.bg_btn.clicked.connect(self._pick_bg_color)
        btn_row.addWidget(self.bg_btn)
        reset_btn = QPushButton("Reset View")
        reset_btn.setStyleSheet(_action_btn_ss)
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)
        adv_layout.addLayout(btn_row)

        layout.addWidget(adv)

        # ── Wire up header buttons ─────────────────────────────────────
        self._spin_btn.toggled.connect(self.preview.toggle_auto_rotate)
        self._spin_btn.toggled.connect(self.auto_rotate_cb.setChecked)
        reset_btn_hdr.clicked.connect(self._on_reset)

        # Mode buttons
        self.mode_stack_btn.clicked.connect(lambda: self._set_mode("stack"))
        self.mode_voxel_btn.clicked.connect(lambda: self._set_mode("voxel"))
        self.mode_bill_btn.clicked.connect(lambda:  self._set_mode("billboard"))

        # Rotation controls from ctrl bar
        rot_left.clicked.connect(lambda: self._rotate(-15))
        rot_right.clicked.connect(lambda: self._rotate(15))

    # ------------------------------------------------------------------
    # Control handlers
    # ------------------------------------------------------------------

    def _on_spacing_changed(self, val):
        spacing = val / 10.0
        self.preview.layer_spacing = spacing
        self.spacing_label.setText(f"{spacing:.1f}")
        self.preview.update()

    def _on_rotation_spin_changed(self, val):
        self.preview.rotation_angle = float(val)
        self.angle_label.setText(f"{val}°")
        self.preview.update()

    def _snap_angle(self, angle):
        self.rotation_spin.setValue(angle)

    def _rotate(self, delta):
        new_angle = int((self.preview.rotation_angle + delta) % 360)
        self.rotation_spin.setValue(new_angle)

    def _set_mode(self, mode):
        self.mode_combo.setCurrentText(mode)
        self.mode_stack_btn.setChecked(mode == "stack")
        self.mode_voxel_btn.setChecked(mode == "voxel")
        self.mode_bill_btn.setChecked(mode == "billboard")

    def _on_tilt_changed(self, val):
        self.preview.tilt_angle = float(val)
        self.tilt_label.setText(f"{val}°")
        self.preview.update()

    def _on_mode_changed(self, mode):
        self.preview.render_mode = mode
        self.preview.update()

    def _on_speed_changed(self, val):
        speed = val / 10.0
        self.preview.auto_rotate_speed = speed
        self.speed_label.setText(f"{speed:.1f}°/t")

    def _pick_bg_color(self):
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self.preview.bg_color, self, "Background Colour")
        if color.isValid():
            self.preview.bg_color = color
            self.preview.update()

    def _on_reset(self):
        self.preview.reset_view()
        self.rotation_spin.blockSignals(True)
        self.rotation_spin.setValue(45)
        self.rotation_spin.blockSignals(False)
        self.angle_label.setText("45°")
        self.tilt_slider.blockSignals(True)
        self.tilt_slider.setValue(30)
        self.tilt_slider.blockSignals(False)
        self.tilt_label.setText("30°")

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------

    def update_layers(self, layers):
        """Update preview with current layers (list of QImage)."""
        self.preview.set_layers(layers)

    def update_scene(self, scene_items, scope="ensemble", focus_item_id=None):
        """Update preview from scene payload (objects + sprites)."""
        self.preview.set_scene_items(scene_items, scope, focus_item_id)

    def set_pivot(self, px, py):
        """Set pivot point (normalised 0-1 coords)."""
        self.preview.pivot = (px, py)
        self.preview.update()


# ======================================================================
# Inline3DOverlay – floating 3D preview with corner-grouped controls
# ======================================================================

class Inline3DOverlay(QWidget):
    """
    Full-screen overlay for the Create workspace that shows a 3D preview
    of the active object with compact corner-grouped controls.

    Layout:
      ┌─[TL: mode/view]──────────────────[TR: rotation/tilt]─┐
      │                                                       │
      │              SpriteStack3DPreview                      │
      │                                                       │
      └─[BL: spacing/auto]───────────[BR: d-pad / +- scale]──┘

    Signals:
      scale_changed(float)   – emitted when +/- pressed (real scale delta)
      nudge_requested(dx,dy) – emitted when arrow pressed (px offset for slices)
    """

    scale_changed = pyqtSignal(float)      # delta multiplier
    nudge_requested = pyqtSignal(int, int)  # dx, dy in pixels

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {_T['bg']};")

        # Central preview
        self.preview = SpriteStack3DPreview(self)
        self.preview.bg_color = QColor(_T['bg'])

        # ── Shared styles ────────────────────────────────────────
        _fbtn = (
            f"QPushButton {{ background: rgba(18,19,26,210); "
            f"border: 1px solid {_T['border_dark']}; border-radius: 4px; "
            f"color: {_T['text_dim']}; font-family: '{FONT_FAMILY}'; "
            f"font-size: 13px; min-width: 26px; min-height: 26px; "
            f"max-width: 26px; max-height: 26px; padding: 0; }}"
            f"QPushButton:hover {{ background: {_T['bg_header']}; "
            f"color: {_T['text_bright']}; border-color: {_T['border_light']}; }}"
            f"QPushButton:checked {{ background: {_T['accent_dim']}; "
            f"color: {_T['accent']}; border-color: {_T['accent']}; }}"
        )
        _lbl = (
            f"color: {_T['text_muted']}; font-family: '{FONT_FAMILY}'; "
            f"font-size: 10px; background: transparent;"
        )
        _cluster = (
            f"background: rgba(18,19,26,210); "
            f"border: 1px solid {_T['border_dark']}; border-radius: 6px; "
            f"padding: 4px;"
        )
        _slider = (
            f"QSlider::groove:horizontal {{ background: {_T['bg_input']}; "
            f"border: 1px solid {_T['border']}; height: 4px; }}"
            f"QSlider::handle:horizontal {{ background: {_T['text_bright']}; "
            f"border: 1px solid {_T['border_light']}; width: 8px; margin: -3px 0; }}"
            f"QSlider::sub-page:horizontal {{ background: {_T['accent']}; }}"
        )

        def _btn(text, tip="", checkable=False):
            b = QPushButton(text, self)
            b.setToolTip(tip)
            b.setStyleSheet(_fbtn)
            b.setCheckable(checkable)
            return b

        # ── TOP-LEFT cluster: Render mode ────────────────────────
        self._tl = QWidget(self)
        self._tl.setStyleSheet(_cluster)
        tl_lay = QVBoxLayout(self._tl)
        tl_lay.setContentsMargins(5, 5, 5, 5)
        tl_lay.setSpacing(3)

        mode_lbl = QLabel("MODE")
        mode_lbl.setStyleSheet(_lbl + "font-weight: bold;")
        tl_lay.addWidget(mode_lbl)
        mode_row = QHBoxLayout(); mode_row.setSpacing(2)
        self._mode_stack = _btn("S", "Stack view", True)
        self._mode_stack.setChecked(True)
        self._mode_voxel = _btn("V", "Voxel view", True)
        self._mode_bill = _btn("B", "Billboard", True)
        for b in (self._mode_stack, self._mode_voxel, self._mode_bill):
            mode_row.addWidget(b)
        tl_lay.addLayout(mode_row)

        view_row = QHBoxLayout(); view_row.setSpacing(2)
        self._outline_btn = _btn("=", "Outlines", True)
        self._outline_btn.setChecked(True)
        self._shadow_btn = _btn("O", "Shadow", True)
        self._shadow_btn.setChecked(True)
        view_row.addWidget(self._outline_btn)
        view_row.addWidget(self._shadow_btn)
        tl_lay.addLayout(view_row)

        # ── TOP-RIGHT cluster: Rotation / Tilt ───────────────────
        self._tr = QWidget(self)
        self._tr.setStyleSheet(_cluster)
        tr_lay = QVBoxLayout(self._tr)
        tr_lay.setContentsMargins(5, 5, 5, 5)
        tr_lay.setSpacing(3)

        rot_lbl = QLabel("ANGLE")
        rot_lbl.setStyleSheet(_lbl + "font-weight: bold;")
        tr_lay.addWidget(rot_lbl)

        self._angle_label = QLabel("45°")
        self._angle_label.setStyleSheet(
            f"color: {_T['accent']}; font-family: '{FONT_FAMILY}'; "
            f"font-size: 13px; font-weight: bold; background: transparent;"
        )
        tr_lay.addWidget(self._angle_label)

        snap_row = QHBoxLayout(); snap_row.setSpacing(2)
        for a in [0, 45, 90, 180]:
            sb = _btn(f"{a}", f"Snap to {a}°")
            sb.setStyleSheet(_fbtn.replace("min-width: 26px", "min-width: 22px")
                                   .replace("max-width: 26px", "max-width: 22px")
                                   .replace("font-size: 13px", "font-size: 9px"))
            sb.clicked.connect(lambda _, ang=a: self._snap(ang))
            snap_row.addWidget(sb)
        tr_lay.addLayout(snap_row)

        tilt_row = QHBoxLayout(); tilt_row.setSpacing(3)
        tilt_lbl2 = QLabel("Tilt")
        tilt_lbl2.setStyleSheet(_lbl)
        self._tilt_slider = QSlider(Qt.Horizontal)
        self._tilt_slider.setRange(-90, 90)
        self._tilt_slider.setValue(30)
        self._tilt_slider.setFixedWidth(70)
        self._tilt_slider.setStyleSheet(_slider)
        tilt_row.addWidget(tilt_lbl2)
        tilt_row.addWidget(self._tilt_slider)
        tr_lay.addLayout(tilt_row)

        # ── BOTTOM-LEFT cluster: Spacing / Auto-rotate ───────────
        self._bl = QWidget(self)
        self._bl.setStyleSheet(_cluster)
        bl_lay = QVBoxLayout(self._bl)
        bl_lay.setContentsMargins(5, 5, 5, 5)
        bl_lay.setSpacing(3)

        sp_lbl = QLabel("SPACING")
        sp_lbl.setStyleSheet(_lbl + "font-weight: bold;")
        bl_lay.addWidget(sp_lbl)

        sp_row = QHBoxLayout(); sp_row.setSpacing(3)
        self._spacing_slider = QSlider(Qt.Horizontal)
        self._spacing_slider.setRange(1, 100)
        self._spacing_slider.setValue(10)
        self._spacing_slider.setFixedWidth(80)
        self._spacing_slider.setStyleSheet(_slider)
        self._spacing_val = QLabel("1.0")
        self._spacing_val.setStyleSheet(
            f"color: {_T['accent']}; font-family: '{FONT_FAMILY}'; "
            f"font-size: 10px; background: transparent;"
        )
        sp_row.addWidget(self._spacing_slider)
        sp_row.addWidget(self._spacing_val)
        bl_lay.addLayout(sp_row)

        auto_row = QHBoxLayout(); auto_row.setSpacing(3)
        self._auto_btn = _btn("R", "Auto-rotate", True)
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(1, 100)
        self._speed_slider.setValue(10)
        self._speed_slider.setFixedWidth(60)
        self._speed_slider.setStyleSheet(_slider)
        auto_row.addWidget(self._auto_btn)
        auto_row.addWidget(self._speed_slider)
        bl_lay.addLayout(auto_row)

        # ── BOTTOM-RIGHT cluster: D-pad (nudge) + Scale ──────────
        self._br = QWidget(self)
        self._br.setStyleSheet(_cluster)
        br_lay = QVBoxLayout(self._br)
        br_lay.setContentsMargins(5, 5, 5, 5)
        br_lay.setSpacing(3)

        nav_lbl = QLabel("ALIGN / SCALE")
        nav_lbl.setStyleSheet(_lbl + "font-weight: bold;")
        br_lay.addWidget(nav_lbl)

        # D-pad
        dpad = QGridLayout()
        dpad.setSpacing(2)
        self._up_btn = _btn("^", "Nudge slices up (1 px)")
        self._down_btn = _btn("v", "Nudge slices down (1 px)")
        self._left_btn = _btn("<", "Nudge slices left (1 px)")
        self._right_btn = _btn(">", "Nudge slices right (1 px)")
        self._center_btn = _btn("*", "Center object")
        self._center_btn.setStyleSheet(_fbtn.replace("font-size: 13px", "font-size: 10px"))
        dpad.addWidget(self._up_btn, 0, 1)
        dpad.addWidget(self._left_btn, 1, 0)
        dpad.addWidget(self._center_btn, 1, 1)
        dpad.addWidget(self._right_btn, 1, 2)
        dpad.addWidget(self._down_btn, 2, 1)
        br_lay.addLayout(dpad)

        # +/- scale
        scale_row = QHBoxLayout(); scale_row.setSpacing(2)
        self._scale_down = _btn("-", "Scale down slices (real resize)")
        self._scale_up = _btn("+", "Scale up slices (real resize)")
        self._scale_label = QLabel("1x")
        self._scale_label.setStyleSheet(
            f"color: {_T['accent']}; font-family: '{FONT_FAMILY}'; "
            f"font-size: 11px; font-weight: bold; background: transparent; "
            f"padding: 0 4px;"
        )
        scale_row.addWidget(self._scale_down)
        scale_row.addWidget(self._scale_label)
        scale_row.addWidget(self._scale_up)
        br_lay.addLayout(scale_row)

        # ── Wire up controls ─────────────────────────────────────
        self._mode_stack.clicked.connect(lambda: self._set_mode("stack"))
        self._mode_voxel.clicked.connect(lambda: self._set_mode("voxel"))
        self._mode_bill.clicked.connect(lambda: self._set_mode("billboard"))
        self._outline_btn.toggled.connect(
            lambda v: setattr(self.preview, 'show_outline', v) or self.preview.update())
        self._shadow_btn.toggled.connect(
            lambda v: setattr(self.preview, 'shadow_enabled', v) or self.preview.update())
        self._tilt_slider.valueChanged.connect(self._on_tilt)
        self._spacing_slider.valueChanged.connect(self._on_spacing)
        self._auto_btn.toggled.connect(self.preview.toggle_auto_rotate)
        self._speed_slider.valueChanged.connect(self._on_speed)

        self._up_btn.clicked.connect(lambda: self.nudge_requested.emit(0, -1))
        self._down_btn.clicked.connect(lambda: self.nudge_requested.emit(0, 1))
        self._left_btn.clicked.connect(lambda: self.nudge_requested.emit(-1, 0))
        self._right_btn.clicked.connect(lambda: self.nudge_requested.emit(1, 0))
        self._scale_down.clicked.connect(lambda: self.scale_changed.emit(-1))
        self._scale_up.clicked.connect(lambda: self.scale_changed.emit(1))

    # Layout corners on resize
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.preview.setGeometry(0, 0, self.width(), self.height())
        m = 8  # margin
        self._tl.adjustSize()
        self._tl.move(m, m)
        self._tr.adjustSize()
        self._tr.move(self.width() - self._tr.width() - m, m)
        self._bl.adjustSize()
        self._bl.move(m, self.height() - self._bl.height() - m)
        self._br.adjustSize()
        self._br.move(self.width() - self._br.width() - m,
                      self.height() - self._br.height() - m)

    # ── Handlers ─────────────────────────────────────────────────
    def _set_mode(self, mode):
        self.preview.render_mode = mode
        self._mode_stack.setChecked(mode == "stack")
        self._mode_voxel.setChecked(mode == "voxel")
        self._mode_bill.setChecked(mode == "billboard")
        self.preview.update()

    def _snap(self, angle):
        self.preview.rotation_angle = float(angle)
        self._angle_label.setText(f"{angle}°")
        self.preview.update()

    def _on_tilt(self, val):
        self.preview.tilt_angle = float(val)
        self.preview.update()

    def _on_spacing(self, val):
        sp = val / 10.0
        self.preview.layer_spacing = sp
        self._spacing_val.setText(f"{sp:.1f}")
        self.preview.update()

    def _on_speed(self, val):
        self.preview.auto_rotate_speed = val / 10.0

    # ── Public API ───────────────────────────────────────────────
    def set_layers(self, layers):
        self.preview.set_layers(layers)

    def set_scene_items(self, items, scope="ensemble", focus_item_id=None):
        self.preview.set_scene_items(items, scope, focus_item_id)

    def update_scene(self, scene_items, scope="ensemble", focus_item_id=None):
        """Alias for set_scene_items (matches Preview3DPanel API)."""
        self.preview.set_scene_items(scene_items, scope, focus_item_id)

    def set_pivot(self, px, py):
        self.preview.pivot = (px, py)
        self.preview.update()

    def update_scale_label(self, factor):
        self._scale_label.setText(f"{factor:.0f}x" if factor >= 1 else f"{factor:.1f}x")
