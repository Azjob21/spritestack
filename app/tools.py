"""
Drawing tools toolbar with descriptive icons, brush options, and selection helpers.
All signals are fully wired. Includes opacity, tolerance, hardness, grid, onion skin,
magic wand threshold, and safe bidirectional slider/spinbox sync.

Restyled: Aseprite-inspired flat dark theme with hard 1px borders, no rounded corners.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox,
    QLabel, QToolButton, QButtonGroup, QCheckBox,
    QSlider, QFrame, QComboBox, QSizePolicy, QColorDialog
)
from PyQt5.QtGui import QIcon, QPainter, QColor, QPixmap, QPen, QFont, QPolygon
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QPoint

from app.theme import T as _T, FONT_FAMILY, FONT_SIZE, ACCENT, TEXT, TEXT_MUTED, TEXT_BRIGHT, BG_PANEL, BG_INPUT, BG_RAISED, BG_HEADER, BORDER, BORDER_LIGHT, BORDER_DARK

# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _draw_icon(draw_func, size=24, bg=Qt.transparent):
    pix = QPixmap(size, size)
    pix.fill(bg)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    draw_func(p, size)
    p.end()
    return QIcon(pix)


def _pencil_icon(p, s):
    p.setPen(QPen(QColor(_T["text_bright"]), 2))
    p.drawLine(5, s - 5, s - 5, 5)
    p.setPen(QPen(QColor(_T["yellow"]), 2))
    p.drawLine(4, s - 4, 7, s - 7)


def _eraser_icon(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_T["red"]))
    p.drawRoundedRect(4, 8, s - 8, s - 12, 3, 3)
    p.setBrush(QColor("#FFB0C8"))
    p.drawRoundedRect(4, 4, s - 8, 8, 3, 3)


def _fill_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    poly = QPolygon([QPoint(6, 6), QPoint(s - 4, 6),
                     QPoint(s - 6, s - 6), QPoint(4, s - 6)])
    p.drawPolygon(poly)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_T["accent"]))
    p.drawEllipse(s - 8, s - 10, 6, 8)


def _eyedropper_icon(p, s):
    p.setPen(QPen(QColor(_T["yellow"]), 2))
    p.drawLine(6, s - 6, s - 6, 6)
    p.setBrush(QColor(_T["yellow"]))
    p.drawEllipse(s - 9, 3, 6, 6)


def _line_icon(p, s):
    p.setPen(QPen(QColor(_T["green"]), 2))
    p.drawLine(4, s - 4, s - 4, 4)


def _rect_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRect(4, 4, s - 8, s - 8)


def _rect_fill_icon(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_T["accent"]))
    p.drawRect(4, 4, s - 8, s - 8)


def _circle_icon(p, s):
    p.setPen(QPen(QColor(_T["red"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(4, 4, s - 8, s - 8)


def _circle_fill_icon(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_T["red"]))
    p.drawEllipse(4, 4, s - 8, s - 8)


def _select_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 1, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(4, 4, s - 8, s - 8)


def _move_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    mid = s // 2
    p.drawLine(mid, 4, mid, s - 4)
    p.drawLine(4, mid, s - 4, mid)
    p.drawLine(mid, 4, mid - 3, 7)
    p.drawLine(mid, 4, mid + 3, 7)
    p.drawLine(mid, s - 4, mid - 3, s - 7)
    p.drawLine(mid, s - 4, mid + 3, s - 7)


def _wand_icon(p, s):
    p.setPen(QPen(QColor(_T["yellow"]), 2))
    p.drawLine(4, s - 4, s - 6, 6)
    p.setBrush(QColor(_T["yellow"]))
    p.drawEllipse(s - 9, 3, 5, 5)
    p.setPen(QPen(QColor(_T["text_bright"]), 1))
    for dx, dy in [(2, 2), (s - 4, 10), (8, s - 8)]:
        p.drawPoint(dx, dy)


def _symmetry_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    mid = s // 2
    p.drawLine(mid, 3, mid, s - 3)
    p.drawLine(3, mid, s - 3, mid)
    p.setPen(QPen(QColor(_T["text_bright"]), 1, Qt.DotLine))
    p.drawRect(4, 4, s - 8, s - 8)


def _gradient_icon(p, s):
    for i in range(s - 8):
        t = i / max(1, s - 9)
        c = int(255 * t)
        p.setPen(QColor(c, c, c))
        p.drawLine(4 + i, 4, 4 + i, s - 4)


def _zoom_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(4, 4, s - 12, s - 12)
    p.drawLine(s - 8, s - 8, s - 4, s - 4)
    p.setPen(QPen(QColor(_T["text_bright"]), 1))
    mid = s // 2 - 2
    p.drawLine(8, mid, s - 10, mid)
    p.drawLine(mid, 8, mid, s - 10)


def _blur_icon(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_T["accent_dim"]))
    p.drawEllipse(3, 3, s - 6, s - 6)
    p.setBrush(QColor(_T["accent"]))
    p.drawEllipse(6, 6, s - 12, s - 12)


def _curve_icon(p, s):
    from PyQt5.QtGui import QPainterPath
    p.setPen(QPen(QColor(_T["green"]), 2))
    path = QPainterPath()
    path.moveTo(4, s - 4)
    path.cubicTo(4, 4, s - 4, s - 4, s - 4, 4)
    p.drawPath(path)


def _contour_icon(p, s):
    p.setPen(QPen(QColor(_T["yellow"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(6, 6, s - 12, s - 12, 4, 4)


def _ai_assist_icon(p, s):
    p.setPen(QPen(QColor(_T["accent"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(4, 4, s - 8, s - 8)
    p.setPen(QPen(QColor(_T["yellow"]), 2))
    p.drawLine(s // 2, 6, s // 2, s - 6)
    p.drawLine(6, s // 2, s - 6, s // 2)


def _lasso_icon(p, s):
    from PyQt5.QtGui import QPainterPath
    p.setPen(QPen(QColor(_T["accent"]), 2, Qt.DashLine))
    path = QPainterPath()
    path.moveTo(s // 2, 4)
    path.cubicTo(s - 4, 4, s - 4, s - 4, s // 2, s - 4)
    path.cubicTo(4, s - 4, 4, 4, s // 2, 4)
    p.drawPath(path)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ("pencil",      "Pencil (B)",          _pencil_icon,      "B"),
    ("eraser",      "Eraser (E)",          _eraser_icon,      "E"),
    ("fill",        "Fill Bucket (G)",     _fill_icon,        "G"),
    ("eyedropper",  "Eyedropper (I)",      _eyedropper_icon,  "I"),
    ("line",        "Line (L)",            _line_icon,        "L"),
    ("curve",       "Curve (K)",           _curve_icon,       "K"),
    ("rect",        "Rectangle (R)",       _rect_icon,        "R"),
    ("rect_fill",   "Filled Rect (F)",     _rect_fill_icon,   "F"),
    ("circle",      "Circle (C)",          _circle_icon,      "C"),
    ("circle_fill", "Filled Circle (O)",   _circle_fill_icon, "O"),
    ("select",      "Select (S)",          _select_icon,      "S"),
    ("lasso",       "Lasso (A)",           _lasso_icon,       "A"),
    ("symmetry",    "Symmetry Axis (Y)",   _symmetry_icon,    "Y"),
    ("move",        "Move (M)",            _move_icon,        "M"),
    ("magic_wand",  "Magic Wand (W)",      _wand_icon,        "W"),
    ("gradient",    "Gradient (D)",        _gradient_icon,    "D"),
    ("zoom",        "Zoom (Z)",            _zoom_icon,        "Z"),
    ("blur",        "Blur (U)",            _blur_icon,        "U"),
    ("contour",     "Contour (T)",         _contour_icon,     "T"),
    ("ai_assist",   "AI Assist",           _ai_assist_icon,   "-"),
]

TOOL_DISPLAY_NAMES = {
    "pencil":       "Pencil",
    "eraser":       "Eraser",
    "fill":         "Fill",
    "eyedropper":   "Pick",
    "line":         "Line",
    "curve":        "Curve",
    "rect":         "Rect",
    "rect_fill":    "RectF",
    "circle":       "Circle",
    "circle_fill":  "CircF",
    "select":       "Select",
    "lasso":        "Lasso",
    "symmetry":     "Symmetry",
    "move":         "Move",
    "magic_wand":   "Wand",
    "gradient":     "Gradient",
    "zoom":         "Zoom",
    "blur":         "Blur",
    "contour":      "Contour",
    "ai_assist":    "AI Assist",
}

TOLERANCE_TOOLS = {"magic_wand", "fill"}
BRUSH_TOOLS     = {"pencil", "eraser", "line", "curve", "rect", "rect_fill",
                   "circle", "circle_fill", "blur"}


# ---------------------------------------------------------------------------
# Bidirectional slider <-> spinbox
# ---------------------------------------------------------------------------

def _sync_slider_spin(slider: QSlider, spin: QSpinBox):
    def s2sp(v):
        spin.blockSignals(True); spin.setValue(v); spin.blockSignals(False)
    def sp2s(v):
        slider.blockSignals(True); slider.setValue(v); slider.blockSignals(False)
    slider.valueChanged.connect(s2sp)
    spin.valueChanged.connect(sp2s)


# ---------------------------------------------------------------------------
# ToolBar
# ---------------------------------------------------------------------------

class ToolBar(QWidget):
    """
    Vertical toolbar with all drawing tools and options.

    Signals
    -------
    tool_changed(str)
    brush_size_changed(int)
    brush_shape_changed(str)
    brush_hardness_changed(int)
    brush_opacity_changed(int)
    tolerance_changed(int)
    gradient_mode_changed(str)
    gradient_start_color_changed(QColor)
    gradient_end_color_changed(QColor)
    mirror_x_changed(bool)
    mirror_y_changed(bool)
    symmetry_axis_count_changed(int)
    symmetry_inverse_changed(bool)
    grid_toggled(bool)
    onion_toggled(bool)
    onion_frames_changed(int)
    center_object_clicked()
    """

    tool_changed           = pyqtSignal(str)
    brush_size_changed     = pyqtSignal(int)
    brush_shape_changed    = pyqtSignal(str)
    brush_hardness_changed = pyqtSignal(int)
    brush_opacity_changed  = pyqtSignal(int)
    tolerance_changed      = pyqtSignal(int)
    gradient_mode_changed  = pyqtSignal(str)
    gradient_start_color_changed = pyqtSignal(object)
    gradient_end_color_changed   = pyqtSignal(object)
    mirror_x_changed       = pyqtSignal(bool)
    mirror_y_changed       = pyqtSignal(bool)
    symmetry_axis_count_changed = pyqtSignal(int)
    symmetry_inverse_changed = pyqtSignal(bool)
    grid_toggled           = pyqtSignal(bool)
    onion_toggled          = pyqtSignal(bool)
    onion_frames_changed   = pyqtSignal(int)
    center_object_clicked  = pyqtSignal()
    selection_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(174)
        self.setMaximumWidth(260)
        self.setStyleSheet(
            f"QWidget {{ background: {_T['bg_panel']}; color: {_T['text']}; }}"
        )
        self.current_tool = "pencil"
        self._building = True
        self.gradient_start_color = QColor(0, 0, 0, 255)
        self.gradient_end_color = QColor(255, 255, 255, 255)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_tools_section())
        layout.addWidget(self._build_brush_section())
        layout.addWidget(self._build_tolerance_section())
        layout.addWidget(self._build_selection_mode_section())
        layout.addWidget(self._build_gradient_section())
        layout.addWidget(self._build_symmetry_section())
        layout.addWidget(self._build_view_section())
        layout.addStretch()

        self._building = False
        self._update_context_panels("pencil")

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_tools_section(self):
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(5)

        outer.addWidget(self._sec_label("TOOLS"))

        self.tool_buttons = {}
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        grid = QVBoxLayout()
        grid.setSpacing(3)
        row_layout = None

        for idx, (tool_id, tooltip, icon_func, key_label) in enumerate(TOOLS):
            btn = QToolButton()
            btn.setToolTip(tooltip)
            btn.setIcon(_draw_icon(icon_func))
            btn.setIconSize(QSize(20, 20))
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setText(TOOL_DISPLAY_NAMES.get(tool_id, tool_id[:6]))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setStyleSheet(self._tool_btn_style())

            if tool_id == "pencil":
                btn.setChecked(True)

            self.tool_buttons[tool_id] = btn
            self.button_group.addButton(btn)
            btn.clicked.connect(lambda checked, tid=tool_id: self._on_tool_clicked(tid))

            if idx % 2 == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(3)
                grid.addLayout(row_layout)
            row_layout.addWidget(btn)

        if len(TOOLS) % 2 != 0:
            row_layout.addStretch()

        outer.addLayout(grid)
        return wrapper

    def _build_brush_section(self):
        self.brush_section = QFrame()
        self.brush_section.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(self.brush_section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("BRUSH", color=_T["red"]))

        # Size
        layout.addWidget(self._sub_label("Size"))
        size_row = QHBoxLayout()
        size_row.setSpacing(5)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 64)
        self.size_spin.setValue(1)
        self.size_spin.setStyleSheet(self._spinbox_style())
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(1, 64)
        self.size_slider.setValue(1)
        self.size_slider.setStyleSheet(self._slider_style(_T["red"], _T["bg_input"]))
        self.size_label = QLabel("1 px")
        self.size_label.setFixedWidth(34)
        self.size_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 9px; "
            f"color: {_T['red']}; font-weight: 700; background: transparent;"
        )
        _sync_slider_spin(self.size_slider, self.size_spin)
        self.size_spin.valueChanged.connect(self._on_size_changed)
        self.size_spin.valueChanged.connect(lambda v: self.size_label.setText(f"{v} px"))
        size_row.addWidget(self.size_spin)
        size_row.addWidget(self.size_label)
        layout.addLayout(size_row)
        layout.addWidget(self.size_slider)

        # Shape
        shape_row = QHBoxLayout()
        shape_row.setSpacing(5)
        shape_row.addWidget(self._sub_label("Shape"))
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["Square", "Circle", "Diamond"])
        self.shape_combo.setStyleSheet(self._combo_style())
        self.shape_combo.currentTextChanged.connect(self._on_shape_changed)
        shape_row.addWidget(self.shape_combo, 1)
        layout.addLayout(shape_row)

        # Hardness
        layout.addWidget(self._sub_label("Hardness"))
        hard_row = QHBoxLayout()
        hard_row.setSpacing(5)
        self.hardness_slider = QSlider(Qt.Horizontal)
        self.hardness_slider.setRange(0, 100)
        self.hardness_slider.setValue(100)
        self.hardness_slider.setStyleSheet(self._slider_style(_T["accent"], _T["bg_input"]))
        self.hardness_label = QLabel("100%")
        self.hardness_label.setFixedWidth(34)
        self.hardness_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 9px; "
            f"color: {_T['accent']}; font-weight: 700; background: transparent;"
        )
        self.hardness_slider.valueChanged.connect(self._on_hardness_changed)
        hard_row.addWidget(self.hardness_slider)
        hard_row.addWidget(self.hardness_label)
        layout.addLayout(hard_row)

        # Opacity
        layout.addWidget(self._sub_label("Opacity"))
        op_row = QHBoxLayout()
        op_row.setSpacing(5)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setStyleSheet(self._slider_style(_T["accent"], _T["bg_input"]))
        self.opacity_label = QLabel("100%")
        self.opacity_label.setFixedWidth(34)
        self.opacity_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 9px; "
            f"color: {_T['accent']}; font-weight: 700; background: transparent;"
        )
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self.opacity_slider)
        op_row.addWidget(self.opacity_label)
        layout.addLayout(op_row)

        return self.brush_section

    def _build_tolerance_section(self):
        self.tolerance_section = QFrame()
        self.tolerance_section.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(self.tolerance_section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("TOLERANCE", color=_T["yellow"]))

        tol_row = QHBoxLayout()
        tol_row.setSpacing(5)
        self.tolerance_slider = QSlider(Qt.Horizontal)
        self.tolerance_slider.setRange(0, 255)
        self.tolerance_slider.setValue(32)
        self.tolerance_slider.setStyleSheet(self._slider_style(_T["yellow"], _T["bg_input"]))
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(32)
        self.tolerance_spin.setStyleSheet(self._spinbox_style())
        _sync_slider_spin(self.tolerance_slider, self.tolerance_spin)
        self.tolerance_slider.valueChanged.connect(self._on_tolerance_changed)
        tol_row.addWidget(self.tolerance_slider)
        tol_row.addWidget(self.tolerance_spin)
        layout.addLayout(tol_row)

        self.contiguous_cb = QCheckBox("Contiguous only")
        self.contiguous_cb.setChecked(True)
        self.contiguous_cb.setStyleSheet(self._checkbox_style())
        layout.addWidget(self.contiguous_cb)

        self.tolerance_section.setVisible(False)
        return self.tolerance_section

    def _build_selection_mode_section(self):
        self.sel_mode_section = QFrame()
        self.sel_mode_section.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(self.sel_mode_section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("SELECTION MODE", color=_T["accent"]))

        self.sel_mode_group = QButtonGroup(self)
        self.sel_mode_group.setExclusive(True)
        modes = [
            ("replace",   "Replace",   "New selection replaces old"),
            ("add",       "Add",       "Add to existing selection"),
            ("subtract",  "Subtract",  "Remove from selection"),
            ("intersect", "Intersect", "Keep only overlap"),
        ]
        row = QHBoxLayout()
        row.setSpacing(3)
        for mode_id, label, tip in modes:
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(self._tool_btn_style())
            if mode_id == "replace":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, m=mode_id: self._on_sel_mode(m))
            self.sel_mode_group.addButton(btn)
            row.addWidget(btn)
        layout.addLayout(row)

        self.sel_mode_section.setVisible(False)
        return self.sel_mode_section

    def _on_sel_mode(self, mode_id):
        self.selection_mode_changed.emit(mode_id)

    def _build_gradient_section(self):
        self.gradient_section = QFrame()
        self.gradient_section.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(self.gradient_section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("GRADIENT", color=_T["accent"]))

        # Colors
        layout.addWidget(self._sub_label("Colors"))
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self.gradient_start_btn = QPushButton()
        self.gradient_start_btn.setFixedSize(24, 24)
        self.gradient_start_btn.setToolTip("Gradient start color")
        self.gradient_start_btn.clicked.connect(self._pick_gradient_start)
        self._set_color_button(self.gradient_start_btn, self.gradient_start_color)
        self.gradient_end_btn = QPushButton()
        self.gradient_end_btn.setFixedSize(24, 24)
        self.gradient_end_btn.setToolTip("Gradient end color")
        self.gradient_end_btn.clicked.connect(self._pick_gradient_end)
        self._set_color_button(self.gradient_end_btn, self.gradient_end_color)
        color_row.addWidget(self._sub_label("A"))
        color_row.addWidget(self.gradient_start_btn)
        color_row.addSpacing(6)
        color_row.addWidget(self._sub_label("B"))
        color_row.addWidget(self.gradient_end_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        # Shape
        shape_row = QHBoxLayout()
        shape_row.setSpacing(5)
        shape_row.addWidget(self._sub_label("Shape"))
        self.gradient_shape_combo = QComboBox()
        self.gradient_shape_combo.addItems(["Free (Drag)", "Horizontal", "Vertical", "Diagonal"])
        self.gradient_shape_combo.setStyleSheet(self._combo_style())
        self.gradient_shape_combo.currentTextChanged.connect(self._on_gradient_shape_changed)
        shape_row.addWidget(self.gradient_shape_combo, 1)
        layout.addLayout(shape_row)

        self.gradient_section.setVisible(False)
        return self.gradient_section



    def _build_symmetry_section(self):
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("SYMMETRY", color=_T["accent"]))

        sym_row = QHBoxLayout()
        sym_row.setSpacing(3)

        self.mirror_x_cb = QCheckBox("  Mirror X")
        self.mirror_x_cb.setStyleSheet(self._sym_toggle_style())
        self.mirror_x_cb.toggled.connect(self.mirror_x_changed.emit)
        sym_row.addWidget(self.mirror_x_cb)

        self.mirror_y_cb = QCheckBox("  Mirror Y")
        self.mirror_y_cb.setStyleSheet(self._sym_toggle_style())
        self.mirror_y_cb.toggled.connect(self.mirror_y_changed.emit)
        sym_row.addWidget(self.mirror_y_cb)

        layout.addLayout(sym_row)

        axis_row = QHBoxLayout()
        axis_row.setSpacing(5)
        axis_row.addWidget(self._sub_label("Axes"))
        self.symmetry_axes_spin = QSpinBox()
        self.symmetry_axes_spin.setRange(1, 32)
        self.symmetry_axes_spin.setValue(1)
        self.symmetry_axes_spin.setToolTip("Number of symmetry axes/repetitions around the symmetry center")
        self.symmetry_axes_spin.setStyleSheet(self._spinbox_style())
        self.symmetry_axes_spin.valueChanged.connect(self.symmetry_axis_count_changed.emit)
        axis_row.addWidget(self.symmetry_axes_spin)
        axis_row.addStretch()
        layout.addLayout(axis_row)

        self.symmetry_inverse_cb = QCheckBox("  Inverse / Rotational")
        self.symmetry_inverse_cb.setToolTip(
            "Repeat strokes by rotation around the symmetry center instead of reflecting them"
        )
        self.symmetry_inverse_cb.setStyleSheet(self._checkbox_style())
        self.symmetry_inverse_cb.toggled.connect(self.symmetry_inverse_changed.emit)
        layout.addWidget(self.symmetry_inverse_cb)
        return wrapper

    def _build_view_section(self):
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background: {_T['bg_panel']}; border: 1px solid {_T['border']}; }}"
        )
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        layout.addWidget(self._sec_label("VIEW", color=_T["accent"]))

        self.grid_cb = QCheckBox("Show Grid")
        self.grid_cb.setChecked(True)
        self.grid_cb.setStyleSheet(self._checkbox_style())
        self.grid_cb.toggled.connect(self.grid_toggled.emit)
        layout.addWidget(self.grid_cb)

        self.onion_cb = QCheckBox("Onion Skinning")
        self.onion_cb.setStyleSheet(self._checkbox_style())
        self.onion_cb.toggled.connect(self._on_onion_toggled)
        layout.addWidget(self.onion_cb)

        onion_row = QHBoxLayout()
        self.onion_label = QLabel("Frames:")
        self.onion_label.setEnabled(False)
        self.onion_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 9px; "
            f"color: {_T['text_muted']}; background: transparent;"
        )
        self.onion_spin = QSpinBox()
        self.onion_spin.setRange(1, 8)
        self.onion_spin.setValue(2)
        self.onion_spin.setEnabled(False)
        self.onion_spin.setStyleSheet(self._spinbox_style())
        self.onion_spin.valueChanged.connect(self.onion_frames_changed.emit)
        onion_row.addWidget(self.onion_label)
        onion_row.addWidget(self.onion_spin)
        onion_row.addStretch()
        layout.addLayout(onion_row)

        # Centre Object button
        self.centre_btn = QPushButton("  Centre Object")
        self.centre_btn.setToolTip("Centre layer content on canvas  (Ctrl+Shift+C)")
        self.centre_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
                color: {_T['accent']};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
                padding: 5px 6px;
                margin-top: 2px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {_T['bg_header']};
                border-color: {_T['accent']};
                color: {_T['text_bright']};
            }}
            QPushButton:pressed {{
                background: {_T['bg_input']};
            }}
        """)
        self.centre_btn.clicked.connect(self.center_object_clicked.emit)
        layout.addWidget(self.centre_btn)

        return wrapper

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_tool_clicked(self, tool_id: str):
        self.current_tool = tool_id
        self._update_context_panels(tool_id)
        self.tool_changed.emit(tool_id)

    def _on_size_changed(self, val: int):
        self.brush_size_changed.emit(val)

    def _on_shape_changed(self, text: str):
        self.brush_shape_changed.emit(text)

    def _on_hardness_changed(self, val: int):
        self.hardness_label.setText(f"{val}%")
        self.brush_hardness_changed.emit(val)

    def _on_opacity_changed(self, val: int):
        self.opacity_label.setText(f"{val}%")
        self.brush_opacity_changed.emit(val)

    def _on_tolerance_changed(self, val: int):
        self.tolerance_changed.emit(val)

    def _on_gradient_shape_changed(self, text: str):
        mode = {
            "Free (Drag)": "free",
            "Horizontal": "horizontal",
            "Vertical": "vertical",
            "Diagonal": "diagonal",
        }.get(text, "free")
        self.gradient_mode_changed.emit(mode)

    def _pick_gradient_start(self):
        color = QColorDialog.getColor(self.gradient_start_color, self, "Gradient Start Color")
        if color.isValid():
            self._set_gradient_start_color(color, emit=True)

    def _pick_gradient_end(self):
        color = QColorDialog.getColor(self.gradient_end_color, self, "Gradient End Color")
        if color.isValid():
            self._set_gradient_end_color(color, emit=True)

    def _on_onion_toggled(self, enabled: bool):
        self.onion_label.setEnabled(enabled)
        self.onion_spin.setEnabled(enabled)
        self.onion_toggled.emit(enabled)

    def _update_context_panels(self, tool_id: str):
        if self._building:
            return
        self.brush_section.setVisible(tool_id in BRUSH_TOOLS)
        self.tolerance_section.setVisible(tool_id in TOLERANCE_TOOLS)
        self.sel_mode_section.setVisible(tool_id in {"select", "lasso", "magic_wand"})
        self.gradient_section.setVisible(tool_id == "gradient")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_tool(self, tool_id: str):
        if tool_id in self.tool_buttons:
            self.tool_buttons[tool_id].setChecked(True)
            self._on_tool_clicked(tool_id)

    def keypress_select_tool(self, key) -> bool:
        key_map = {
            Qt.Key_B: "pencil",      Qt.Key_E: "eraser",
            Qt.Key_G: "fill",        Qt.Key_I: "eyedropper",
            Qt.Key_L: "line",        Qt.Key_K: "curve",
            Qt.Key_R: "rect",
            Qt.Key_F: "rect_fill",   Qt.Key_C: "circle",
            Qt.Key_O: "circle_fill", Qt.Key_S: "select",
            Qt.Key_A: "lasso",       Qt.Key_Y: "symmetry",
            Qt.Key_M: "move",        Qt.Key_W: "magic_wand",
            Qt.Key_D: "gradient",    Qt.Key_Z: "zoom",
            Qt.Key_U: "blur",        Qt.Key_T: "contour",
        }
        if key in key_map:
            self.select_tool(key_map[key])
            return True
        return False

    def get_brush_options(self) -> dict:
        return {
            "size":       self.size_spin.value(),
            "shape":      self.shape_combo.currentText(),
            "hardness":   self.hardness_slider.value(),
            "opacity":    self.opacity_slider.value(),
            "tolerance":  self.tolerance_slider.value(),
            "contiguous": self.contiguous_cb.isChecked(),
        }

    def get_view_options(self) -> dict:
        return {
            "grid":         self.grid_cb.isChecked(),
            "onion_skin":   self.onion_cb.isChecked(),
            "onion_frames": self.onion_spin.value(),
        }

    def set_brush_size(self, size: int):
        self.size_spin.setValue(max(1, min(64, size)))

    def set_gradient_colors(self, start, end):
        self._set_gradient_start_color(start, emit=False)
        self._set_gradient_end_color(end, emit=False)

    def set_gradient_mode(self, mode: str):
        text = {
            "free": "Free (Drag)",
            "horizontal": "Horizontal",
            "vertical": "Vertical",
            "diagonal": "Diagonal",
        }.get(mode, "Free (Drag)")
        self.gradient_shape_combo.blockSignals(True)
        self.gradient_shape_combo.setCurrentText(text)
        self.gradient_shape_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _tool_btn_style(self):
        return f"""
            QToolButton {{
                background: {_T['bg_raised']};
                border: 1px solid {_T['border']};
                color: {_T['text_muted']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                text-align: left;
                padding-left: 4px;
            }}
            QToolButton:checked {{
                background: {_T['accent_dim']};
                border-color: {_T['accent']};
                color: {_T['text_bright']};
            }}
            QToolButton:hover:!checked {{
                background: {_T['bg_header']};
                border-color: {_T['border_light']};
                color: {_T['text']};
            }}
            QToolButton:pressed {{
                background: {_T['bg_input']};
            }}
        """

    def _slider_style(self, handle_color: str, fill_color: str) -> str:
        return f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
            }}
            QSlider::handle:horizontal {{
                background: {_T['text_bright']};
                border: 1px solid {_T['border_light']};
                width: 12px;
                margin: -4px 0;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {fill_color}, stop:1 {handle_color});
            }}
        """

    def _spinbox_style(self) -> str:
        return f"""
            QSpinBox {{
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
                color: {_T['text']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                padding: 2px 4px;
            }}
            QSpinBox:hover {{ border-color: {_T['border_light']}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {_T['bg_raised']};
                border: none;
                border-left: 1px solid {_T['border']};
                width: 14px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {_T['bg_header']};
            }}
        """

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
                color: {_T['text']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                padding: 3px 18px 3px 6px;
            }}
            QComboBox:hover {{ border-color: {_T['border_light']}; color: {_T['text_bright']}; }}
            QComboBox::drop-down {{ border: none; background: transparent; }}
            QComboBox QAbstractItemView {{
                background: {_T['bg_panel']};
                color: {_T['text']};
                border: 1px solid {_T['border_light']};
                selection-background-color: {_T['accent_dim']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
            }}
        """

    def _color_button_style(self, color: QColor) -> str:
        return (
            "QPushButton {"
            f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()});"
            f"border: 1px solid {_T['border']};"
            "}"
            f"QPushButton:hover {{ border-color: {_T['border_light']}; }}"
        )

    def _set_color_button(self, button: QPushButton, color: QColor):
        button.setStyleSheet(self._color_button_style(color))
        button.setToolTip(color.name())

    def _set_gradient_start_color(self, color: QColor, emit: bool = False):
        self.gradient_start_color = QColor(color)
        self._set_color_button(self.gradient_start_btn, self.gradient_start_color)
        if emit:
            self.gradient_start_color_changed.emit(self.gradient_start_color)

    def _set_gradient_end_color(self, color: QColor, emit: bool = False):
        self.gradient_end_color = QColor(color)
        self._set_color_button(self.gradient_end_btn, self.gradient_end_color)
        if emit:
            self.gradient_end_color_changed.emit(self.gradient_end_color)

    def _checkbox_style(self) -> str:
        return f"""
            QCheckBox {{
                color: {_T['text_muted']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                spacing: 5px;
                background: transparent;
            }}
            QCheckBox:hover {{ color: {_T['text']}; }}
            QCheckBox::indicator {{
                width: 13px; height: 13px;
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
            }}
            QCheckBox::indicator:checked {{
                background: {_T['accent_dim']};
                border-color: {_T['accent']};
            }}
            QCheckBox::indicator:hover {{ border-color: {_T['border_light']}; }}
        """

    def _sym_toggle_style(self) -> str:
        return f"""
            QCheckBox {{
                color: {_T['text_dim']};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                spacing: 4px;
                background: {_T['bg_input']};
                border: 1px solid {_T['border_dark']};
                padding: 4px 6px;
            }}
            QCheckBox:hover {{
                color: {_T['text']};
                background: {_T['bg_header']};
            }}
            QCheckBox:checked {{
                background: {_T['accent_dim']};
                border-color: {_T['accent']};
                color: {_T['accent']};
            }}
            QCheckBox::indicator {{ width: 0; height: 0; margin: 0; }}
        """

    @staticmethod
    def _sec_label(text: str, color: str = None) -> QLabel:
        c = color or _T["text_dim"]
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 8px; font-weight: 700; "
            f"letter-spacing: 0.15em; color: {c}; background: transparent;"
        )
        return lbl

    @staticmethod
    def _sub_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 8px; "
            f"color: {_T['text_muted']}; background: transparent; margin-top: 1px;"
        )
        return lbl

    # kept for backward compatibility — main_window may call these
    @staticmethod
    def _group_style(title_color: str) -> str:
        return f"""
            QGroupBox {{
                border: 1px solid {_T['border']};
                margin-top: 10px; padding-top: 14px;
                font-family: '{FONT_FAMILY}'; font-size: 9px;
                font-weight: bold; color: {title_color};
                background: {_T['bg_panel']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 8px; padding: 0 4px;
            }}
        """

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; color: {_T['text_muted']}; "
            f"font-size: 9px; margin-top: 2px; background: transparent;"
        )
        return lbl
