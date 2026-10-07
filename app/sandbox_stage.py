from __future__ import annotations

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt5.QtWidgets import QWidget

from app.theme import (
    ACCENT,
    BG_DARK,
    BORDER,
    BORDER_LIGHT,
    CYAN,
    FONT_FAMILY,
    FONT_SIZE,
    GREEN,
    RED,
    TEXT_BRIGHT,
    TEXT_MUTED,
    YELLOW,
)


class SandboxStage(QWidget):
    """
    Chess-board-style level stage for SpriteStack Studio Sandbox.

    The AI scene parser populates this canvas automatically when a response
    arrives. Objects are rendered at the positions and sizes the model
    decided. The user may drag objects afterward to fine-tune placement.

    Coordinate system
    -----------------
    All object positions are normalised floats in [0, 1] relative to the
    stage widget's current pixel dimensions. (0, 0) is top-left.
    """

    object_moved = pyqtSignal(str, float, float)
    object_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objects: list[dict] = []
        self._selected_id = ""
        self._dragging_id = ""
        self._panning = False
        self._drag_offset = (0.0, 0.0)
        self._pan_start = QPointF(0.0, 0.0)
        self._pan_origin = QPointF(0.0, 0.0)
        self._view_zoom = 1.0
        self._min_zoom = 0.12
        self._max_zoom = 32.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._preview_enabled = False
        self._sprite_pixmaps: dict[str, QPixmap] = {}
        self._palette = [ACCENT, GREEN, YELLOW, CYAN, RED]
        self._num_screens = 1
        self.show_grid = True
        self.setMinimumSize(360, 260)
        self.setMouseTracking(True)

    @property
    def num_screens(self) -> int:
        return self._num_screens

    @num_screens.setter
    def num_screens(self, val: int):
        self._num_screens = max(1, int(val))
        self.updateGeometry()
        self._clamp_pan()
        self.update()

    def update_stage_dimensions(self, viewport_height: int):
        h = max(260, int(viewport_height or 260))
        w = h * self._num_screens
        self.setFixedSize(max(360, w), h)

    def set_scene(self, objects: list[dict]) -> None:
        normalised = []
        for i, obj in enumerate(objects or []):
            if not isinstance(obj, dict):
                continue
            item = dict(obj)
            item.setdefault("id", f"scene_obj_{i + 1}")
            item.setdefault("label", item.get("name") or item.get("object") or f"Object {i + 1}")
            item["x"] = self._clamp_float(item.get("x"), 0.0, 1.0, 0.5)
            item["y"] = self._clamp_float(item.get("y"), 0.0, 1.0, 0.5)
            item["w"] = self._clamp_float(item.get("w"), 0.001, 1.0, 0.0625)
            item["h"] = self._clamp_float(item.get("h"), 0.001, 1.0, 0.0625)
            item["scale"] = self._clamp_float(item.get("scale"), 0.01, 100.0, 1.0)
            item["depth"] = self._clamp_float(item.get("depth", item.get("z")), -9999.0, 9999.0, float(i))
            normalised.append(item)
        previous_selected = self._selected_id
        self._objects = sorted(normalised, key=lambda o: float(o.get("depth", 0.0)))
        valid_ids = {str(o.get("id", "")) for o in self._objects}
        self._selected_id = previous_selected if previous_selected in valid_ids else ""
        self._dragging_id = ""
        self._clamp_pan()
        self.update()

    def clear_scene(self) -> None:
        self._objects = []
        self._selected_id = ""
        self._dragging_id = ""
        self._panning = False
        self.update()

    def reset_view(self) -> None:
        self._view_zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def zoom_view(self, factor: float) -> None:
        self._zoom_at(self.rect().center(), factor)

    def view_zoom(self) -> float:
        return self._view_zoom

    def set_preview_enabled(self, enabled: bool) -> None:
        self._preview_enabled = bool(enabled)
        self.update()

    def preview_enabled(self) -> bool:
        return self._preview_enabled

    def set_sprite_images(self, images: dict[str, QPixmap]) -> None:
        self._sprite_pixmaps = {
            str(k): v
            for k, v in (images or {}).items()
            if isinstance(v, QPixmap) and not v.isNull()
        }
        self.update()

    def select_object(self, object_id: str) -> None:
        self._selected_id = str(object_id or "")
        self.update()

    def objects(self) -> list[dict]:
        return [dict(o) for o in self._objects]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        self._draw_board(p)
        if not self._objects:
            self._draw_empty_state(p)
        else:
            for i, obj in enumerate(self._objects):
                if self._preview_enabled:
                    self._draw_preview_object(p, obj, i)
                else:
                    self._draw_object(p, obj, i)
        p.end()

    def mousePressEvent(self, event):
        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._pan_start = QPointF(event.pos())
            self._pan_origin = QPointF(self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton:
            return
        for obj in reversed(self._objects):
            rect = self._object_rect(obj)
            if rect.contains(event.pos()):
                self._selected_id = str(obj.get("id", ""))
                self._dragging_id = self._selected_id
                stage_pos = self._screen_to_stage(event.x(), event.y())
                self._drag_offset = (
                    stage_pos.x() - float(obj.get("x", 0.0)),
                    stage_pos.y() - float(obj.get("y", 0.0)),
                )
                self.object_selected.emit(self._selected_id)
                self.update()
                return
        self._selected_id = ""
        self._dragging_id = ""
        self.update()

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = QPointF(event.pos()) - self._pan_start
            self._pan_x = self._pan_origin.x() + delta.x()
            self._pan_y = self._pan_origin.y() + delta.y()
            self._clamp_pan()
            self.update()
            return
        if not self._dragging_id:
            return
        obj = self._find_object(self._dragging_id)
        if obj is None:
            return
        scale = max(0.01, float(obj.get("scale", 1.0) or 1.0))
        w = min(1.0, float(obj.get("w", 0.12)) * scale)
        h = min(1.0, float(obj.get("h", 0.12)) * scale)
        stage_pos = self._screen_to_stage(event.x(), event.y())
        x = max(0.0, min(stage_pos.x() - self._drag_offset[0], 1.0 - w))
        y = max(0.0, min(stage_pos.y() - self._drag_offset[1], 1.0 - h))
        cols, rows = 16 * self._num_screens, 16
        obj["x"] = max(0.0, min(round(x * cols) / cols, 1.0 - w))
        obj["y"] = max(0.0, min(round(y * rows) / rows, 1.0 - h))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = False
            self.unsetCursor()
            return
        if self._dragging_id:
            obj = self._find_object(self._dragging_id)
            if obj is not None:
                self.object_moved.emit(
                    self._dragging_id,
                    float(obj.get("x", 0.0)),
                    float(obj.get("y", 0.0)),
                )
        self._dragging_id = ""

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.12 if delta > 0 else 1.0 / 1.12
        self._zoom_at(event.pos(), factor)

    def _draw_board(self, p: QPainter):
        W, H = self.width(), self.height()
        cols, rows = 16 * self._num_screens, 16
        tile_w = max(4.0, self._content_width() / cols)
        tile_h = max(4.0, self._content_height() / rows)

        # Detect active theme from objects
        theme = "default"
        for obj in self._objects:
            candidate = str(obj.get("scene_type") or "").lower()
            if candidate and candidate != "default":
                theme = candidate
                break

        # --- Draw the themed background first ---
        if theme == "dungeon":
            self._draw_bg_dungeon(p, W, H)
        elif theme == "desert":
            self._draw_bg_desert(p, W, H)
        else:  # grassland / default
            self._draw_bg_grassland(p, W, H)

        if not self.show_grid:
            return

        # --- Semi-transparent checkerboard over the background ---
        if theme == "dungeon":
            a = QColor(0, 0, 0, 30)
            b = QColor(0, 0, 0, 50)
            grid_color = QColor(255, 255, 255, 18)
        elif theme == "desert":
            a = QColor(0, 0, 0, 20)
            b = QColor(0, 0, 0, 40)
            grid_color = QColor(255, 255, 255, 22)
        else:  # grassland / default
            a = QColor(0, 0, 0, 15)
            b = QColor(0, 0, 0, 35)
            grid_color = QColor(255, 255, 255, 25)

        start_col = int(max(0, (-self._pan_x) // tile_w))
        end_col = int(min(cols, ((self.width() - self._pan_x) // tile_w) + 2))
        start_row = int(max(0, (-self._pan_y) // tile_h))
        end_row = int(min(rows, ((self.height() - self._pan_y) // tile_h) + 2))

        for r in range(start_row, end_row):
            for c in range(start_col, end_col):
                x = int(self._pan_x + c * tile_w)
                y = int(self._pan_y + r * tile_h)
                w = int(self._pan_x + (c + 1) * tile_w) - x
                h = int(self._pan_y + (r + 1) * tile_h) - y
                p.fillRect(x, y, w, h, a if ((c + r) % 2 == 0) else b)

        p.setPen(QPen(grid_color, 1))
        for c in range(start_col, end_col + 1):
            x = int(self._pan_x + c * tile_w)
            p.drawLine(x, 0, x, self.height())
        for r in range(start_row, end_row + 1):
            y = int(self._pan_y + r * tile_h)
            p.drawLine(0, y, self.width(), y)

    # ------------------------------------------------------------------
    # Theme backgrounds — Super Mario Bros inspired
    # ------------------------------------------------------------------

    def _draw_bg_grassland(self, p: QPainter, W: int, H: int):
        """SMB World 1-1 style: blue sky gradient, fluffy clouds, green hills."""
        import math

        # Sky gradient — bright Mario blue
        sky = QLinearGradient(0, 0, 0, H)
        sky.setColorAt(0.0, QColor("#5C94FC"))   # SMB bright sky blue top
        sky.setColorAt(0.55, QColor("#88B4FC"))   # lighter mid
        sky.setColorAt(1.0, QColor("#A8D0FC"))   # pale at horizon
        p.fillRect(0, 0, W, H, QBrush(sky))

        # --- Clouds (two layers for parallax feel) ---
        p.setRenderHint(QPainter.Antialiasing, True)
        cloud_color = QColor(255, 255, 255, 200)
        cloud_highlight = QColor(255, 255, 255, 240)

        # Large fluffy clouds
        cloud_positions = [
            (0.08, 0.10, 1.0),
            (0.35, 0.06, 1.3),
            (0.62, 0.12, 0.9),
            (0.88, 0.05, 1.1),
        ]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            screen_w = W / self._num_screens
            for (rx, ry, scale) in cloud_positions:
                cx = offset_x + rx * screen_w
                cy = ry * H
                cw = 0.14 * screen_w * scale
                ch = cw * 0.45

                # Cloud body — three overlapping ellipses
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(cloud_color))
                p.drawEllipse(QRectF(cx, cy + ch * 0.2, cw, ch * 0.7))
                p.drawEllipse(QRectF(cx + cw * 0.15, cy, cw * 0.5, ch * 0.8))
                p.drawEllipse(QRectF(cx + cw * 0.4, cy + ch * 0.1, cw * 0.5, ch * 0.75))
                # Highlight
                p.setBrush(QBrush(cloud_highlight))
                p.drawEllipse(QRectF(cx + cw * 0.2, cy + ch * 0.05, cw * 0.35, ch * 0.5))

        # --- Background hills (far layer — light green) ---
        far_hill_color = QColor("#4AA52E")
        far_hill_color.setAlpha(160)
        hill_far = [
            (0.0, 0.6, 0.30, 0.25),
            (0.25, 0.65, 0.35, 0.20),
            (0.55, 0.60, 0.28, 0.28),
            (0.80, 0.63, 0.32, 0.22),
        ]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for (rx, ry, rw, rh) in hill_far:
                hx = offset_x + rx * sw
                hy = ry * H
                hw = rw * sw
                hh = rh * H
                path = QPainterPath()
                path.moveTo(hx, hy + hh)
                path.quadTo(hx + hw * 0.5, hy, hx + hw, hy + hh)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(far_hill_color))
                p.drawPath(path)

        # --- Foreground hills (near layer — darker green) ---
        near_hill_color = QColor("#3B8C27")
        near_hill_color.setAlpha(180)
        hill_near = [
            (-0.05, 0.72, 0.25, 0.20),
            (0.20, 0.75, 0.20, 0.15),
            (0.45, 0.70, 0.30, 0.22),
            (0.75, 0.73, 0.22, 0.18),
        ]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for (rx, ry, rw, rh) in hill_near:
                hx = offset_x + rx * sw
                hy = ry * H
                hw = rw * sw
                hh = rh * H
                path = QPainterPath()
                path.moveTo(hx, hy + hh)
                path.quadTo(hx + hw * 0.5, hy, hx + hw, hy + hh)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(near_hill_color))
                p.drawPath(path)

        # --- Small bushes at bottom ---
        bush_color = QColor("#2D7A1E")
        bush_color.setAlpha(140)
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for bx_frac in [0.10, 0.40, 0.70, 0.95]:
                bx = offset_x + bx_frac * sw
                by = H * 0.88
                bw = sw * 0.06
                bh = H * 0.05
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(bush_color))
                p.drawEllipse(QRectF(bx, by, bw, bh))
                p.drawEllipse(QRectF(bx + bw * 0.3, by - bh * 0.3, bw * 0.7, bh * 0.8))

        p.setRenderHint(QPainter.Antialiasing, False)

    def _draw_bg_dungeon(self, p: QPainter, W: int, H: int):
        """SMB Underground / Castle style: dark stone, torch glow, stalactites."""
        import math

        # Very dark gradient background
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0.0, QColor("#0a0a12"))
        bg.setColorAt(0.4, QColor("#10101c"))
        bg.setColorAt(1.0, QColor("#18182a"))
        p.fillRect(0, 0, W, H, QBrush(bg))

        # --- Brick pattern on walls (subtle) ---
        brick_color = QColor("#1e1e30")
        mortar_color = QColor("#14141e")
        brick_h = max(8, int(H / 24))
        brick_w = max(16, int(W / (self._num_screens * 12)))
        p.setPen(QPen(mortar_color, 1))
        for row_idx in range(0, H, brick_h):
            offset = (brick_w // 2) if ((row_idx // brick_h) % 2 == 1) else 0
            for col_x in range(-brick_w + offset, W + brick_w, brick_w):
                p.fillRect(col_x + 1, row_idx + 1, brick_w - 2, brick_h - 2, brick_color)

        # --- Stalactites hanging from ceiling ---
        p.setRenderHint(QPainter.Antialiasing, True)
        stalactite_color = QColor("#252540")
        stalactite_positions = [0.08, 0.18, 0.32, 0.45, 0.58, 0.72, 0.85, 0.93]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for i, frac in enumerate(stalactite_positions):
                sx = offset_x + frac * sw
                sh = H * (0.06 + 0.04 * math.sin(i * 2.3))
                sw_tip = sw * 0.02
                path = QPainterPath()
                path.moveTo(sx - sw_tip, 0)
                path.lineTo(sx + sw_tip, 0)
                path.lineTo(sx, sh)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(stalactite_color))
                p.drawPath(path)

        # --- Torch glow spots (warm orange circles) ---
        torch_positions = [0.25, 0.75]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for frac in torch_positions:
                tx = offset_x + frac * sw
                ty = H * 0.35
                glow_r = sw * 0.12

                # Outer glow
                glow = QColor(255, 140, 40, 20)
                for ring in range(6, 0, -1):
                    r = glow_r * (ring / 6.0)
                    glow.setAlpha(int(12 * (7 - ring)))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(glow))
                    p.drawEllipse(QRectF(tx - r, ty - r, r * 2, r * 2))

                # Torch flame (tiny bright spot)
                flame = QColor(255, 200, 80, 180)
                p.setBrush(QBrush(flame))
                p.drawEllipse(QRectF(tx - 3, ty - 4, 6, 8))

        # --- Dripping water highlights ---
        drip_color = QColor(100, 140, 255, 40)
        drip_x_fracs = [0.15, 0.42, 0.68, 0.90]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for i, frac in enumerate(drip_x_fracs):
                dx = offset_x + frac * sw
                dy = H * (0.1 + 0.05 * math.sin(i * 1.7))
                p.setPen(QPen(drip_color, 2))
                p.drawLine(int(dx), int(dy), int(dx), int(dy + H * 0.08))

        p.setRenderHint(QPainter.Antialiasing, False)

    def _draw_bg_desert(self, p: QPainter, W: int, H: int):
        """SMB Desert World style: warm sky, sun, layered sand dunes."""
        import math

        # Warm sky gradient
        sky = QLinearGradient(0, 0, 0, H)
        sky.setColorAt(0.0, QColor("#E8A840"))   # amber top
        sky.setColorAt(0.3, QColor("#F0C060"))   # golden
        sky.setColorAt(0.6, QColor("#F8D888"))   # pale sand
        sky.setColorAt(1.0, QColor("#E8C070"))   # warm bottom
        p.fillRect(0, 0, W, H, QBrush(sky))

        p.setRenderHint(QPainter.Antialiasing, True)

        # --- Sun ---
        sun_x = W * 0.82
        sun_y = H * 0.12
        sun_r = min(W, H) * 0.08

        # Sun glow rings
        for ring in range(8, 0, -1):
            r = sun_r * (1.0 + ring * 0.4)
            glow = QColor(255, 220, 100, int(10 * (9 - ring)))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(sun_x - r, sun_y - r, r * 2, r * 2))

        # Sun disc
        p.setBrush(QBrush(QColor(255, 240, 180, 220)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(sun_x - sun_r, sun_y - sun_r, sun_r * 2, sun_r * 2))

        # --- Far sand dunes (light) ---
        dune_far_color = QColor("#D4A855")
        dune_far_color.setAlpha(140)
        dune_far = [
            (0.0, 0.50, 0.35, 0.18),
            (0.30, 0.48, 0.30, 0.20),
            (0.55, 0.52, 0.28, 0.16),
            (0.80, 0.49, 0.30, 0.19),
        ]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for (rx, ry, rw, rh) in dune_far:
                dx = offset_x + rx * sw
                dy = ry * H
                dw = rw * sw
                dh = rh * H
                path = QPainterPath()
                path.moveTo(dx, dy + dh)
                path.quadTo(dx + dw * 0.5, dy, dx + dw, dy + dh)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(dune_far_color))
                p.drawPath(path)

        # --- Near sand dunes (darker, taller) ---
        dune_near_color = QColor("#C09040")
        dune_near_color.setAlpha(160)
        dune_near = [
            (-0.05, 0.62, 0.28, 0.22),
            (0.22, 0.60, 0.32, 0.25),
            (0.50, 0.64, 0.25, 0.20),
            (0.75, 0.61, 0.30, 0.23),
        ]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for (rx, ry, rw, rh) in dune_near:
                dx = offset_x + rx * sw
                dy = ry * H
                dw = rw * sw
                dh = rh * H
                path = QPainterPath()
                path.moveTo(dx, dy + dh)
                path.quadTo(dx + dw * 0.35, dy, dx + dw, dy + dh)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(dune_near_color))
                p.drawPath(path)

        # --- Small cacti silhouettes ---
        cactus_color = QColor("#6B8A3D")
        cactus_color.setAlpha(100)
        cactus_fracs = [0.15, 0.45, 0.78]
        for screen in range(self._num_screens):
            offset_x = screen * (W / self._num_screens)
            sw = W / self._num_screens
            for i, frac in enumerate(cactus_fracs):
                cx = offset_x + frac * sw
                cy = H * 0.72
                cw = sw * 0.015
                ch = H * (0.06 + 0.02 * math.sin(i * 1.5))
                # Trunk
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(cactus_color))
                p.drawRect(QRectF(cx - cw / 2, cy - ch, cw, ch))
                # Left arm
                arm_y = cy - ch * 0.6
                p.drawRect(QRectF(cx - cw * 2, arm_y, cw * 1.5, cw))
                p.drawRect(QRectF(cx - cw * 2, arm_y - cw * 2, cw, cw * 2))
                # Right arm
                arm_y2 = cy - ch * 0.35
                p.drawRect(QRectF(cx + cw * 0.5, arm_y2, cw * 1.5, cw))
                p.drawRect(QRectF(cx + cw * 1.5, arm_y2 - cw * 1.5, cw, cw * 1.5))

        # --- Heat shimmer lines ---
        shimmer = QColor(255, 255, 255, 15)
        p.setPen(QPen(shimmer, 1))
        for y_frac in [0.78, 0.82, 0.86, 0.90]:
            y = int(y_frac * H)
            for x_seg in range(0, W, 20):
                wave = int(2 * math.sin(x_seg * 0.15 + y_frac * 30))
                p.drawLine(x_seg, y + wave, x_seg + 10, y - wave)

        p.setRenderHint(QPainter.Antialiasing, False)

    def _draw_empty_state(self, p: QPainter):
        inset = 40
        rect = self.rect().adjusted(inset, inset, -inset, -inset)
        p.setPen(QPen(QColor(BORDER_LIGHT), 2, Qt.DashLine))
        p.drawRect(rect)
        p.setPen(QColor(TEXT_BRIGHT))
        f1 = QFont(FONT_FAMILY, 11)
        f1.setBold(True)
        p.setFont(f1)
        center_y = self.height() // 2 - 16
        p.drawText(QRect(0, center_y, self.width(), 22), Qt.AlignCenter, "Stage empty")
        p.setPen(QColor(TEXT_MUTED))
        p.setFont(QFont(FONT_FAMILY, 9))
        p.drawText(
            QRect(0, center_y + 24, self.width(), 20),
            Qt.AlignCenter,
            "Describe a scene above and click Generate Scene",
        )

    def _draw_object(self, p: QPainter, obj: dict, index: int):
        rect = self._object_rect(obj)
        color = self._object_color(obj, index)
        p.setPen(QPen(QColor(BG_DARK), 1))
        p.drawRect(rect.adjusted(1, 1, 1, 1))
        p.setOpacity(0.8)
        p.fillRect(rect, color)
        p.setOpacity(1.0)
        border = QColor(ACCENT) if str(obj.get("id", "")) == self._selected_id else color.lighter(130)
        p.setPen(QPen(border, 2))
        p.drawRect(rect)
        label = str(obj.get("label") or obj.get("name") or "Object")
        p.setFont(QFont(FONT_FAMILY, FONT_SIZE))
        fm = QFontMetrics(p.font())
        label = fm.elidedText(label, Qt.ElideRight, max(8, rect.width() - 8))
        p.setPen(QColor(TEXT_BRIGHT))
        p.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, label)

    def _draw_preview_object(self, p: QPainter, obj: dict, index: int):
        rect = self._object_rect(obj)
        color = self._object_color(obj, index)
        selected = str(obj.get("id", "")) == self._selected_id
        if not bool(obj.get("visible", True)):
            p.setOpacity(0.35)

        pixmap = self._sprite_pixmaps.get(str(obj.get("id", "")))
        if pixmap and not pixmap.isNull():
            target = rect
            scaled = pixmap.scaled(
                target.size(),
                Qt.IgnoreAspectRatio,
                Qt.FastTransformation,
            )
            p.drawPixmap(target.x(), target.y(), scaled)
        else:
            p.setOpacity(0.75 if bool(obj.get("visible", True)) else 0.35)
            p.fillRect(rect, color)
            p.setOpacity(1.0)
            self._draw_fallback_mark(p, rect, obj)

        p.setOpacity(1.0)
        if selected:
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(rect)

    def _draw_fallback_mark(self, p: QPainter, rect: QRect, obj: dict):
        label = str(obj.get("label") or obj.get("name") or "?").strip()
        mark = label[:1].upper() if label else "?"
        font = QFont(FONT_FAMILY, max(9, min(18, rect.height() // 3)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(TEXT_BRIGHT))
        p.drawText(rect, Qt.AlignCenter, mark)

    def _object_rect(self, obj: dict) -> QRect:
        content_w = self._content_width()
        content_h = self._content_height()
        scale = max(0.01, float(obj.get("scale", 1.0) or 1.0))
        x = int(float(obj.get("x", 0.0)) * content_w + self._pan_x)
        y = int(float(obj.get("y", 0.0)) * content_h + self._pan_y)
        w = max(2, int(float(obj.get("w", 0.12)) * content_w * scale))
        h = max(2, int(float(obj.get("h", 0.12)) * content_h * scale))
        return QRect(x, y, w, h)

    def _object_color(self, obj: dict, index: int) -> QColor:
        raw = obj.get("color")
        color = QColor(str(raw)) if raw else QColor()
        if not color.isValid():
            name = str(obj.get("name") or obj.get("label") or "").lower()
            theme = str(obj.get("scene_type") or "default").lower()
            palettes = {
                "dungeon": {
                    "solid": "#2F4F4F", "loot": "#FFD700", "enemy": "#8B0000",
                    "climbable": "#4A3B32", "player": "#00FFFF", "default": "#5F9EA0",
                },
                "desert": {
                    "solid": "#D2B48C", "loot": "#9370DB", "enemy": "#D35400",
                    "climbable": "#CD853F", "player": "#E0FFFF", "default": "#F4A460",
                },
                "default": {
                    "solid": "#8B5A2B", "loot": "#FFD700", "enemy": "#FF4500",
                    "climbable": "#32CD32", "player": "#1E90FF",
                },
            }
            palette = palettes.get(theme, palettes["default"])
            for key, value in palette.items():
                if key != "default" and key in name:
                    color = QColor(value)
                    break
            if not color.isValid():
                color = QColor(palette.get("default") or self._palette[index % len(self._palette)])
        color.setAlpha(204)
        return color

    def _find_object(self, object_id: str) -> dict | None:
        for obj in self._objects:
            if str(obj.get("id", "")) == object_id:
                return obj
        return None

    def _content_width(self) -> float:
        return max(1.0, float(self.width()) * self._view_zoom)

    def _content_height(self) -> float:
        return max(1.0, float(self.height()) * self._view_zoom)

    def _screen_to_stage(self, x: float, y: float) -> QPointF:
        return QPointF(
            max(0.0, min(1.0, (float(x) - self._pan_x) / self._content_width())),
            max(0.0, min(1.0, (float(y) - self._pan_y) / self._content_height())),
        )

    def _zoom_at(self, screen_pos, factor: float) -> None:
        old_zoom = self._view_zoom
        new_zoom = max(self._min_zoom, min(self._max_zoom, old_zoom * float(factor)))
        if abs(new_zoom - old_zoom) < 1e-9:
            return
        sx = float(screen_pos.x())
        sy = float(screen_pos.y())
        nx = (sx - self._pan_x) / max(1.0, self.width() * old_zoom)
        ny = (sy - self._pan_y) / max(1.0, self.height() * old_zoom)
        self._view_zoom = new_zoom
        self._pan_x = sx - nx * self.width() * new_zoom
        self._pan_y = sy - ny * self.height() * new_zoom
        self._clamp_pan()
        self.update()

    def _clamp_pan(self) -> None:
        content_w = self._content_width()
        content_h = self._content_height()
        if content_w <= self.width():
            self._pan_x = (self.width() - content_w) / 2.0
        else:
            min_x = self.width() - content_w
            self._pan_x = max(min_x, min(0.0, self._pan_x))
        if content_h <= self.height():
            self._pan_y = (self.height() - content_h) / 2.0
        else:
            min_y = self.height() - content_h
            self._pan_y = max(min_y, min(0.0, self._pan_y))

    def resizeEvent(self, event):
        self._clamp_pan()
        super().resizeEvent(event)

    @staticmethod
    def _clamp_float(value, lo: float, hi: float, default: float) -> float:
        try:
            val = float(value)
        except (TypeError, ValueError):
            val = default
        return max(lo, min(val, hi))
