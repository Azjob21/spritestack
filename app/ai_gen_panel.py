from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.theme import T as _T


class AIGenPanel(QWidget):
    generate_requested = pyqtSignal(dict)
    status_message = pyqtSignal(str)

    _MODE_IDS = ["full", "fill_selection", "inpaint", "recolor"]
    _OUTPUT_IDS = {
        "New layer": "new_layer",
        "Replace selection": "replace_selection",
        "Blend into layer": "blend",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None
        self._mode = 0
        self._output_mode = "new_layer"
        self._style = "Pixel art"
        self._strength = 7
        self._palette_lock = True
        self._variations = 1
        self._tag_buttons: dict[str, QPushButton] = {}
        self._prompt_hints_dialog: QDialog | None = None

        self._build_ui()
        self.refresh_context(None)

    def _build_ui(self):
        self.setStyleSheet(
            f"QWidget {{ background: {_T['bg_panel']}; color: {_T['text']}; "
            f"font-family: '{_T['font']}'; font-size: {_T['font_size']}pt; }}"
            f"QLabel {{ color: {_T['text']}; }}"
            f"QPlainTextEdit, QTextEdit {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; "
            f"color: {_T['text']}; }}"
            f"QComboBox {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; color: {_T['text']}; }}"
            f"QSlider::groove:horizontal {{ border: 1px solid {_T['border']}; height: 4px; background: {_T['bg_input']}; }}"
            f"QSlider::sub-page:horizontal {{ background: {_T['accent']}; }}"
            f"QSlider::handle:horizontal {{ background: {_T['text']}; border: 1px solid {_T['border']}; width: 8px; margin: -3px 0; }}"
            f"QTabBar::tab {{ background: {_T['bg_header']}; color: {_T['text_muted']}; border: 1px solid {_T['border']}; "
            f"padding: 4px 8px; }}"
            f"QTabBar::tab:selected {{ background: {_T['bg_panel']}; color: {_T['text']}; border-bottom: 2px solid {_T['accent']}; }}"
            f"QSpinBox {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; color: {_T['text']}; }}"
            f"QCheckBox::indicator {{ width: 12px; height: 12px; background: {_T['bg_input']}; border: 1px solid {_T['border']}; }}"
            f"QCheckBox::indicator:checked {{ background: {_T['accent']}; border-color: {_T['accent']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.mode_tabs = QTabBar()
        self.mode_tabs.addTab("Full Sprite")
        self.mode_tabs.addTab("Fill Selection")
        self.mode_tabs.addTab("Inpaint Region")
        self.mode_tabs.addTab("Recolor")
        self.mode_tabs.setCurrentIndex(0)
        self.mode_tabs.currentChanged.connect(self._on_mode_changed)
        root.addWidget(self.mode_tabs)

        self.selection_warning = QLabel("⚠ Make a selection on the canvas first")
        self.selection_warning.setStyleSheet(f"QLabel {{ color: {_T['yellow']}; }}")
        self.selection_warning.hide()
        root.addWidget(self.selection_warning)

        self.context_label = QLabel("")
        self.context_label.setStyleSheet(
            f"QLabel {{ color: {_T['text_muted']}; font-size: {int(_T['font_size']) + 2}pt; }}"
        )
        root.addWidget(self.context_label)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Describe what to generate…  e.g. 'worn knight armour, dark palette, outlined'"
        )
        line_height = self.prompt_edit.fontMetrics().lineSpacing()
        self.prompt_edit.setFixedHeight(line_height * 4 + 18)
        root.addWidget(self.prompt_edit)

        tags_row = QHBoxLayout()
        tags_row.setSpacing(4)
        self._build_tag_buttons(tags_row)
        root.addLayout(tags_row)

        self.prompt_hints_btn = QPushButton("? Prompt hints")
        self.prompt_hints_btn.setFlat(True)
        self.prompt_hints_btn.clicked.connect(self._show_prompt_hints)
        root.addWidget(self.prompt_hints_btn, 0, Qt.AlignLeft)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.output_combo = QComboBox()
        self.output_combo.addItems(["New layer", "Replace selection", "Blend into layer"])
        self.output_combo.currentTextChanged.connect(self._on_output_changed)
        out_row.addWidget(self.output_combo, 1)
        root.addLayout(out_row)

        params_row = QHBoxLayout()
        params_row.setSpacing(6)

        params_row.addWidget(QLabel("Style"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Pixel art", "Isometric", "Low-poly", "Painterly"])
        self.style_combo.currentTextChanged.connect(lambda value: setattr(self, "_style", value))
        params_row.addWidget(self.style_combo)

        params_row.addWidget(QLabel("Strength"))
        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(1, 10)
        self.strength_slider.setValue(7)
        self.strength_slider.valueChanged.connect(self._on_strength_changed)
        params_row.addWidget(self.strength_slider, 1)
        self.strength_value_label = QLabel("7")
        params_row.addWidget(self.strength_value_label)

        params_row.addWidget(QLabel("Palette lock"))
        self.palette_lock_cb = QCheckBox()
        self.palette_lock_cb.setChecked(True)
        self.palette_lock_cb.toggled.connect(lambda checked: setattr(self, "_palette_lock", bool(checked)))
        params_row.addWidget(self.palette_lock_cb)

        params_row.addWidget(QLabel("Variations"))
        self.variations_spin = QSpinBox()
        self.variations_spin.setRange(1, 4)
        self.variations_spin.setValue(1)
        self.variations_spin.valueChanged.connect(lambda value: setattr(self, "_variations", int(value)))
        params_row.addWidget(self.variations_spin)
        root.addLayout(params_row)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setStyleSheet(
            f"QPushButton {{ background: {_T['accent']}; color: {_T['text_bright']}; "
            f"border: 1px solid {_T['accent']}; padding: 6px 10px; }}"
            f"QPushButton:disabled {{ background: {_T['accent_dim']}; color: {_T['text_dim']}; border-color: {_T['border']}; }}"
        )
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        root.addWidget(self.generate_btn)

    def _build_tag_buttons(self, layout: QHBoxLayout):
        for tag in self._load_tags():
            button = QPushButton(tag)
            button.setFlat(True)
            button.setCheckable(True)
            button.toggled.connect(lambda checked, t=tag: self._on_tag_toggled(t, checked))
            layout.addWidget(button)
            self._tag_buttons[tag] = button
        layout.addStretch(1)

    def _load_tags(self) -> list[str]:
        tags_path = Path(__file__).with_name("ai_tag_presets.json")
        fallback = [
            "worn",
            "outlined",
            "metallic",
            "dithered",
            "shaded",
            "dark fantasy",
            "bright palette",
            "pixel outline",
            "cel shaded",
            "top-down",
        ]
        try:
            payload = json.loads(tags_path.read_text(encoding="utf-8"))
            tags = payload.get("tags", [])
            if isinstance(tags, list):
                normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
                return normalized or fallback
        except Exception:
            pass
        return fallback

    def _load_prompt_hints(self) -> str:
        path = Path(__file__).with_name("ai_prompt_guide.txt")
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return "Prompt guide could not be loaded."

    def _show_prompt_hints(self):
        if self._prompt_hints_dialog is None:
            dialog = QDialog(self)
            dialog.setModal(False)
            dialog.setWindowTitle("Prompt hints")
            dialog.resize(680, 520)
            layout = QVBoxLayout(dialog)
            viewer = QTextEdit(dialog)
            viewer.setReadOnly(True)
            viewer.setPlainText(self._load_prompt_hints())
            layout.addWidget(viewer)
            self._prompt_hints_dialog = dialog
        self._prompt_hints_dialog.show()
        self._prompt_hints_dialog.raise_()
        self._prompt_hints_dialog.activateWindow()

    def _on_mode_changed(self, index: int):
        self._mode = max(0, min(index, len(self._MODE_IDS) - 1))
        self.refresh_context(self._canvas)

    def _on_output_changed(self, label: str):
        self._output_mode = self._OUTPUT_IDS.get(label, "new_layer")

    def _on_strength_changed(self, value: int):
        self._strength = int(value)
        self.strength_value_label.setText(str(value))

    def _on_tag_toggled(self, tag_text: str, checked: bool):
        token = tag_text.lstrip("+").strip()
        if not token:
            return
        segments = [s.strip() for s in self.prompt_edit.toPlainText().split(",") if s.strip()]
        lowered = [s.lower() for s in segments]
        if checked:
            if token.lower() not in lowered:
                segments.append(token)
        else:
            segments = [s for s in segments if s.lower() != token.lower()]
        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(", ".join(segments))
        self.prompt_edit.blockSignals(False)

    @staticmethod
    def _qimage_to_hex(image: QImage) -> str:
        if image is None or image.isNull():
            return ""
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        ptr = rgba.bits()
        ptr.setsize(rgba.byteCount())
        return bytes(ptr).hex()

    def _make_selection_payload(self) -> dict | None:
        canvas = self._canvas
        if canvas is None or getattr(canvas, "selection_rect", None) is None:
            return None
        rect = canvas.selection_rect
        try:
            layer = canvas.layers[canvas.active_layer]
        except Exception:
            return None
        region = layer.copy(rect)
        return {
            "x": int(rect.x()),
            "y": int(rect.y()),
            "w": int(rect.width()),
            "h": int(rect.height()),
            "region_hex": self._qimage_to_hex(region),
            "context_hex": self._qimage_to_hex(layer),
            "width": int(rect.width()),
            "height": int(rect.height()),
        }

    def refresh_context(self, canvas) -> None:
        self._canvas = canvas
        width = int(getattr(canvas, "canvas_width", 0) or 0)
        height = int(getattr(canvas, "canvas_height", 0) or 0)
        active_idx = int(getattr(canvas, "active_layer", 0) or 0)
        layer_names = getattr(canvas, "layer_names", []) or []
        if 0 <= active_idx < len(layer_names):
            layer_name = str(layer_names[active_idx])
        else:
            layer_name = f"Layer {active_idx + 1}"

        selection = getattr(canvas, "selection_rect", None)
        if selection is None:
            selection_text = "No selection"
        else:
            selection_text = f"Selection: {int(selection.width())}×{int(selection.height())} px"
        self.context_label.setText(
            f"Canvas: {width}×{height}  ·  Layer: {layer_name}  ·  {selection_text}"
        )
        needs_selection = self._mode in (1, 2)
        self.selection_warning.setVisible(needs_selection and selection is None)

    def set_generating(self, is_generating: bool) -> None:
        self.generate_btn.setEnabled(not is_generating)
        self.generate_btn.setText("Generating…" if is_generating else "Generate")

    def get_prompt(self) -> str:
        return self.prompt_edit.toPlainText().strip()

    def current_mode(self) -> str:
        return self._MODE_IDS[self._mode]

    def _on_generate_clicked(self):
        prompt = self.get_prompt()
        if not prompt:
            self.status_message.emit("Prompt is empty.")
            return

        payload = {
            "prompt": prompt,
            "mode": self._MODE_IDS[self._mode],
            "output_mode": self._output_mode,
            "style": self._style,
            "strength": int(self._strength),
            "palette_lock": bool(self._palette_lock),
            "variations": int(self._variations),
        }

        if self._mode in (1, 2):
            selection = self._make_selection_payload()
            if selection is not None:
                payload["selection"] = selection

        self.generate_requested.emit(payload)
        self.set_generating(True)
