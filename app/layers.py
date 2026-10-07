"""
Unified Scene & Layer management panel.

Single panel replacing the old separate Scene + Layers tabs.
Objects (sprite, texture, stack) at the top level; their layers/slices
as children.  All CRUD operations (add, remove, rename, reorder,
duplicate, merge, visibility, opacity, blend mode, type conversion)
in one place.

Styled with Aseprite dark-theme tokens from app.theme, with improved
text size, icon visibility, and contrast.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QSlider, QMenu, QAction, QInputDialog,
    QAbstractItemView, QComboBox, QToolButton, QFrame, QMessageBox,
    QSizePolicy, QHeaderView,
)
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QImage, QFont
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from app.theme import (T as _T, FONT_FAMILY, FONT_SIZE, ACCENT, TEXT, TEXT_MUTED,
                        TEXT_BRIGHT, BG_PANEL, BG_INPUT, BG_RAISED, BG_HEADER,
                        BORDER, BORDER_LIGHT, BORDER_DARK)


# ─────────────────────────────────────────────────────────────────
# Icon helpers
# ─────────────────────────────────────────────────────────────────

def _icon(text, fg=TEXT, bg="transparent", size=20):
    """Render a single-glyph icon as a QIcon."""
    pix = QPixmap(size, size)
    pix.fill(QColor(bg) if bg != "transparent" else Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QColor(fg))
    f = QFont(FONT_FAMILY, int(size * 0.55))
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 0, size, size, Qt.AlignCenter, text)
    p.end()
    return QIcon(pix)


def _colored_badge(text, fg, size=18):
    """A small colored text badge as QIcon (for type indicators)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QColor(fg))
    f = QFont(FONT_FAMILY, int(size * 0.6))
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 0, size, size, Qt.AlignCenter, text)
    p.end()
    return QIcon(pix)


# ─────────────────────────────────────────────────────────────────
# Blend modes
# ─────────────────────────────────────────────────────────────────

BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay", "Add",
               "Darken", "Lighten", "Difference", "Exclusion"]


# ─────────────────────────────────────────────────────────────────
# Type icon / glyph maps
# ─────────────────────────────────────────────────────────────────

_TYPE_GLYPHS  = {"stack": "S", "sprite": "P", "texture": "T"}
_TYPE_COLORS  = {"stack": _T["accent"], "sprite": _T["green"], "texture": _T["yellow"]}


def _type_icon(obj_type):
    return _colored_badge(
        _TYPE_GLYPHS.get(obj_type, "?"),
        _TYPE_COLORS.get(obj_type, _T["text"]),
    )


def _vis_icon(visible):
    if visible:
        return _icon("o", _T["accent"])
    return _icon("-", _T["text_dim"])


# ─────────────────────────────────────────────────────────────────
# Stylesheet fragments  (improved contrast & size)
# ─────────────────────────────────────────────────────────────────

_BTN = f"""
QPushButton {{
    background: {_T['bg_input']};
    border: 1px solid {_T['border']};
    color: {_T['text']};
    font-family: "{FONT_FAMILY}";
    font-size: 11px;
    padding: 4px 8px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: {_T['bg_header']};
    color: {_T['text_bright']};
    border-color: {_T['border_light']};
}}
QPushButton:pressed {{ background: {_T['bg_input']}; }}
QPushButton:disabled {{
    color: {_T['text_dim']};
    border-color: {_T['border_dark']};
    background: {_T['bg_panel']};
}}
"""

_BTN_ACCENT = f"""
QPushButton {{
    background: {_T['bg_input']};
    border: 1px solid {_T['green']};
    color: {_T['green']};
    font-family: "{FONT_FAMILY}";
    font-size: 11px;
    font-weight: bold;
    padding: 4px 8px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {_T['bg_header']}; border-color: {_T['green']}; color: {_T['text_bright']}; }}
QPushButton:pressed {{ background: {_T['bg_input']}; }}
"""

_BTN_DEL = f"""
QPushButton {{
    background: {_T['bg_input']};
    border: 1px solid {_T['red']};
    color: {_T['red']};
    font-family: "{FONT_FAMILY}";
    font-size: 11px;
    padding: 4px 8px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {_T['bg_header']}; border-color: {_T['red']}; color: {_T['text_bright']}; }}
QPushButton:pressed {{ background: {_T['bg_input']}; }}
QPushButton:disabled {{
    color: {_T['text_dim']};
    border-color: {_T['border_dark']};
    background: {_T['bg_panel']};
}}
"""

_CONTEXT_MENU = f"""
QMenu {{
    background: {_T['bg_panel']};
    border: 1px solid {_T['border_light']};
    color: {_T['text']};
    font-family: "{FONT_FAMILY}";
    font-size: 11px;
}}
QMenu::item {{ padding: 6px 24px 6px 14px; }}
QMenu::item:selected {{
    background: {_T['accent_dim']};
    color: {_T['text_bright']};
}}
QMenu::separator {{
    height: 1px;
    background: {_T['border']};
    margin: 3px 0;
}}
"""

_TREE_STYLE = f"""
QTreeWidget {{
    background-color: {_T['bg_input']};
    color: {_T['text']};
    border: none;
    outline: none;
    font-family: "{FONT_FAMILY}";
    font-size: 11px;
}}
QTreeWidget::item {{
    padding: 4px 0;
    border-bottom: 1px solid {_T['border_dark']};
    min-height: 22px;
}}
QTreeWidget::item:selected {{
    background-color: {_T['accent_dim']};
    border-left: 3px solid {_T['accent']};
    color: {_T['text_bright']};
}}
QTreeWidget::item:hover:!selected {{
    background-color: {_T['bg_header']};
}}
QTreeWidget::branch {{
    background: {_T['bg_input']};
}}
QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:closed:has-children:has-siblings {{
    image: none;
    border-image: none;
}}
QTreeWidget::branch:open:has-children:!has-siblings,
QTreeWidget::branch:open:has-children:has-siblings {{
    image: none;
    border-image: none;
}}
QHeaderView::section {{
    background: {_T['bg_raised']};
    color: {_T['text_muted']};
    border: 1px solid {_T['border_dark']};
    font-family: "{FONT_FAMILY}";
    font-size: 10px;
    padding: 4px;
}}
"""

# Role constants for QTreeWidgetItem.data()
ROLE_TYPE      = Qt.UserRole       # "object" | "layer"
ROLE_OBJ_ID    = Qt.UserRole + 1
ROLE_LAYER_IDX = Qt.UserRole + 2


def _get_obj_attr(obj, attr, default=None):
    """Get attribute from SceneObject or dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _get_layer_attr(layer, attr, default=None):
    """Get attribute from LayerData or dict."""
    if isinstance(layer, dict):
        return layer.get(attr, default)
    return getattr(layer, attr, default)


# ─────────────────────────────────────────────────────────────────
# LayerPanel — unified Scene & Layer panel
# ─────────────────────────────────────────────────────────────────

class LayerPanel(QWidget):
    """
    Unified hierarchical scene tree: Objects -> Layers/Slices.

    Replaces the old separate Scene tab + Layers tab with a single
    panel that handles all object and layer CRUD operations.

    Layer signals (backward-compatible, apply to active object):
        layer_selected(int)
        layer_added(str)
        layer_removed(int)
        layer_moved(int, int)
        layer_visibility_changed(int, bool)
        layer_opacity_changed(int, int)
        layer_blend_mode_changed(int, str)
        layer_duplicated(int)
        layer_merged_down(int)
        merge_visible_requested()
        layer_renamed(int, str)
        layer_locked_changed(int, bool)
        flatten_requested()

    Object signals:
        object_selected(str)            -- object id
        object_add_requested(str)       -- object type
        object_remove_requested(str)    -- object id
        object_renamed(str, str)        -- object id, new name
        object_type_converted(str, str) -- object id, new type
    """

    # -- Layer signals --
    layer_selected           = pyqtSignal(int)
    layer_added              = pyqtSignal(str)
    layer_removed            = pyqtSignal(int)
    layer_moved              = pyqtSignal(int, int)
    layer_visibility_changed = pyqtSignal(int, bool)
    layer_opacity_changed    = pyqtSignal(int, int)
    layer_blend_mode_changed = pyqtSignal(int, str)
    layer_duplicated         = pyqtSignal(int)
    layer_merged_down        = pyqtSignal(int)
    merge_visible_requested  = pyqtSignal()
    layer_renamed            = pyqtSignal(int, str)
    layer_locked_changed     = pyqtSignal(int, bool)
    flatten_requested        = pyqtSignal()

    # -- Object signals --
    object_selected          = pyqtSignal(str)
    object_add_requested     = pyqtSignal(str)
    object_remove_requested  = pyqtSignal(str)
    object_renamed           = pyqtSignal(str, str)
    object_type_converted    = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(250)
        self.setStyleSheet(f"background: {_T['bg_panel']}; color: {_T['text']};")

        self._names       = []
        self._visible     = []
        self._opacity     = []
        self._locked      = []
        self._blend_modes = []
        self._active_obj_id = None
        self._refreshing  = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_tree(), stretch=1)
        layout.addWidget(self._build_controls_frame())
        layout.addWidget(self._build_button_frame())

    # ──────────────────────────────────────────────────────────────
    # UI builders
    # ──────────────────────────────────────────────────────────────

    def _build_header(self):
        frame = QFrame()
        frame.setFixedHeight(32)
        frame.setStyleSheet(
            f"QFrame {{ background: {_T['bg_raised']}; "
            f"border-bottom: 1px solid {_T['border_dark']}; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 0, 8, 0)
        row.setSpacing(6)

        title = QLabel("SCENE")
        title.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 12px; font-weight: bold; "
            f"color: {_T['text_bright']}; letter-spacing: 0.12em; background: transparent;"
        )
        row.addWidget(title)
        row.addStretch()

        # Add-object dropdown
        self.add_obj_btn = QToolButton()
        self.add_obj_btn.setText("+")
        self.add_obj_btn.setToolTip("Add new object to scene")
        self.add_obj_btn.setFixedSize(24, 24)
        self.add_obj_btn.setPopupMode(QToolButton.InstantPopup)
        self.add_obj_btn.setStyleSheet(
            f"QToolButton {{ background: {_T['bg_input']}; border: 1px solid {_T['green']}; "
            f"color: {_T['green']}; font-size: 14px; font-weight: bold; }}"
            f"QToolButton:hover {{ background: {_T['bg_header']}; color: {_T['text_bright']}; }}"
            f"QToolButton::menu-indicator {{ image: none; }}"
        )
        add_menu = QMenu(self.add_obj_btn)
        add_menu.setStyleSheet(_CONTEXT_MENU)
        add_menu.addAction("New Stack").triggered.connect(
            lambda: self.object_add_requested.emit("stack"))
        add_menu.addAction("New Sprite").triggered.connect(
            lambda: self.object_add_requested.emit("sprite"))
        add_menu.addAction("New Texture").triggered.connect(
            lambda: self.object_add_requested.emit("texture"))
        self.add_obj_btn.setMenu(add_menu)
        row.addWidget(self.add_obj_btn)

        return frame

    def _build_tree(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Vis"])
        self.tree.setColumnCount(2)
        self.tree.setMinimumHeight(160)
        self.tree.setStyleSheet(_TREE_STYLE)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(False)
        self.tree.setIndentation(18)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.NoDragDrop)

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.resizeSection(1, 32)

        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        return self.tree

    def _build_controls_frame(self):
        """Opacity slider + blend mode combo in one compact frame."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {_T['bg_raised']}; "
            f"border-top: 1px solid {_T['border_dark']}; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(5)

        # Opacity row
        op_row = QHBoxLayout()
        op_row.setSpacing(8)

        op_label = QLabel("OPACITY")
        op_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 10px; "
            f"font-weight: bold; letter-spacing: 0.1em; color: {_T['text_muted']}; "
            f"background: transparent;"
        )
        op_label.setFixedWidth(58)
        op_row.addWidget(op_label)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 255)
        self.opacity_slider.setValue(255)
        self.opacity_slider.setStyleSheet(f"""
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
                background: {_T['accent']};
            }}
        """)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self.opacity_slider, 1)

        self.opacity_label = QLabel("100%")
        self.opacity_label.setFixedWidth(38)
        self.opacity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacity_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 11px; "
            f"color: {_T['accent']}; font-weight: bold; background: transparent;"
        )
        op_row.addWidget(self.opacity_label)
        layout.addLayout(op_row)

        # Blend row
        bl_row = QHBoxLayout()
        bl_row.setSpacing(8)

        bl_label = QLabel("BLEND")
        bl_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}'; font-size: 10px; "
            f"font-weight: bold; letter-spacing: 0.1em; color: {_T['text_muted']}; "
            f"background: transparent;"
        )
        bl_label.setFixedWidth(58)
        bl_row.addWidget(bl_label)

        self.blend_combo = QComboBox()
        self.blend_combo.addItems(BLEND_MODES)
        self.blend_combo.setToolTip("Layer blend mode")
        self.blend_combo.setStyleSheet(f"""
            QComboBox {{
                background: {_T['bg_input']};
                border: 1px solid {_T['border']};
                color: {_T['text']};
                font-family: "{FONT_FAMILY}";
                font-size: 11px;
                padding: 3px 20px 3px 6px;
                min-height: 18px;
            }}
            QComboBox:hover {{
                border-color: {_T['border_light']};
                color: {_T['text_bright']};
            }}
            QComboBox::drop-down {{ border: none; background: transparent; }}
            QComboBox::down-arrow {{ image: none; width: 0; }}
            QComboBox QAbstractItemView {{
                background: {_T['bg_panel']};
                color: {_T['text']};
                border: 1px solid {_T['border_light']};
                selection-background-color: {_T['accent_dim']};
                font-family: "{FONT_FAMILY}";
                font-size: 11px;
            }}
        """)
        self.blend_combo.currentTextChanged.connect(self._on_blend_mode_changed)
        bl_row.addWidget(self.blend_combo, 1)

        layout.addLayout(bl_row)
        return frame

    def _build_button_frame(self):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {_T['bg_raised']}; "
            f"border-top: 1px solid {_T['border_dark']}; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 5, 8, 6)
        layout.setSpacing(3)

        # Row 1 — Add Layer / Duplicate / Delete
        row1 = QHBoxLayout()
        row1.setSpacing(3)

        self.add_btn = QPushButton("+ Layer")
        self.add_btn.setToolTip("Add new layer/slice (Ctrl+Shift+N)")
        self.add_btn.setStyleSheet(_BTN_ACCENT)
        self.add_btn.clicked.connect(self._on_add_layer)
        row1.addWidget(self.add_btn)

        self.dup_btn = QPushButton("Dup")
        self.dup_btn.setToolTip("Duplicate layer")
        self.dup_btn.setStyleSheet(_BTN)
        self.dup_btn.clicked.connect(self._on_duplicate)
        row1.addWidget(self.dup_btn)

        self.remove_btn = QPushButton("Del")
        self.remove_btn.setToolTip("Delete selected layer or object")
        self.remove_btn.setStyleSheet(_BTN_DEL)
        self.remove_btn.clicked.connect(self._on_remove)
        row1.addWidget(self.remove_btn)

        layout.addLayout(row1)

        # Row 2 — Move Up / Move Down / Merge Down
        row2 = QHBoxLayout()
        row2.setSpacing(3)

        self.up_btn = QPushButton("Up")
        self.up_btn.setToolTip("Move layer up in stack")
        self.up_btn.setStyleSheet(_BTN)
        self.up_btn.clicked.connect(self._on_move_up)
        row2.addWidget(self.up_btn)

        self.down_btn = QPushButton("Down")
        self.down_btn.setToolTip("Move layer down in stack")
        self.down_btn.setStyleSheet(_BTN)
        self.down_btn.clicked.connect(self._on_move_down)
        row2.addWidget(self.down_btn)

        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setToolTip("Merge with layer below")
        self.merge_btn.setStyleSheet(_BTN)
        self.merge_btn.clicked.connect(self._on_merge_down)
        row2.addWidget(self.merge_btn)

        layout.addLayout(row2)

        # Row 3 — Merge Visible / Flatten
        row3 = QHBoxLayout()
        row3.setSpacing(3)

        self.merge_vis_btn = QPushButton("Merge Visible")
        self.merge_vis_btn.setToolTip("Merge all visible layers")
        self.merge_vis_btn.setStyleSheet(_BTN)
        self.merge_vis_btn.clicked.connect(self.merge_visible_requested.emit)
        row3.addWidget(self.merge_vis_btn, 2)

        self.flatten_btn = QPushButton("Flatten")
        self.flatten_btn.setToolTip("Flatten all layers into one")
        self.flatten_btn.setStyleSheet(_BTN)
        self.flatten_btn.clicked.connect(self._on_flatten)
        row3.addWidget(self.flatten_btn, 1)

        layout.addLayout(row3)
        return frame

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def refresh_layers(self, names, visible_list, opacity_list, active_idx,
                       thumbnails=None, locked_list=None, blend_list=None,
                       layer_types=None, objects=None, active_object_id=None):
        """
        Rebuild the tree.

        Parameters
        ----------
        objects : list[SceneObject] or None
            If provided, uses the SceneModel hierarchy for the tree.
            If None, falls back to a flat single-object tree.
        active_object_id : str or None
        names, visible_list, ... : flat layer arrays (for the *active* object)
        """
        n = len(names)
        # Ensure all auxiliary lists are exactly length n to avoid IndexError
        # after undo/redo when canvas lists may be out of sync.
        if locked_list is None:
            locked_list = [False] * n
        elif len(locked_list) < n:
            locked_list = list(locked_list) + [False] * (n - len(locked_list))
        if blend_list is None:
            blend_list = ["Normal"] * n
        elif len(blend_list) < n:
            blend_list = list(blend_list) + ["Normal"] * (n - len(blend_list))
        if layer_types is None:
            layer_types = ["slice"] * n
        elif len(layer_types) < n:
            layer_types = list(layer_types) + ["slice"] * (n - len(layer_types))

        self._names       = list(names)
        self._visible     = list(visible_list)
        self._opacity     = list(opacity_list)
        self._locked      = list(locked_list)
        self._blend_modes = list(blend_list)
        self._active_obj_id = active_object_id

        self._refreshing = True
        self.tree.clear()

        if objects:
            # ── Scene-model mode: object -> layer hierarchy ──
            for obj in objects:
                obj_item = QTreeWidgetItem()
                obj_type = _get_obj_attr(obj, "type") or _get_obj_attr(obj, "obj_type", "stack")
                obj_name = _get_obj_attr(obj, "name", "Object")
                obj_id = _get_obj_attr(obj, "id", "")
                obj_visible = _get_obj_attr(obj, "visible", True)
                type_tag = _TYPE_GLYPHS.get(obj_type, "?")
                obj_item.setText(0, f"[{type_tag}] {obj_name}")
                obj_item.setIcon(0, _type_icon(obj_type))
                obj_item.setText(1, "o" if obj_visible else "-")
                obj_item.setData(0, ROLE_TYPE, "object")
                obj_item.setData(0, ROLE_OBJ_ID, obj_id)
                obj_item.setFlags(obj_item.flags() | Qt.ItemIsEditable)

                # Bold font for objects
                obj_font = QFont(FONT_FAMILY, 10)
                obj_font.setBold(True)
                obj_item.setFont(0, obj_font)

                # Color the object name by type
                obj_item.setForeground(0, QColor(_TYPE_COLORS.get(obj_type, _T["text"])))

                is_active = (obj_id == active_object_id)

                # Build layer list
                layer_list = []
                if is_active:
                    for i in range(n):
                        layer_list.append((
                            names[i],
                            visible_list[i],
                            opacity_list[i],
                            locked_list[i],
                            blend_list[i],
                            thumbnails[i] if thumbnails and i < len(thumbnails) else None,
                        ))
                else:
                    obj_layers = _get_obj_attr(obj, "layers", [])
                    for ld in obj_layers:
                        layer_list.append((
                            _get_layer_attr(ld, "name", "Layer"),
                            _get_layer_attr(ld, "visible", True),
                            _get_layer_attr(ld, "opacity", 255),
                            _get_layer_attr(ld, "locked", False),
                            _get_layer_attr(ld, "blend_mode", "Normal"),
                            None,
                        ))

                # Layers in reverse (top layer first in tree)
                for i in range(len(layer_list) - 1, -1, -1):
                    lname, lvis, lop, llocked, lblend, thumb = layer_list[i]
                    child = QTreeWidgetItem()
                    pct = int(lop / 255 * 100)
                    lock_tag = " [L]" if llocked else ""
                    child.setText(0, f"  {lname}{lock_tag}")
                    child.setText(1, "o" if lvis else "-")
                    child.setData(0, ROLE_TYPE, "layer")
                    child.setData(0, ROLE_OBJ_ID, obj_id)
                    child.setData(0, ROLE_LAYER_IDX, i)
                    child.setToolTip(0, f"{lblend}  |  {pct}%{lock_tag}")

                    # Visibility column coloring
                    if lvis:
                        child.setForeground(1, QColor(_T["accent"]))
                    else:
                        child.setForeground(1, QColor(_T["text_dim"]))

                    # Thumbnail
                    if thumb and not thumb.isNull():
                        pix = QPixmap.fromImage(
                            thumb.scaled(20, 20, Qt.KeepAspectRatio, Qt.FastTransformation))
                        child.setIcon(0, QIcon(pix))

                    obj_item.addChild(child)

                self.tree.addTopLevelItem(obj_item)
                obj_item.setExpanded(is_active)

            # Select the active layer
            if active_object_id:
                self._select_layer_in_tree(active_object_id, active_idx)
        else:
            # ── Flat fallback (no scene model) ──
            obj_item = QTreeWidgetItem()
            obj_item.setText(0, "[P] Canvas")
            obj_item.setData(0, ROLE_TYPE, "object")
            obj_item.setData(0, ROLE_OBJ_ID, "__flat__")
            obj_font = QFont(FONT_FAMILY, 10)
            obj_font.setBold(True)
            obj_item.setFont(0, obj_font)

            for i in range(n - 1, -1, -1):
                child = QTreeWidgetItem()
                child.setText(0, f"  {names[i]}")
                child.setText(1, "o" if visible_list[i] else "-")
                child.setData(0, ROLE_TYPE, "layer")
                child.setData(0, ROLE_OBJ_ID, "__flat__")
                child.setData(0, ROLE_LAYER_IDX, i)
                if visible_list[i]:
                    child.setForeground(1, QColor(_T["accent"]))
                else:
                    child.setForeground(1, QColor(_T["text_dim"]))
                if thumbnails and i < len(thumbnails) and thumbnails[i]:
                    pix = QPixmap.fromImage(
                        thumbnails[i].scaled(20, 20, Qt.KeepAspectRatio, Qt.FastTransformation))
                    child.setIcon(0, QIcon(pix))
                obj_item.addChild(child)
            self.tree.addTopLevelItem(obj_item)
            obj_item.setExpanded(True)

            for ci in range(obj_item.childCount()):
                ch = obj_item.child(ci)
                if ch.data(0, ROLE_LAYER_IDX) == active_idx:
                    self.tree.setCurrentItem(ch)
                    break

        self._refreshing = False

        if 0 <= active_idx < n:
            self._sync_controls_to_layer(active_idx)
        self._update_button_states()

    def refresh_scene(self, objects, active_object_id, active_layer_idx,
                      canvas_names=None, canvas_visible=None, canvas_opacity=None,
                      canvas_locked=None, canvas_blend=None, canvas_thumbnails=None):
        """Higher-level refresh that takes SceneObjects directly."""
        if not canvas_names:
            canvas_names = []
        self.refresh_layers(
            names=canvas_names or [],
            visible_list=canvas_visible or [],
            opacity_list=canvas_opacity or [],
            active_idx=active_layer_idx,
            thumbnails=canvas_thumbnails,
            locked_list=canvas_locked,
            blend_list=canvas_blend,
            objects=objects,
            active_object_id=active_object_id,
        )

    def update_thumbnail(self, layer_idx: int, image: QImage):
        """Update a layer's thumbnail in the tree."""
        it = self.tree.invisibleRootItem()
        for oi in range(it.childCount()):
            obj_item = it.child(oi)
            for ci in range(obj_item.childCount()):
                child = obj_item.child(ci)
                if (child.data(0, ROLE_LAYER_IDX) == layer_idx and
                        child.data(0, ROLE_OBJ_ID) == self._active_obj_id):
                    if image and not image.isNull():
                        pix = QPixmap.fromImage(
                            image.scaled(20, 20, Qt.KeepAspectRatio, Qt.FastTransformation))
                        child.setIcon(0, QIcon(pix))
                    return

    def get_layer_count(self) -> int:
        return len(self._names)

    @property
    def layer_list(self):
        """Backward-compat alias."""
        return self.tree

    # ──────────────────────────────────────────────────────────────
    # Internal slots — tree interaction
    # ──────────────────────────────────────────────────────────────

    def _on_tree_selection(self):
        if self._refreshing:
            return
        items = self.tree.selectedItems()
        if not items:
            self._update_button_states()
            return
        item = items[0]
        role = item.data(0, ROLE_TYPE)
        obj_id = item.data(0, ROLE_OBJ_ID)

        if role == "object":
            self.object_selected.emit(obj_id)
        elif role == "layer":
            idx = item.data(0, ROLE_LAYER_IDX)
            if obj_id and obj_id != self._active_obj_id:
                self.object_selected.emit(obj_id)
            if isinstance(idx, int) and idx >= 0:
                self._sync_controls_to_layer(idx)
                self.layer_selected.emit(idx)
        self._update_button_states()

    def _on_tree_clicked(self, item, column):
        """Handle clicks on column 1 (visibility toggle)."""
        if column != 1:
            return
        role = item.data(0, ROLE_TYPE)
        if role == "layer":
            idx = item.data(0, ROLE_LAYER_IDX)
            if isinstance(idx, int) and 0 <= idx < len(self._visible):
                new_state = not self._visible[idx]
                self._visible[idx] = new_state
                item.setText(1, "o" if new_state else "-")
                if new_state:
                    item.setForeground(1, QColor(_T["accent"]))
                else:
                    item.setForeground(1, QColor(_T["text_dim"]))
                self.layer_visibility_changed.emit(idx, new_state)

    # ──────────────────────────────────────────────────────────────
    # Internal slots — controls
    # ──────────────────────────────────────────────────────────────

    def _on_opacity_changed(self, value: int):
        idx = self._get_selected_layer_idx()
        if idx < 0:
            return
        pct = int(value / 255 * 100)
        self.opacity_label.setText(f"{pct}%")
        self.layer_opacity_changed.emit(idx, value)

    def _on_blend_mode_changed(self, mode: str):
        idx = self._get_selected_layer_idx()
        if idx < 0:
            return
        self.layer_blend_mode_changed.emit(idx, mode)

    # ──────────────────────────────────────────────────────────────
    # Internal slots — buttons
    # ──────────────────────────────────────────────────────────────

    def _on_add_layer(self):
        name, ok = QInputDialog.getText(
            self, "New Layer", "Layer name:",
            text=f"Layer {len(self._names) + 1}"
        )
        if ok:
            name = name.strip() or f"Layer {len(self._names) + 1}"
            self.layer_added.emit(name)

    def _on_remove(self):
        item = self._selected_item()
        if not item:
            return
        role = item.data(0, ROLE_TYPE)
        if role == "object":
            obj_id = item.data(0, ROLE_OBJ_ID)
            if obj_id:
                reply = QMessageBox.question(
                    self, "Delete Object",
                    "Delete this object and all its layers?",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.object_remove_requested.emit(obj_id)
        elif role == "layer":
            idx = item.data(0, ROLE_LAYER_IDX)
            if isinstance(idx, int) and idx >= 0:
                if len(self._names) <= 1:
                    QMessageBox.information(self, "Cannot Delete",
                                            "At least one layer must remain.")
                    return
                self.layer_removed.emit(idx)

    def _on_duplicate(self):
        idx = self._get_selected_layer_idx()
        if idx >= 0:
            self.layer_duplicated.emit(idx)

    def _on_move_up(self):
        idx = self._get_selected_layer_idx()
        if idx >= 0 and idx < len(self._names) - 1:
            self.layer_moved.emit(idx, idx + 1)

    def _on_move_down(self):
        idx = self._get_selected_layer_idx()
        if idx > 0:
            self.layer_moved.emit(idx, idx - 1)

    def _on_merge_down(self):
        idx = self._get_selected_layer_idx()
        if idx > 0:
            self.layer_merged_down.emit(idx)

    def _on_flatten(self):
        if len(self._names) > 1:
            self.flatten_requested.emit()

    # ──────────────────────────────────────────────────────────────
    # Context menu
    # ──────────────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            # Right-click on empty area — offer to add object
            menu = QMenu(self)
            menu.setStyleSheet(_CONTEXT_MENU)
            add_menu = menu.addMenu("Add Object")
            add_menu.setStyleSheet(_CONTEXT_MENU)
            add_menu.addAction("New Stack").triggered.connect(
                lambda: self.object_add_requested.emit("stack"))
            add_menu.addAction("New Sprite").triggered.connect(
                lambda: self.object_add_requested.emit("sprite"))
            add_menu.addAction("New Texture").triggered.connect(
                lambda: self.object_add_requested.emit("texture"))
            menu.exec_(self.tree.mapToGlobal(pos))
            return

        role = item.data(0, ROLE_TYPE)
        menu = QMenu(self)
        menu.setStyleSheet(_CONTEXT_MENU)

        if role == "object":
            obj_id = item.data(0, ROLE_OBJ_ID)

            menu.addAction("Rename Object...").triggered.connect(
                lambda: self._rename_object(obj_id, item))
            menu.addSeparator()

            menu.addAction("Add Layer").triggered.connect(self._on_add_layer)
            menu.addSeparator()

            # Type conversion submenu
            convert_menu = menu.addMenu("Convert Type")
            convert_menu.setStyleSheet(_CONTEXT_MENU)
            for t in ["stack", "sprite", "texture"]:
                act = convert_menu.addAction(f"  {t.title()}")
                act.triggered.connect(
                    lambda checked, oid=obj_id, nt=t: self.object_type_converted.emit(oid, nt))

            menu.addSeparator()
            menu.addAction("Delete Object").triggered.connect(
                lambda: self.object_remove_requested.emit(obj_id))

        elif role == "layer":
            idx = item.data(0, ROLE_LAYER_IDX)

            menu.addAction("Rename...").triggered.connect(
                lambda: self._rename_layer(idx))

            vis = self._visible[idx] if idx < len(self._visible) else True
            vis_label = "Hide Layer" if vis else "Show Layer"
            menu.addAction(vis_label).triggered.connect(
                lambda: self.layer_visibility_changed.emit(idx, not vis))

            locked = self._locked[idx] if idx < len(self._locked) else False
            lock_label = "Unlock Layer" if locked else "Lock Layer"
            menu.addAction(lock_label).triggered.connect(
                lambda: self.layer_locked_changed.emit(idx, not locked))

            menu.addSeparator()
            menu.addAction("Duplicate").triggered.connect(
                lambda: self.layer_duplicated.emit(idx))

            merge_act = menu.addAction("Merge Down")
            merge_act.triggered.connect(lambda: self.layer_merged_down.emit(idx))
            merge_act.setEnabled(idx > 0)

            menu.addAction("Merge Visible").triggered.connect(
                self.merge_visible_requested.emit)

            menu.addSeparator()
            blend_menu = menu.addMenu("Blend Mode")
            blend_menu.setStyleSheet(_CONTEXT_MENU)
            cur_blend = self._blend_modes[idx] if idx < len(self._blend_modes) else "Normal"
            for mode in BLEND_MODES:
                act = blend_menu.addAction(("* " if mode == cur_blend else "  ") + mode)
                act.triggered.connect(
                    lambda checked, m=mode: self.layer_blend_mode_changed.emit(idx, m))

            menu.addSeparator()
            del_act = menu.addAction("Delete Layer")
            del_act.triggered.connect(lambda: self.layer_removed.emit(idx))
            del_act.setEnabled(len(self._names) > 1)

        menu.exec_(self.tree.mapToGlobal(pos))

    # ──────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────

    def _selected_item(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _get_selected_layer_idx(self) -> int:
        item = self._selected_item()
        if item and item.data(0, ROLE_TYPE) == "layer":
            idx = item.data(0, ROLE_LAYER_IDX)
            if isinstance(idx, int):
                return idx
        return -1

    def _selected_is_object(self) -> bool:
        item = self._selected_item()
        return item is not None and item.data(0, ROLE_TYPE) == "object"

    def _select_layer_in_tree(self, obj_id, layer_idx):
        """Select a specific layer in the tree."""
        root = self.tree.invisibleRootItem()
        for oi in range(root.childCount()):
            obj_item = root.child(oi)
            if obj_item.data(0, ROLE_OBJ_ID) == obj_id:
                for ci in range(obj_item.childCount()):
                    child = obj_item.child(ci)
                    if child.data(0, ROLE_LAYER_IDX) == layer_idx:
                        self.tree.setCurrentItem(child)
                        return

    def _sync_controls_to_layer(self, idx: int):
        opacity = self._opacity[idx] if idx < len(self._opacity) else 255
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(opacity)
        self.opacity_label.setText(f"{int(opacity / 255 * 100)}%")
        self.opacity_slider.blockSignals(False)

        blend = self._blend_modes[idx] if idx < len(self._blend_modes) else "Normal"
        self.blend_combo.blockSignals(True)
        combo_idx = self.blend_combo.findText(blend)
        if combo_idx >= 0:
            self.blend_combo.setCurrentIndex(combo_idx)
        self.blend_combo.blockSignals(False)

    def _update_button_states(self):
        idx   = self._get_selected_layer_idx()
        count = len(self._names)
        has   = idx >= 0

        self.remove_btn.setEnabled(has and count > 1 or self._selected_is_object())
        self.dup_btn.setEnabled(has)
        self.up_btn.setEnabled(has and idx < count - 1)
        self.down_btn.setEnabled(has and idx > 0)
        self.merge_btn.setEnabled(has and idx > 0)
        self.merge_vis_btn.setEnabled(count > 1)
        self.flatten_btn.setEnabled(count > 1)

    def _rename_object(self, obj_id, item):
        current = item.text(0).split("] ", 1)[-1] if item else "Object"
        text, ok = QInputDialog.getText(self, "Rename Object", "New name:",
                                        text=current)
        if ok and text.strip():
            self.object_renamed.emit(obj_id, text.strip())

    def _rename_layer(self, idx: int):
        current = self._names[idx] if idx < len(self._names) else ""
        text, ok = QInputDialog.getText(self, "Rename Layer", "New name:",
                                        text=current)
        if ok and text.strip():
            self.layer_renamed.emit(idx, text.strip())
