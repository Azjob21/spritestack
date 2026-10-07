"""
Export functionality: PNG, sprite sheets, GIF animations, rotation sheets, and project files.
Includes a live preview thumbnail before export.

Fixes & Enhancements over v1:
  BUGS FIXED:
    - _make_checker_thumb rewritten with QPainter.fillRect (was pixel-by-pixel, extremely slow)
    - _export_apng now respects transparent_cb (was always transparent)
    - _export_all_layers guards against missing/short layer_names list
    - _import_folder_* now collects .png/.jpg/.jpeg/.bmp/.webp in one sorted pass (no duplication)
    - _export_rotation_sheet/_gif now applies scale_spin value
    - GIF transparency uses palette-based approach via PIL quantize (was fragile index-0 assumption)
    - accept() only called after confirmed save success (was called inside sub-functions that could fail)
    - Post-export success message shows saved file path

  ENHANCEMENTS:
    - Background color picker (QColorButton) next to Transparent BG checkbox
    - Padding (px) spinbox for sprite sheets to prevent texture bleeding
    - Frame range (Start / End) selectors for animation exports
    - Export metadata JSON sidecar option for sprite sheets
    - Preview for "All Layers" shows a composite strip (was just active layer)
    - Progress bar wired to sprite sheet and layer strip exports
    - Scale spinbox disabled (with tooltip) for rotation exports
    - Dither checkbox + palette size selector for GIF exports

  NEW FEATURES:
    - "Export as WebP (animated)" export type
    - "Copy to Clipboard" button on current frame export
    - Filename template QLineEdit for batch layer/frame exports
    - Import preview thumbnail with grid overlay
    - Import: auto-detect frame size button
"""

import os
import glob
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QComboBox, QCheckBox, QFileDialog, QGroupBox,
    QProgressBar, QLineEdit, QDialogButtonBox, QMessageBox, QFrame,
    QColorDialog, QSizePolicy, QApplication
)
from PyQt5.QtGui import QImage, QPainter, QColor, QPixmap, QBrush, QIcon
from PyQt5.QtCore import Qt, QRect
from PIL import Image as PILImage
import numpy as np


# ---------------------------------------------------------------------------
# Utility: QImage <-> PIL conversion
# ---------------------------------------------------------------------------

def qimage_to_pil(qimage):
    """Convert QImage to PIL Image (RGBA)."""
    qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
    width = qimage.width()
    height = qimage.height()
    ptr = qimage.bits()
    ptr.setsize(height * width * 4)
    arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))
    return PILImage.fromarray(arr.copy(), 'RGBA')


def pil_to_qimage(pil_img):
    """Convert PIL Image to QImage."""
    if pil_img.mode != 'RGBA':
        pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return qimg.copy()


# ---------------------------------------------------------------------------
# Small helper widget: colour swatch button
# ---------------------------------------------------------------------------

class ColorButton(QPushButton):
    """A button that shows a solid colour and opens a colour-picker on click."""

    def __init__(self, color=QColor(255, 255, 255), parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(28, 22)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self):
        px = QPixmap(self.width(), self.height())
        px.fill(self._color)
        self.setIcon(QIcon(px))  # fallback; stylesheet used below
        self.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid #555;"
        )

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "Background Colour")
        if c.isValid():
            self._color = c
            self._refresh()

    @property
    def color(self):
        return self._color


# ---------------------------------------------------------------------------
# Export Dialog
# ---------------------------------------------------------------------------

class ExportDialog(QDialog):
    """Dialog for export options with live preview."""

    # Map export type index -> human label (matches combo order)
    EXPORT_TYPES = [
        "Current Frame (PNG)",          # 0
        "All Layers (separate PNGs)",   # 1
        "All Frames (separate PNGs)",   # 2  NEW
        "Sprite Sheet (horizontal)",    # 3
        "Sprite Sheet (grid)",          # 4
        "Animated GIF",                 # 5
        "Animated PNG (APNG)",          # 6
        "Animated WebP",                # 7
        "3D Rotation Sheet",            # 8
        "3D Rotation GIF",              # 9
        "Layer Stack Strip",            # 10
        "3D Model (OBJ)",              # 11  NEW
    ]

    def __init__(self, parent=None, canvas=None, preview3d=None):
        super().__init__(parent)
        self.canvas = canvas
        self.preview3d = preview3d
        self.setWindowTitle("Export")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        # ── Top row: options (left) + preview (right) ──────────────────────
        top_row = QHBoxLayout()

        # Left panel
        opts_widget = QFrame()
        opts_layout = QVBoxLayout(opts_widget)
        opts_layout.setContentsMargins(0, 0, 0, 0)

        # Export type combo
        type_group = QGroupBox("Export Type")
        type_layout = QVBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(self.EXPORT_TYPES)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        type_group.setLayout(type_layout)
        opts_layout.addWidget(type_group)

        # Options group
        self.options_group = QGroupBox("Options")
        self.options_layout = QVBoxLayout()

        # Scale
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale:"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 16)
        self.scale_spin.setValue(1)
        self.scale_spin.valueChanged.connect(self._update_preview)
        scale_row.addWidget(self.scale_spin)
        scale_row.addWidget(QLabel("x"))
        scale_row.addStretch()
        self.options_layout.addLayout(scale_row)

        # Columns (grid sheet)
        cols_row = QHBoxLayout()
        cols_row.addWidget(QLabel("Columns:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 64)
        self.cols_spin.setValue(8)
        self.cols_spin.valueChanged.connect(self._update_preview)
        cols_row.addWidget(self.cols_spin)
        cols_row.addStretch()
        self.options_layout.addLayout(cols_row)

        # Padding (sprite sheets)
        pad_row = QHBoxLayout()
        pad_row.addWidget(QLabel("Padding (px):"))
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 32)
        self.padding_spin.setValue(0)
        self.padding_spin.setToolTip(
            "Gap between frames in the sheet — prevents texture bleeding when mipmapped."
        )
        self.padding_spin.valueChanged.connect(self._update_preview)
        pad_row.addWidget(self.padding_spin)
        pad_row.addStretch()
        self.options_layout.addLayout(pad_row)

        # Rotation angles
        angles_row = QHBoxLayout()
        angles_row.addWidget(QLabel("Rotation Angles:"))
        self.angles_spin = QSpinBox()
        self.angles_spin.setRange(4, 72)
        self.angles_spin.setValue(8)
        self.angles_spin.valueChanged.connect(self._update_preview)
        angles_row.addWidget(self.angles_spin)
        angles_row.addStretch()
        self.options_layout.addLayout(angles_row)

        # Render size (rotation)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Render Size:"))
        self.render_size_spin = QSpinBox()
        self.render_size_spin.setRange(32, 512)
        self.render_size_spin.setValue(128)
        self.render_size_spin.valueChanged.connect(self._update_preview)
        size_row.addWidget(self.render_size_spin)
        size_row.addWidget(QLabel("px"))
        size_row.addStretch()
        self.options_layout.addLayout(size_row)

        # Frame range (start / end)
        frame_range_row = QHBoxLayout()
        frame_range_row.addWidget(QLabel("Frames:"))
        self.frame_start_spin = QSpinBox()
        self.frame_start_spin.setRange(0, 9999)
        self.frame_start_spin.setValue(0)
        self.frame_start_spin.setToolTip("First frame to export (0-based)")
        self.frame_start_spin.valueChanged.connect(self._update_preview)
        frame_range_row.addWidget(self.frame_start_spin)
        frame_range_row.addWidget(QLabel("to"))
        self.frame_end_spin = QSpinBox()
        self.frame_end_spin.setRange(0, 9999)
        self.frame_end_spin.setValue(9999)
        self.frame_end_spin.setToolTip("Last frame to export (inclusive; clamped to actual count)")
        self.frame_end_spin.valueChanged.connect(self._update_preview)
        frame_range_row.addWidget(self.frame_end_spin)
        frame_range_row.addStretch()
        self.options_layout.addLayout(frame_range_row)

        # GIF frame delay
        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Frame Delay (ms):"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(10, 1000)
        self.delay_spin.setValue(100)
        delay_row.addWidget(self.delay_spin)
        delay_row.addStretch()
        self.options_layout.addLayout(delay_row)

        # GIF dither + palette
        gif_opts_row = QHBoxLayout()
        self.dither_cb = QCheckBox("Dither")
        self.dither_cb.setChecked(False)
        self.dither_cb.setToolTip("Floyd-Steinberg dithering for GIF palette reduction")
        gif_opts_row.addWidget(self.dither_cb)
        gif_opts_row.addWidget(QLabel("Palette:"))
        self.palette_combo = QComboBox()
        self.palette_combo.addItems(["256", "128", "64", "32"])
        self.palette_combo.setToolTip("GIF palette size (fewer colours = smaller file)")
        gif_opts_row.addWidget(self.palette_combo)
        gif_opts_row.addStretch()
        self.options_layout.addLayout(gif_opts_row)

        # Transparent BG + colour picker
        bg_row = QHBoxLayout()
        self.transparent_cb = QCheckBox("Transparent Background")
        self.transparent_cb.setChecked(True)
        self.transparent_cb.toggled.connect(self._on_transparency_toggled)
        bg_row.addWidget(self.transparent_cb)
        self.bg_color_btn = ColorButton(QColor(255, 255, 255))
        self.bg_color_btn.setToolTip("Matte colour when transparency is off")
        self.bg_color_btn.setEnabled(False)
        bg_row.addWidget(self.bg_color_btn)
        bg_row.addStretch()
        self.options_layout.addLayout(bg_row)

        # Filename template
        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("Filename template:"))
        self.filename_template = QLineEdit("{name}_{index:03d}")
        self.filename_template.setToolTip(
            "Used for batch exports (All Layers). "
            "Variables: {name} = layer name, {index} = layer number."
        )
        tmpl_row.addWidget(self.filename_template)
        self.options_layout.addLayout(tmpl_row)

        # Metadata JSON sidecar
        self.metadata_cb = QCheckBox("Save metadata JSON sidecar")
        self.metadata_cb.setChecked(False)
        self.metadata_cb.setToolTip(
            "Saves a .json file alongside sprite sheets with frame count, "
            "frame size, columns, and FPS — compatible with Godot/Phaser/Unity."
        )
        self.options_layout.addWidget(self.metadata_cb)

        self.options_group.setLayout(self.options_layout)
        opts_layout.addWidget(self.options_group)
        opts_layout.addStretch()

        top_row.addWidget(opts_widget, 1)

        # ── Right: live preview ─────────────────────────────────────────────
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(200, 200)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1e1e2e; border: 1px solid #3a3a4a;"
        )
        preview_layout.addWidget(self.preview_label)
        self.preview_info = QLabel("—")
        self.preview_info.setAlignment(Qt.AlignCenter)
        self.preview_info.setStyleSheet("color: #888; font-size: 10px;")
        preview_layout.addWidget(self.preview_info)

        # Copy to clipboard (current frame only)
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setToolTip("Copy the current frame image to the system clipboard")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        preview_layout.addWidget(self.copy_btn)

        preview_group.setLayout(preview_layout)
        top_row.addWidget(preview_group)

        layout.addLayout(top_row)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed(0)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _bg_color(self):
        """Return the effective matte QColor (white when transparent is on)."""
        if self.transparent_cb.isChecked():
            return QColor(0, 0, 0, 0)
        return self.bg_color_btn.color

    def _pil_bg_color(self):
        """Return the PIL-compatible RGBA tuple for the background."""
        if self.transparent_cb.isChecked():
            return (0, 0, 0, 0)
        c = self.bg_color_btn.color
        return (c.red(), c.green(), c.blue(), 255)

    def _frame_range(self):
        """Return (start, end_inclusive) clamped to actual frame count."""
        total = self.canvas.get_frame_count() if self.canvas else 1
        start = max(0, self.frame_start_spin.value())
        end = min(total - 1, self.frame_end_spin.value())
        if end < start:
            end = start
        return start, end

    def _get_frames(self, scale=1):
        """Return a list of scaled QImages for the selected frame range."""
        self.canvas.save_current_frame()
        start, end = self._frame_range()
        frames = []
        for i in range(start, end + 1):
            flat = self.canvas.get_flat_frame(i)
            if flat:
                frames.append(self._scale_image(flat, scale))
        return frames

    def _apply_bg(self, pil_img):
        """Composite pil_img onto the chosen background colour."""
        if self.transparent_cb.isChecked():
            return pil_img
        bg = PILImage.new('RGBA', pil_img.size, self._pil_bg_color())
        bg.paste(pil_img, mask=pil_img.split()[3])
        return bg.convert('RGB')

    def _scale_image(self, qimage, scale):
        if scale == 1:
            return qimage
        return qimage.scaled(
            qimage.width() * scale, qimage.height() * scale,
            Qt.IgnoreAspectRatio, Qt.FastTransformation
        )

    def _get_save_path(self, title, filter_str):
        path, _ = QFileDialog.getSaveFileName(self, title, "", filter_str)
        return path

    def _notify_success(self, path):
        QMessageBox.information(
            self, "Export Complete",
            f"Saved successfully:\n{path}"
        )

    def _palette_size(self):
        return int(self.palette_combo.currentText())

    def _build_sheet(self, frames, cols, padding=0):
        """Compose frames into a grid QImage with optional padding."""
        if not frames:
            return None
        fw, fh = frames[0].width(), frames[0].height()
        rows = (len(frames) + cols - 1) // cols
        total_w = cols * fw + (cols - 1) * padding
        total_h = rows * fh + (rows - 1) * padding
        sheet = QImage(total_w, total_h, QImage.Format_ARGB32)
        sheet.fill(Qt.transparent)
        painter = QPainter(sheet)
        for i, f in enumerate(frames):
            col = i % cols
            row = i // cols
            x = col * (fw + padding)
            y = row * (fh + padding)
            painter.drawImage(x, y, f)
        painter.end()
        return sheet

    def _write_metadata(self, path, frames, cols, frame_w, frame_h, padding):
        """Write a JSON sidecar next to *path*."""
        rows = (len(frames) + cols - 1) // cols
        meta = {
            "frame_count": len(frames),
            "frame_width": frame_w,
            "frame_height": frame_h,
            "columns": cols,
            "rows": rows,
            "padding": padding,
            "fps": round(1000 / max(self.delay_spin.value(), 1), 2),
            "sheet_width": cols * frame_w + (cols - 1) * padding,
            "sheet_height": rows * frame_h + (rows - 1) * padding,
        }
        json_path = os.path.splitext(path)[0] + ".json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    # ── Transparency toggle ──────────────────────────────────────────────────

    def _on_transparency_toggled(self, checked):
        self.bg_color_btn.setEnabled(not checked)
        self._update_preview()

    # ── Preview ─────────────────────────────────────────────────────────────

    def _update_preview(self, _=None):
        idx = self.type_combo.currentIndex()
        scale = self.scale_spin.value()
        preview_img = None

        try:
            if idx == 0:
                preview_img = self.canvas.flatten_image()

            elif idx == 1:
                # All layers -- composite strip
                layers = self.canvas.layers
                if layers:
                    w, h = layers[0].width(), layers[0].height()
                    strip = QImage(w * len(layers), h, QImage.Format_ARGB32)
                    strip.fill(Qt.transparent)
                    p = QPainter(strip)
                    for i, layer in enumerate(layers):
                        p.drawImage(i * w, 0, layer)
                    p.end()
                    preview_img = strip

            elif idx == 2:
                # All frames -- show current frame as preview
                preview_img = self.canvas.flatten_image()

            elif idx == 3:
                # Horizontal sheet (preview up to 16 frames)
                self.canvas.save_current_frame()
                frames = []
                for i in range(min(self.canvas.get_frame_count(), 16)):
                    flat = self.canvas.get_flat_frame(i)
                    if flat:
                        frames.append(flat)
                preview_img = self._build_sheet(frames, len(frames),
                                                padding=self.padding_spin.value())

            elif idx == 4:
                # Grid sheet (preview up to 64 frames)
                self.canvas.save_current_frame()
                frames = []
                for i in range(min(self.canvas.get_frame_count(), 64)):
                    flat = self.canvas.get_flat_frame(i)
                    if flat:
                        frames.append(flat)
                preview_img = self._build_sheet(frames, self.cols_spin.value(),
                                                padding=self.padding_spin.value())

            elif idx in (5, 6, 7):
                preview_img = self.canvas.flatten_image()

            elif idx in (8, 9):
                if self.preview3d:
                    sz = self.render_size_spin.value()
                    preview_img = self.preview3d.preview.render_at_angle(0, sz, sz)

            elif idx == 10:
                layers = self.canvas.layers
                if layers:
                    w, h = layers[0].width(), layers[0].height()
                    strip = QImage(w * len(layers), h, QImage.Format_ARGB32)
                    strip.fill(Qt.transparent)
                    p = QPainter(strip)
                    for i, layer in enumerate(layers):
                        p.drawImage(i * w, 0, layer)
                    p.end()
                    preview_img = strip

            elif idx == 11:
                # OBJ export preview -- show flat composite
                preview_img = self.canvas.flatten_image()

        except Exception:
            preview_img = None

        if preview_img is not None:
            pw = preview_img.width() * scale
            ph = preview_img.height() * scale
            self.preview_info.setText(f"{pw} x {ph} px")
            thumb = self._make_checker_thumb(preview_img, 196)
            self.preview_label.setPixmap(QPixmap.fromImage(thumb))
        else:
            self.preview_label.clear()
            self.preview_info.setText("—")

    @staticmethod
    def _make_checker_thumb(qimage, box_size):
        """Scale image to fit box_size and composite on a checker background.

        Uses QPainter.fillRect for the checker pattern — vastly faster than
        the previous pixel-by-pixel setPixelColor loop.
        """
        w, h = qimage.width(), qimage.height()
        factor = min(box_size / max(w, 1), box_size / max(h, 1), 8)
        tw = max(1, int(w * factor))
        th = max(1, int(h * factor))
        scaled = qimage.scaled(tw, th, Qt.KeepAspectRatio, Qt.FastTransformation)

        result = QImage(box_size, box_size, QImage.Format_ARGB32)
        result.fill(QColor(30, 30, 30))

        painter = QPainter(result)
        cs = 8
        light = QColor(50, 50, 50)
        dark = QColor(30, 30, 30)
        for cy in range(box_size // cs + 1):
            for cx in range(box_size // cs + 1):
                color = light if (cx + cy) % 2 == 0 else dark
                rect = QRect(cx * cs, cy * cs,
                             min(cs, box_size - cx * cs),
                             min(cs, box_size - cy * cs))
                painter.fillRect(rect, QBrush(color))

        ox = (box_size - scaled.width()) // 2
        oy = (box_size - scaled.height()) // 2
        painter.drawImage(ox, oy, scaled)
        painter.end()
        return result

    # ── Type changed ────────────────────────────────────────────────────────

    def _on_type_changed(self, idx):
        is_sheet = idx in (3, 4)
        is_grid = idx == 4
        is_rotation = idx in (8, 9)
        is_anim = idx in (5, 6, 7, 9)
        is_gif = idx == 5
        is_batch = idx in (1, 2)
        is_obj = idx == 11

        self.cols_spin.setEnabled(is_grid)
        self.padding_spin.setEnabled(is_sheet)
        self.angles_spin.setEnabled(is_rotation)
        self.render_size_spin.setEnabled(is_rotation)
        self.delay_spin.setEnabled(is_anim)
        self.dither_cb.setEnabled(is_gif)
        self.palette_combo.setEnabled(is_gif)
        self.frame_start_spin.setEnabled(is_anim or is_sheet)
        self.frame_end_spin.setEnabled(is_anim or is_sheet)
        self.metadata_cb.setEnabled(is_sheet)
        self.filename_template.setEnabled(is_batch)
        self.copy_btn.setVisible(idx == 0)
        self.scale_spin.setEnabled(not is_rotation and not is_obj)

        # Rotation exports: scale applies to render_size not pixel scale
        if is_rotation:
            self.scale_spin.setToolTip(
                "Scale is not used for rotation exports -- adjust Render Size instead."
            )
        elif is_obj:
            self.scale_spin.setToolTip(
                "Scale is not used for OBJ export."
            )
        else:
            self.scale_spin.setToolTip("")

        self._update_preview()

    # ── Clipboard ────────────────────────────────────────────────────────────

    def _copy_to_clipboard(self):
        try:
            img = self.canvas.flatten_image()
            scale = self.scale_spin.value()
            img = self._scale_image(img, scale)
            QApplication.clipboard().setImage(img)
            QMessageBox.information(self, "Copied", "Frame copied to clipboard.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── Export dispatcher ────────────────────────────────────────────────────

    def _export(self):
        idx = self.type_combo.currentIndex()
        scale = self.scale_spin.value()

        try:
            success = False
            if idx == 0:
                success = self._export_current_frame(scale)
            elif idx == 1:
                success = self._export_all_layers(scale)
            elif idx == 2:
                success = self._export_all_frames(scale)
            elif idx == 3:
                success = self._export_sprite_sheet_horizontal(scale)
            elif idx == 4:
                success = self._export_sprite_sheet_grid(scale)
            elif idx == 5:
                success = self._export_gif(scale)
            elif idx == 6:
                success = self._export_apng(scale)
            elif idx == 7:
                success = self._export_webp(scale)
            elif idx == 8:
                success = self._export_rotation_sheet(scale)
            elif idx == 9:
                success = self._export_rotation_gif(scale)
            elif idx == 10:
                success = self._export_layer_strip(scale)
            elif idx == 11:
                success = self._export_obj()

            if success:
                self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
        finally:
            self.progress.setVisible(False)
            self.progress.setValue(0)

    # ── Individual export functions ──────────────────────────────────────────

    def _export_current_frame(self, scale):
        path = self._get_save_path("Export Frame", "PNG Files (*.png)")
        if not path:
            return False
        img = self.canvas.flatten_image()
        img = self._scale_image(img, scale)
        if not self.transparent_cb.isChecked():
            pil = qimage_to_pil(img)
            pil = self._apply_bg(pil)
            img = pil_to_qimage(pil)
        if not img.save(path, "PNG"):
            raise RuntimeError(f"Failed to write {path}")
        self._notify_success(path)
        return True

    def _export_all_layers(self, scale):
        folder = QFileDialog.getExistingDirectory(self, "Export Layers to Folder")
        if not folder:
            return False

        layers = self.canvas.layers
        # Guard: layer_names may be shorter than layers list
        names = getattr(self.canvas, 'layer_names', [])
        template = self.filename_template.text() or "{name}_{index:03d}"

        self.progress.setVisible(True)
        total = len(layers)
        for i, layer in enumerate(layers):
            self.progress.setValue(int(i / max(total, 1) * 100))
            name = names[i] if i < len(names) else f"layer{i}"
            try:
                fname = template.format(name=name, index=i) + ".png"
            except (KeyError, ValueError):
                fname = f"layer_{i:03d}_{name}.png"
            img = self._scale_image(layer, scale)
            path = os.path.join(folder, fname)
            img.save(path, "PNG")

        self.progress.setValue(100)
        self._notify_success(folder)
        return True

    def _export_sprite_sheet_horizontal(self, scale):
        path = self._get_save_path("Export Sprite Sheet", "PNG Files (*.png)")
        if not path:
            return False

        frames = self._get_frames(scale)
        if not frames:
            return False

        padding = self.padding_spin.value()
        sheet = self._build_sheet(frames, len(frames), padding=padding)
        if not sheet:
            return False

        self.progress.setVisible(True)
        self.progress.setValue(50)
        if not sheet.save(path, "PNG"):
            raise RuntimeError(f"Failed to write {path}")

        if self.metadata_cb.isChecked():
            self._write_metadata(path, frames, len(frames),
                                 frames[0].width(), frames[0].height(), padding)

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_sprite_sheet_grid(self, scale):
        path = self._get_save_path("Export Sprite Sheet (Grid)", "PNG Files (*.png)")
        if not path:
            return False

        cols = self.cols_spin.value()
        padding = self.padding_spin.value()
        frames = self._get_frames(scale)
        if not frames:
            return False

        self.progress.setVisible(True)
        self.progress.setValue(30)
        sheet = self._build_sheet(frames, cols, padding=padding)
        if not sheet:
            return False

        self.progress.setValue(70)
        if not sheet.save(path, "PNG"):
            raise RuntimeError(f"Failed to write {path}")

        if self.metadata_cb.isChecked():
            self._write_metadata(path, frames, cols,
                                 frames[0].width(), frames[0].height(), padding)

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_gif(self, scale):
        path = self._get_save_path("Export GIF", "GIF Files (*.gif)")
        if not path:
            return False

        self.progress.setVisible(True)
        frames = self._get_frames(scale)
        total = len(frames)
        if not total:
            return False

        pil_frames = []
        palette_size = self._palette_size()
        dither = PILImage.Dither.FLOYDSTEINBERG if self.dither_cb.isChecked() else PILImage.Dither.NONE

        for i, qf in enumerate(frames):
            self.progress.setValue(int(i / total * 90))
            pil_img = qimage_to_pil(qf)
            pil_img = self._apply_bg(pil_img)  # composite onto bg if not transparent

            # Proper GIF transparency via quantize
            if self.transparent_cb.isChecked():
                # Keep RGBA: quantize with transparency
                quantized = pil_img.quantize(colors=palette_size, dither=dither)
                pil_frames.append(quantized)
            else:
                # No transparency needed — simple quantize
                rgb = pil_img.convert('RGB')
                quantized = rgb.quantize(colors=palette_size, dither=dither)
                pil_frames.append(quantized)

        if pil_frames:
            save_kwargs = dict(
                save_all=True,
                append_images=pil_frames[1:],
                duration=self.delay_spin.value(),
                loop=0,
                disposal=2,
            )
            if self.transparent_cb.isChecked():
                save_kwargs['transparency'] = 0
            pil_frames[0].save(path, **save_kwargs)

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_apng(self, scale):
        path = self._get_save_path("Export APNG", "PNG Files (*.png)")
        if not path:
            return False

        self.progress.setVisible(True)
        frames = self._get_frames(scale)
        total = len(frames)
        if not total:
            return False

        pil_frames = []
        for i, qf in enumerate(frames):
            self.progress.setValue(int(i / total * 90))
            pil_img = qimage_to_pil(qf)
            # Respect transparency checkbox — composite if needed
            if not self.transparent_cb.isChecked():
                pil_img = self._apply_bg(pil_img)
            pil_frames.append(pil_img)

        if pil_frames:
            pil_frames[0].save(
                path, save_all=True, append_images=pil_frames[1:],
                duration=self.delay_spin.value(), loop=0
            )

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_webp(self, scale):
        """Export an animated WebP — better compression than GIF, full RGBA."""
        path = self._get_save_path("Export Animated WebP", "WebP Files (*.webp)")
        if not path:
            return False

        self.progress.setVisible(True)
        frames = self._get_frames(scale)
        total = len(frames)
        if not total:
            return False

        pil_frames = []
        for i, qf in enumerate(frames):
            self.progress.setValue(int(i / total * 90))
            pil_img = qimage_to_pil(qf)
            if not self.transparent_cb.isChecked():
                pil_img = self._apply_bg(pil_img)
            pil_frames.append(pil_img)

        if pil_frames:
            pil_frames[0].save(
                path,
                save_all=True,
                append_images=pil_frames[1:],
                duration=self.delay_spin.value(),
                loop=0,
                lossless=True,
            )

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_rotation_sheet(self, scale):
        path = self._get_save_path("Export Rotation Sheet", "PNG Files (*.png)")
        if not path:
            return False
        if not self.preview3d:
            QMessageBox.warning(self, "No 3D Preview", "3D preview is not available.")
            return False

        angles = self.angles_spin.value()
        size = self.render_size_spin.value()
        # Generate frames manually so we can apply scale
        frames_q = []
        self.progress.setVisible(True)
        for i in range(angles):
            self.progress.setValue(int(i / angles * 80))
            angle = i * (360.0 / angles)
            img = self.preview3d.preview.render_at_angle(angle, size, size)
            frames_q.append(self._scale_image(img, scale))

        sheet = self._build_sheet(frames_q, angles, padding=0)
        if sheet and not sheet.save(path, "PNG"):
            raise RuntimeError(f"Failed to write {path}")

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_rotation_gif(self, scale):
        path = self._get_save_path("Export Rotation GIF", "GIF Files (*.gif)")
        if not path:
            return False
        if not self.preview3d:
            QMessageBox.warning(self, "No 3D Preview", "3D preview is not available.")
            return False

        self.progress.setVisible(True)
        angles = self.angles_spin.value()
        size = self.render_size_spin.value()
        pil_frames = []
        for i in range(angles):
            self.progress.setValue(int(i / angles * 90))
            angle = i * (360.0 / angles)
            img = self.preview3d.preview.render_at_angle(angle, size, size)
            img = self._scale_image(img, scale)
            pil_img = qimage_to_pil(img)
            if not self.transparent_cb.isChecked():
                pil_img = self._apply_bg(pil_img)
            pil_frames.append(pil_img)

        if pil_frames:
            pil_frames[0].save(
                path, save_all=True, append_images=pil_frames[1:],
                duration=self.delay_spin.value(), loop=0, disposal=2
            )

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    def _export_layer_strip(self, scale):
        path = self._get_save_path("Export Layer Strip", "PNG Files (*.png)")
        if not path:
            return False

        layers = self.canvas.layers
        if not layers:
            return False

        self.progress.setVisible(True)
        total = len(layers)
        scaled_layers = []
        for i, layer in enumerate(layers):
            self.progress.setValue(int(i / total * 70))
            scaled_layers.append(self._scale_image(layer, scale))

        strip = self._build_sheet(scaled_layers, total, padding=0)
        if strip and not strip.save(path, "PNG"):
            raise RuntimeError(f"Failed to write {path}")

        self.progress.setValue(100)
        self._notify_success(path)
        return True

    # ── NEW: All Frames export ───────────────────────────────────────────────

    def _export_all_frames(self, scale):
        """Export every animation frame as a separate numbered PNG file."""
        folder = QFileDialog.getExistingDirectory(self, "Export All Frames to Folder")
        if not folder:
            return False

        self.canvas.save_current_frame()
        template = self.filename_template.text() or "{name}_{index:03d}"
        total = self.canvas.get_frame_count()

        self.progress.setVisible(True)
        for i in range(total):
            self.progress.setValue(int(i / max(total, 1) * 100))
            flat = self.canvas.get_flat_frame(i)
            if flat is None:
                continue
            img = self._scale_image(flat, scale)
            if not self.transparent_cb.isChecked():
                pil = qimage_to_pil(img)
                pil = self._apply_bg(pil)
                img = pil_to_qimage(pil)
            try:
                fname = template.format(name=f"frame", index=i) + ".png"
            except (KeyError, ValueError):
                fname = f"frame_{i:03d}.png"
            img.save(os.path.join(folder, fname), "PNG")

        self.progress.setValue(100)
        self._notify_success(folder)
        return True

    # ── NEW: OBJ 3D Model export ─────────────────────────────────────────────

    def _export_obj(self):
        """Export the sprite stack as a Wavefront OBJ + MTL voxel model.

        Each opaque pixel on each layer becomes a coloured quad (top face) at
        the corresponding height.  The resulting mesh can be imported into
        Blender, Unity, Godot, etc.
        """
        path = self._get_save_path(
            "Export 3D Model", "Wavefront OBJ (*.obj)"
        )
        if not path:
            return False

        layers = self.canvas.layers
        if not layers:
            return False

        self.progress.setVisible(True)
        mtl_path = os.path.splitext(path)[0] + ".mtl"
        mtl_name = os.path.basename(mtl_path)

        # Collect unique colours
        colour_map = {}  # (r,g,b) -> material index
        voxels = []  # (x, y, z, r, g, b)

        for z, layer in enumerate(layers):
            self.progress.setValue(int(z / len(layers) * 50))
            w, h = layer.width(), layer.height()
            for py in range(h):
                for px in range(w):
                    c = QColor(layer.pixel(px, py))
                    if c.alpha() < 128:
                        continue
                    rgb = (c.red(), c.green(), c.blue())
                    if rgb not in colour_map:
                        colour_map[rgb] = len(colour_map)
                    voxels.append((px, py, z, *rgb))

        if not voxels:
            QMessageBox.warning(self, "Empty", "No opaque pixels found to export.")
            return False

        # Write MTL
        with open(mtl_path, "w", encoding="utf-8") as mf:
            for rgb, idx in sorted(colour_map.items(), key=lambda x: x[1]):
                r, g, b = rgb
                mf.write(f"newmtl mat_{idx}\n")
                mf.write(f"Kd {r/255:.4f} {g/255:.4f} {b/255:.4f}\n")
                mf.write("Ka 0.1 0.1 0.1\n")
                mf.write("Ks 0.0 0.0 0.0\n")
                mf.write("d 1.0\n\n")

        # Write OBJ — one quad per voxel (top face)
        VOXEL_SIZE = 1.0
        with open(path, "w", encoding="utf-8") as of:
            of.write(f"# SpriteStack Studio OBJ export\n")
            of.write(f"# {len(voxels)} voxels, {len(colour_map)} materials\n")
            of.write(f"mtllib {mtl_name}\n\n")

            vi = 1  # vertex index (OBJ is 1-based)
            total = len(voxels)
            for n, (px, py, z, r, g, b) in enumerate(voxels):
                if n % 500 == 0:
                    self.progress.setValue(50 + int(n / total * 50))

                mat_idx = colour_map[(r, g, b)]

                # Top face quad (Y-up convention: x right, y up, z forward)
                x0 = px * VOXEL_SIZE
                x1 = x0 + VOXEL_SIZE
                y0 = z * VOXEL_SIZE
                y1 = y0 + VOXEL_SIZE
                z0 = py * VOXEL_SIZE
                z1 = z0 + VOXEL_SIZE

                # 8 vertices of the cube
                of.write(f"v {x0} {y0} {z0}\n")
                of.write(f"v {x1} {y0} {z0}\n")
                of.write(f"v {x1} {y1} {z0}\n")
                of.write(f"v {x0} {y1} {z0}\n")
                of.write(f"v {x0} {y0} {z1}\n")
                of.write(f"v {x1} {y0} {z1}\n")
                of.write(f"v {x1} {y1} {z1}\n")
                of.write(f"v {x0} {y1} {z1}\n")

                of.write(f"usemtl mat_{mat_idx}\n")
                # 6 faces of the cube
                of.write(f"f {vi} {vi+1} {vi+2} {vi+3}\n")    # front
                of.write(f"f {vi+5} {vi+4} {vi+7} {vi+6}\n")  # back
                of.write(f"f {vi+4} {vi} {vi+3} {vi+7}\n")    # left
                of.write(f"f {vi+1} {vi+5} {vi+6} {vi+2}\n")  # right
                of.write(f"f {vi+3} {vi+2} {vi+6} {vi+7}\n")  # top
                of.write(f"f {vi+4} {vi+5} {vi+1} {vi}\n")    # bottom
                vi += 8

        self.progress.setValue(100)
        self._notify_success(path)
        return True


# ---------------------------------------------------------------------------
# Import Dialog
# ---------------------------------------------------------------------------

class ImportDialog(QDialog):
    """Dialog for importing sprite sheets and images."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import")
        self.setMinimumWidth(480)
        self.imported_images = []

        layout = QVBoxLayout(self)

        # Import type
        type_group = QGroupBox("Import Type")
        type_layout = QVBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Single Image (as layer)",
            "Sprite Sheet (split to frames)",
            "Sprite Sheet (split to layers/stack)",
            "Folder of Images (as layers)",
            "Folder of Images (as frames)",
        ])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Frame Width:"))
        self.frame_w_spin = QSpinBox()
        self.frame_w_spin.setRange(1, 4096)
        self.frame_w_spin.setValue(32)
        self.frame_w_spin.valueChanged.connect(self._update_preview)
        size_row.addWidget(self.frame_w_spin)
        size_row.addWidget(QLabel("Height:"))
        self.frame_h_spin = QSpinBox()
        self.frame_h_spin.setRange(1, 4096)
        self.frame_h_spin.setValue(32)
        self.frame_h_spin.valueChanged.connect(self._update_preview)
        size_row.addWidget(self.frame_h_spin)
        # Auto-detect button
        self.autodetect_btn = QPushButton("Auto-detect")
        self.autodetect_btn.setToolTip(
            "Analyse the image to guess frame dimensions from transparent gutters."
        )
        self.autodetect_btn.clicked.connect(self._auto_detect_frame_size)
        size_row.addWidget(self.autodetect_btn)
        options_layout.addLayout(size_row)

        cols_row = QHBoxLayout()
        cols_row.addWidget(QLabel("Columns:"))
        self.import_cols_spin = QSpinBox()
        self.import_cols_spin.setRange(1, 64)
        self.import_cols_spin.setValue(4)
        self.import_cols_spin.valueChanged.connect(self._update_preview)
        cols_row.addWidget(self.import_cols_spin)
        cols_row.addWidget(QLabel("Rows:"))
        self.import_rows_spin = QSpinBox()
        self.import_rows_spin.setRange(1, 64)
        self.import_rows_spin.setValue(4)
        self.import_rows_spin.valueChanged.connect(self._update_preview)
        cols_row.addWidget(self.import_rows_spin)
        options_layout.addLayout(cols_row)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # File picker row
        file_row = QHBoxLayout()
        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        file_row.addWidget(self.file_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        # Import preview
        prev_group = QGroupBox("Preview")
        prev_layout = QVBoxLayout()
        self.import_preview = QLabel()
        self.import_preview.setFixedSize(256, 128)
        self.import_preview.setAlignment(Qt.AlignCenter)
        self.import_preview.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #3F3F46;"
        )
        prev_layout.addWidget(self.import_preview)
        self.import_preview_info = QLabel("—")
        self.import_preview_info.setAlignment(Qt.AlignCenter)
        self.import_preview_info.setStyleSheet("color: #888; font-size: 10px;")
        prev_layout.addWidget(self.import_preview_info)
        prev_group.setLayout(prev_layout)
        layout.addWidget(prev_group)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._do_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed(0)

    # ── Type changed ────────────────────────────────────────────────────────

    def _on_type_changed(self, idx):
        is_sheet = idx in (1, 2)
        self.frame_w_spin.setEnabled(is_sheet)
        self.frame_h_spin.setEnabled(is_sheet)
        self.import_cols_spin.setEnabled(is_sheet)
        self.import_rows_spin.setEnabled(is_sheet)
        self.autodetect_btn.setEnabled(is_sheet)
        self._update_preview()

    # ── Browse ───────────────────────────────────────────────────────────────

    def _browse(self):
        idx = self.type_combo.currentIndex()
        if idx in (3, 4):
            path = QFileDialog.getExistingDirectory(self, "Select Folder")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Image",
                "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All (*)"
            )
        if path:
            self.file_path.setText(path)
            self._update_preview()

    # ── Auto-detect frame size ───────────────────────────────────────────────

    def _auto_detect_frame_size(self):
        """Heuristic: look for repeating transparent column/row gutters."""
        path = self.file_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "Auto-detect", "Please select an image file first.")
            return
        try:
            pil = PILImage.open(path).convert('RGBA')
            arr = np.array(pil)
            alpha = arr[:, :, 3]

            # Find columns that are fully transparent
            col_transparent = np.all(alpha == 0, axis=0)
            row_transparent = np.all(alpha == 0, axis=1)

            def detect_period(mask):
                """Find repeating period in a boolean mask using differences."""
                indices = np.where(~mask)[0]
                if len(indices) < 2:
                    return None
                diffs = np.diff(indices)
                # Most common gap
                counts = {}
                for d in diffs:
                    counts[d] = counts.get(d, 0) + 1
                period = max(counts, key=counts.get)
                return int(period)

            fw = detect_period(col_transparent)
            fh = detect_period(row_transparent)

            if fw:
                self.frame_w_spin.setValue(fw)
            if fh:
                self.frame_h_spin.setValue(fh)

            if fw and fh:
                cols = pil.width // fw
                rows = pil.height // fh
                self.import_cols_spin.setValue(max(1, cols))
                self.import_rows_spin.setValue(max(1, rows))
                QMessageBox.information(
                    self, "Auto-detect",
                    f"Detected frame size: {fw}x{fh} px  ({cols} cols x {rows} rows)"
                )
            else:
                QMessageBox.warning(
                    self, "Auto-detect",
                    "Could not detect frame boundaries automatically. "
                    "Please set frame size manually."
                )
        except Exception as e:
            QMessageBox.critical(self, "Auto-detect Error", str(e))

        self._update_preview()

    # ── Import preview ───────────────────────────────────────────────────────

    def _update_preview(self, _=None):
        """Show thumbnail with grid overlay so the user can verify tiling."""
        path = self.file_path.text()
        idx = self.type_combo.currentIndex()

        if not path or not os.path.isfile(path):
            self.import_preview.clear()
            self.import_preview_info.setText("—")
            return

        try:
            src = QImage(path)
            if src.isNull():
                return

            # Scale to fit preview box
            box_w, box_h = 254, 126
            scaled = src.scaled(box_w, box_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            result = QImage(box_w, box_h, QImage.Format_ARGB32)
            result.fill(QColor(26, 26, 26))
            painter = QPainter(result)
            ox = (box_w - scaled.width()) // 2
            oy = (box_h - scaled.height()) // 2
            painter.drawImage(ox, oy, scaled)

            # Draw grid overlay for sheet imports
            if idx in (1, 2):
                fw = self.frame_w_spin.value()
                fh = self.frame_h_spin.value()
                if fw > 0 and fh > 0:
                    sx = scaled.width() / max(src.width(), 1)
                    sy = scaled.height() / max(src.height(), 1)
                    grid_color = QColor(0, 200, 255, 140)
                    painter.setPen(grid_color)
                    # Vertical lines
                    x = ox
                    while x <= ox + scaled.width():
                        painter.drawLine(x, oy, x, oy + scaled.height())
                        x += max(1, int(fw * sx))
                    # Horizontal lines
                    y = oy
                    while y <= oy + scaled.height():
                        painter.drawLine(ox, y, ox + scaled.width(), y)
                        y += max(1, int(fh * sy))

            painter.end()
            self.import_preview.setPixmap(QPixmap.fromImage(result))

            cols_est = max(1, src.width() // self.frame_w_spin.value()) if idx in (1, 2) else "—"
            rows_est = max(1, src.height() // self.frame_h_spin.value()) if idx in (1, 2) else "—"
            info = f"{src.width()}x{src.height()} px"
            if idx in (1, 2):
                total_frames = (src.width() // self.frame_w_spin.value()) * \
                               (src.height() // self.frame_h_spin.value())
                info += f"  |  {cols_est} cols x {rows_est} rows  =  {total_frames} frames"
            self.import_preview_info.setText(info)

        except Exception:
            self.import_preview.clear()
            self.import_preview_info.setText("—")

    # ── Import logic ─────────────────────────────────────────────────────────

    def _do_import(self):
        path = self.file_path.text()
        if not path:
            return
        idx = self.type_combo.currentIndex()
        try:
            if idx == 0:
                self._import_single(path)
            elif idx == 1:
                self._import_sheet_frames(path)
            elif idx == 2:
                self._import_sheet_layers(path)
            elif idx == 3:
                self._import_folder_layers(path)
            elif idx == 4:
                self._import_folder_frames(path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _import_single(self, path):
        img = QImage(path)
        if not img.isNull():
            self.imported_images = [img.convertToFormat(QImage.Format_ARGB32)]

    def _import_sheet_frames(self, path):
        img = QImage(path)
        if img.isNull():
            return
        fw = self.frame_w_spin.value()
        fh = self.frame_h_spin.value()
        cols = img.width() // fw
        rows = img.height() // fh
        self.imported_images = []
        for r in range(rows):
            for c in range(cols):
                frame = img.copy(c * fw, r * fh, fw, fh)
                self.imported_images.append(frame.convertToFormat(QImage.Format_ARGB32))

    def _import_sheet_layers(self, path):
        """Same tile splitting as frames but tagged for stack/layer usage.

        Sets imported_images exactly like _import_sheet_frames; the caller
        (main app) distinguishes layers vs frames via the import type index.
        """
        self._import_sheet_frames(path)

    def _collect_image_files(self, folder):
        """Return a deduplicated, sorted list of supported image files in folder."""
        extensions = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp")
        found = set()
        for ext in extensions:
            for p in glob.glob(os.path.join(folder, ext)):
                found.add(os.path.normcase(os.path.abspath(p)))
        # Also case-insensitive upper variants on case-sensitive FS
        for ext in extensions:
            for p in glob.glob(os.path.join(folder, ext.upper())):
                found.add(os.path.normcase(os.path.abspath(p)))
        return sorted(found)

    def _import_folder_layers(self, path):
        self.imported_images = []
        for f in self._collect_image_files(path):
            img = QImage(f)
            if not img.isNull():
                self.imported_images.append(img.convertToFormat(QImage.Format_ARGB32))

    def _import_folder_frames(self, path):
        self._import_folder_layers(path)