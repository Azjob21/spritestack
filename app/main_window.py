"""
Main application window - integrates all panels: canvas, tools, layers, palette,
timeline, 3D preview, export and menus.

Fixes over original:
- keyPressEvent defined only once - Escape + tool shortcuts both handled correctly
- _add_layer accepts the name str emitted by the updated layer_added(str) signal
- _toggle_layer_visibility uses the real emitted bool instead of always negating
- All new signals from fixed tools.py and layers.py properly connected:
    brush_hardness_changed, brush_opacity_changed, tolerance_changed,
    grid_toggled, onion_toggled, onion_frames_changed,
    layer_blend_mode_changed, merge_visible_requested
- hasattr guards replaced with clean unconditional connections
- _on_canvas_modified no longer calls full _refresh_layers on every stroke;
  uses incremental update_thumbnail for the active layer instead
- opacity / blend / rename / lock / move all mark project as modified
- _move_layer saves undo state before moving
- 3D preview timer only fires when the 3D tab is visible and canvas was modified
- __import__ hack replaced with canvas.reset_undo() method call
- inspect.signature sniffing in _refresh_layers removed
- _flatten_layers resets blend_modes list on canvas
- canvas.layer_blend_modes list initialised everywhere layers are created
- Resize canvas dialog gains an Anchor control (Top-Left / Center / Bottom-Right)
- _merge_visible_layers handler implemented
- Recent files menu (up to 8 entries) with QSettings persistence
- Shortcuts dialog updated with F / O / rect_fill / circle_fill keys
- _new_project unsaved-changes guard added (was missing)

Further fixes in this revision:
1.  canvas.frame_changed signal connected → frame_label updates whenever
    the canvas itself triggers frame changes (add/delete/insert/move frame).
2.  Space key play/pause: the QAction shortcut is shadowed by the canvas
    widget's StrongFocus policy - Space now handled directly in
    MainWindow.keyPressEvent so it always works regardless of focus.
3.  _toggle_play() was calling btn.toggle() then timeline._toggle_play() -
    btn.toggle() would itself emit clicked → double-fire.  Rewritten to call
    the public timeline.toggle_play() method (falls back to the internal one
    with signal-blocking if needed).
4.  tools.py center_object_clicked signal connected to canvas.center_layer_content.
    "Centre Object" also added to Layer menu (Ctrl+Shift+C) and shortcuts dialog.
5.  canvas.resize_canvas only accepts (w, h); the anchor offset was silently
    dropped by the try/except.  _resize_canvas() now manually blits existing
    content at the correct offset onto a fresh canvas - anchor actually works.
6.  Window geometry and splitter state saved to QSettings and restored on startup.
7.  _refresh_timer moved to __init__ - no longer re-created on every paint stroke.
8.  All new signals from the updated timeline.py connected:
      frame_inserted_before, frame_inserted_after, frame_moved, frame_cleared,
      onion_skin_changed, playback_mode_changed, loop_range_changed,
      frame_duration_changed.
9.  _new_project resets canvas.pivot to (w//2, h//2) to match new canvas.
10. After load_project the canvas pivot is synced to the 3D preview panel.
11. _import uses dlg.import_mode string attribute (from updated ImportDialog)
    instead of fragile type_combo index comparison.
12. _import_layer_strip dialog now asks Horizontal or Vertical, matching the
    new strip_direction option added to ExportDialog.
13. Shortcuts dialog updated with: Centre Object, Lasso, Gradient Fill.
"""

import os
import sys
import uuid
import json
import string
from pathlib import Path
import numpy as np

from PyQt5.QtCore import Qt, QSettings, QTimer, QSize, QByteArray, QUrl
from PyQt5.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWidgets import (
    QAbstractItemView, QAction, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMenuBar,
    QMessageBox, QShortcut, QSizePolicy, QSpinBox, QSplitter, QStatusBar,
    QTabWidget, QToolBar, QVBoxLayout, QWidget, QFrame, QPushButton, QGridLayout,
    QStackedWidget, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QDoubleSpinBox, QPlainTextEdit, QScrollArea,
)

from app.canvas import PixelCanvas
from app.export import ExportDialog, ImportDialog
from app.layers import LayerPanel
from app.scene_model import (
    SceneManager, Scene, SceneObject, LayerData, ObjectPlacement,
    OBJECT_TYPE_STACK, OBJECT_TYPE_SPRITE, OBJECT_TYPE_TEXTURE,
    _new_object_id, _new_scene_id,
    parse_ai_scene_payload, apply_ai_scene_layout,
)
from app.scene_ui import SceneUIPanel
from app.palette import ColorPalettePanel
from app.preview3d import Preview3DPanel
from app.ai_gen_panel import AIGenPanel
from app.ai_chat_panel import AIChatPanel
from app.sandbox_stage import SandboxStage
from app.project import PROJECT_EXTENSION, load_project, save_project
from app.stack3d import (
    apply_texture_to_layers,
    create_primitive_stack,
    export_stack_to_obj_mtl,
)
from app.timeline import TimelinePanel
from app.tools import ToolBar
from app.theme import ASEPRITE_STYLESHEET, T as _A

# ---------------------------------------------------------------------------
# Global dark stylesheet
# ---------------------------------------------------------------------------

DARK_STYLESHEET = ASEPRITE_STYLESHEET + f"""
/* ── Header (Aseprite-style compact bar) ─────────────── */
#TopHeader                    {{ background-color: {_A['bg_header']};
                                border-bottom: 1px solid {_A['border']}; }}
#LogoMark                     {{ background: transparent; }}
#LogoCell                     {{ min-width: 5px; min-height: 5px;
                                max-width: 5px; max-height: 5px; }}
#HeaderBrand                  {{ color: {_A['text_bright']}; font-family: "{_A['font']}";
                                font-size: 11pt; letter-spacing: 0.04em; font-weight: bold; }}
#HeaderSubtext                {{ color: {_A['text_muted']}; font-family: "{_A['font']}";
                                font-size: {_A['font_size']}pt; }}
#WorkspaceToggle              {{ background: {_A['bg_raised']}; color: {_A['text_muted']};
                                border: 1px solid {_A['border']};
                                padding: 2px 8px;
                                font-family: "{_A['font']}"; font-size: {_A['font_size']}pt; }}
#WorkspaceToggle:hover        {{ background: {_A['bg_header']}; border-color: {_A['border_light']}; color: {_A['text']}; }}
#WorkspaceToggle:checked      {{ background: {_A['accent']}; border-color: {_A['accent']}; color: {_A['text_bright']}; }}
#HeaderIconButton             {{ background-color: {_A['bg_raised']};
                                border: 1px solid {_A['border']};
                                color: {_A['text']};
                                font-family: "{_A['font']}"; font-size: {_A['font_size']}pt;
                                min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
#HeaderIconButton:hover       {{ background-color: {_A['bg_header']}; color: {_A['text_bright']};
                                border-color: {_A['border_light']}; }}
#HeaderIconButton:pressed     {{ background-color: {_A['bg_input']}; }}
#PublishButton                {{ color: {_A['text_bright']};
                                border: 1px solid {_A['green']};
                                background: {_A['green']};
                                padding: 2px 14px;
                                font-family: "{_A['font']}"; font-size: {_A['font_size']}pt;
                                font-weight: bold; }}
#PublishButton:hover          {{ background: #60d090; }}
#PublishButton:pressed        {{ background: #40a060; }}
#LoginButton                  {{ color: {_A['text_bright']};
                                border: 1px solid {_A['red']};
                                background: {_A['red']};
                                padding: 2px 12px;
                                font-family: "{_A['font']}"; font-size: {_A['font_size']}pt;
                                font-weight: bold; }}
#LoginButton:hover            {{ background: #f06070; }}
#LoginButton:pressed          {{ background: #c04050; }}
QPushButton[flat="true"]     {{ color: {_A['text_on_dark']}; }}
QLabel                       {{ color: {_A['text']}; }}
QTabBar::tab                 {{ color: {_A['text']}; }}
QTabBar::tab:selected        {{ color: {_A['text_bright']}; }}
"""

_MAX_RECENT = 8  # maximum recent-file entries to store


# ---------------------------------------------------------------------------
# Helper: build a blank layer stack dict from raw canvas attributes
# ---------------------------------------------------------------------------

def _blank_layer_stack(canvas, width, height, count):
    """Reset canvas layer arrays to a fresh stack of `count` transparent layers."""
    canvas.canvas_width  = width
    canvas.canvas_height = height
    canvas.layers            = []
    canvas.layer_names       = []
    canvas.layer_visible     = []
    canvas.layer_opacity     = []
    canvas.layer_locked      = []
    canvas.layer_types       = []
    canvas.layer_object_ids  = []
    # NOTE: Do NOT clear object_layers here - it's the global project object list
    canvas.layer_blend_modes = []          # FIX: always initialised
    for i in range(count):
        img = QImage(width, height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        canvas.layers.append(img)
        canvas.layer_names.append(f"Layer {i + 1}")
        canvas.layer_visible.append(True)
        canvas.layer_opacity.append(255)
        canvas.layer_locked.append(False)
        canvas.layer_types.append("slice")
        canvas.layer_object_ids.append(None)
        canvas.layer_blend_modes.append("Normal")
    canvas.active_layer = 0
    if hasattr(canvas, "sync_scene_metadata"):
        canvas.sync_scene_metadata()


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class NewCanvasDialog(QDialog):
    """Dialog for creating a new project.

    A project is a workspace that can contain multiple objects of different
    types (3D Stacks, Sprites, Textures).  The user picks a project name,
    a default canvas size, and adds one initial object to start with.
    More objects can be added later from the Scene panel or Sandbox workspace.
    """

    def __init__(self, parent=None, default_w=64, default_h=64):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)

        # --- Project info ---
        proj_group = QGroupBox("Project")
        proj_form = QFormLayout(proj_group)

        self.project_name_edit = QLineEdit("Untitled Project")
        self.project_name_edit.selectAll()
        proj_form.addRow("Project Name:", self.project_name_edit)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 1024)
        self.width_spin.setValue(default_w)
        proj_form.addRow("Canvas Width (px):", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 1024)
        self.height_spin.setValue(default_h)
        proj_form.addRow("Canvas Height (px):", self.height_spin)

        layout.addWidget(proj_group)

        # --- Initial object ---
        obj_group = QGroupBox("First Object")
        obj_form = QFormLayout(obj_group)

        self.object_name_edit = QLineEdit("Stack 1")
        obj_form.addRow("Object Name:", self.object_name_edit)

        self.object_type_combo = QComboBox()
        self.object_type_combo.addItems(["3D Stack", "Sprite", "Texture"])
        self.object_type_combo.currentTextChanged.connect(self._on_type_changed)
        obj_form.addRow("Object Type:", self.object_type_combo)

        self.initial_layers_spin = QSpinBox()
        self.initial_layers_spin.setRange(1, 256)
        self.initial_layers_spin.setValue(8)
        self.initial_layers_label = QLabel("Initial Slices:")
        obj_form.addRow(self.initial_layers_label, self.initial_layers_spin)

        hint = QLabel(
            "You can add more objects of any type later\n"
            "from the Scene panel or the Sandbox workspace."
        )
        hint.setStyleSheet("color: #7a7a8a; font-size: 8pt; margin-top: 4px;")
        obj_form.addRow(hint)

        layout.addWidget(obj_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create Project")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_type_changed(self, text: str):
        is_stack = (text == "3D Stack")
        self.initial_layers_label.setText(
            "Initial Slices:" if is_stack else "Initial Layers:"
        )
        self.initial_layers_spin.setValue(8 if is_stack else 1)
        # Auto-update the default object name
        mapping = {"3D Stack": "Stack 1", "Sprite": "Sprite 1", "Texture": "Texture 1"}
        self.object_name_edit.setText(mapping.get(text, "Object 1"))

    @property
    def project_name(self) -> str:
        return self.project_name_edit.text().strip() or "Untitled Project"

    @property
    def object_name(self) -> str:
        return self.object_name_edit.text().strip() or "Object 1"

    @property
    def object_type(self) -> str:
        mapping = {"3D Stack": "stack", "Sprite": "sprite", "Texture": "texture"}
        return mapping.get(self.object_type_combo.currentText(), "stack")

    @property
    def initial_layers(self) -> int:
        return self.initial_layers_spin.value()


class ResizeCanvasDialog(QDialog):
    """
    Dialog for resizing the canvas.
    FIX: adds an Anchor selector so users can choose where the existing
    content is placed inside the new dimensions (Top-Left / Centre / Bottom-Right).
    """

    ANCHORS = ["Top-Left", "Centre", "Bottom-Right"]

    def __init__(self, parent=None, current_w=64, current_h=64):
        super().__init__(parent)
        self.setWindowTitle("Resize Canvas")
        layout = QFormLayout(self)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 1024)
        self.width_spin.setValue(current_w)
        layout.addRow("New Width (px):", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 1024)
        self.height_spin.setValue(current_h)
        layout.addRow("New Height (px):", self.height_spin)

        self.anchor_combo = QComboBox()
        self.anchor_combo.addItems(self.ANCHORS)
        self.anchor_combo.setCurrentIndex(0)
        self.anchor_combo.setToolTip(
            "Where to place existing content in the resized canvas"
        )
        layout.addRow("Anchor:", self.anchor_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def anchor(self) -> str:
        return self.anchor_combo.currentText()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Main application window for SpriteStack Studio."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpriteStack Studio")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        self.project_path: str | None = None
        self.is_modified: bool = False
        self._canvas_dirty_for_3d: bool = False  # FIX: throttle 3D rebuilds
        self._preview_scene_scope: str = "ensemble"
        self._preview_focus_id: str | None = None
        self._refreshing: bool = False  # FIX: recursion guard for deferred refresh

        # Scene manager (handles multiple scenes with objects)
        self.scene_manager = SceneManager()
        # Create default scene
        default_scene = self.scene_manager.add_scene(name="Scene 1", description="Default scene")
        self._active_scene_id: str = default_scene.id

        # Per-object canvas state management
        self._object_canvas_data: dict = {}
        self._active_object_id: str | None = None

        self._settings = QSettings("SpriteStackStudio", "MainWindow")
        self._ai_network = QNetworkAccessManager(self)
        self._ai_tween_confidence_threshold = 0.65

        self._setup_ui()
        self._last_tool_id = "pencil"
        self._last_non_symmetry_tool = "pencil"
        self._suppress_tool_change = False
        self._setup_initial_object()  # Create initial object and add to scene
        self._setup_menus()
        self._connect_signals()
        self._refresh_all()

        # Fix 7: create coalescing timer at startup, not lazily per stroke
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._deferred_refresh)

        # Fix 6: restore window geometry and splitter state from last session
        if self._settings.contains("geometry"):
            self.restoreGeometry(self._settings.value("geometry"))
        if self._settings.contains("splitter_state"):
            self.main_splitter.restoreState(
                self._settings.value("splitter_state"))

        # FIX: 3D preview timer only fires when the 3D tab is active AND canvas
        # has actually changed - avoids 2 rebuilds/sec when nothing is dirty.
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._maybe_update_3d_preview)
        self.preview_timer.start(500)

        mode = self._settings.value("workspace_mode", "create")
        self._switch_workspace(mode if mode in ("create", "sandbox", "animate", "texture") else "create")

    # ------------------------------------------------------------------
    # Initial object setup
    # ------------------------------------------------------------------

    def _setup_initial_object(self):
        """Create an initial object and add it to the active scene.
        
        Called after _setup_ui() to ensure canvas exists but before signals
        are connected.
        """
        import uuid
        
        # Only setup if canvas has no objects yet
        if self.canvas.object_layers:
            return
            
        # Create initial object
        oid = f"obj_{uuid.uuid4().hex[:8]}"
        self.canvas.object_layers = [{
            "id": oid,
            "name": "Object 1",
            "type": "stack",
            "visible": True,
            "texture_layer_index": -1,
            "texture_enabled": False,
            "texture_tile_x": 1,
            "texture_tile_y": 1,
            "texture_strength": 100,
        }]
        
        # Add initial layer if none exist
        if not self.canvas.layers:
            self.canvas.layers = [QImage(self.canvas.canvas_width, 
                                         self.canvas.canvas_height, 
                                         QImage.Format_ARGB32)]
            self.canvas.layers[0].fill(Qt.transparent)
            self.canvas.layer_names = ["Slice 1"]
            self.canvas.layer_visible = [True]
            self.canvas.layer_opacity = [255]
            self.canvas.layer_locked = [False]
            self.canvas.layer_types = ["slice"]
            if hasattr(self.canvas, 'layer_blend_modes'):
                self.canvas.layer_blend_modes = ["Normal"]
        
        # Map all canvas layers to this object
        self.canvas.layer_object_ids = [oid] * len(self.canvas.layers)
        
        # Add placement to active scene
        active_scene = self.scene_manager.get_scene(self._active_scene_id)
        if active_scene and not active_scene.get_placement(oid):
            active_scene.add_object(
                object_id=oid,
                visible=True,
                offset_x=0.0,
                offset_y=0.0,
                offset_z=0.0,
                scale=1.0,
                rotation=0.0,
                opacity=255,
            )
        
        # Set this as the active object
        self._active_object_id = oid

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        # ── Central canvas area ────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_header())

        # Main splitter holds the central workspace stack
        self.main_splitter = QSplitter(Qt.Horizontal)

        # ── Left: narrow tool strip ────────────────────────────────
        self.tool_bar = ToolBar()
        self.main_splitter.addWidget(self.tool_bar)

        # ── Centre - canvas (creation mode) ────────────────────────
        center_widget = QWidget()
        center_widget.setStyleSheet(f"background-color: {_A['bg']};")
        self.creation_center_layout = QVBoxLayout(center_widget)
        self.creation_center_layout.setContentsMargins(0, 0, 0, 0)
        self.creation_center_layout.setSpacing(0)

        self.canvas = PixelCanvas(64, 64)
        if not hasattr(self.canvas, 'layer_blend_modes'):
            self.canvas.layer_blend_modes = ["Normal"] * len(self.canvas.layers)
        self.creation_center_layout.addWidget(self.canvas, 1)

        # Inline 3D preview overlay (stacked on top of canvas, hidden by default)
        from app.preview3d import Inline3DOverlay
        self.inline_3d_preview = Inline3DOverlay(center_widget)
        self.inline_3d_preview.setVisible(False)
        self._inline_3d_active = False

        # Toggle button: 2D ↔ 3D (top-left overlay)
        self._3d_toggle_btn = QPushButton("3D", center_widget)
        self._3d_toggle_btn.setFixedSize(36, 24)
        self._3d_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_A['bg_panel']}; color: {_A['text']};
                border: 1px solid {_A['border']};
                font-size: 10px; font-weight: bold;
            }}
            QPushButton:checked {{
                background: {_A['accent']}; color: #fff;
            }}
        """)
        self._3d_toggle_btn.setCheckable(True)
        self._3d_toggle_btn.setToolTip("Toggle inline 3D stack preview")
        self._3d_toggle_btn.clicked.connect(self._toggle_inline_3d)
        self._3d_toggle_btn.move(8, 8)
        self._3d_toggle_btn.raise_()

        # Axis toggle button (top-left, below 3D toggle)
        self._axis_toggle_btn = QPushButton("+", center_widget)
        self._axis_toggle_btn.setFixedSize(36, 24)
        self._axis_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_A['bg_panel']}; color: {_A['text']};
                border: 1px solid {_A['border']};
                font-size: 12px;
            }}
            QPushButton:checked {{
                background: #2a5a2a; color: #7f7;
            }}
        """)
        self._axis_toggle_btn.setCheckable(True)
        self._axis_toggle_btn.setToolTip("Toggle axis plane visibility (green/red)")
        self._axis_toggle_btn.clicked.connect(self._toggle_axis_planes)
        self._axis_toggle_btn.move(8, 36)
        self._axis_toggle_btn.raise_()

        self.timeline = TimelinePanel()
        self.main_splitter.addWidget(center_widget)

        # ── Right: tabbed panels (Scene + Palette + 3D Preview) ──
        self.right_tabs = QTabWidget()
        self.right_tabs.setMinimumWidth(250)

        # Unified Scene/Layer panel (replaces old separate Scene + Layers tabs)
        self.layer_panel = LayerPanel()
        self.layer_panel.setVisible(True)
        self.right_tabs.addTab(self.layer_panel, "Scene")

        # Palette tab
        self.palette_panel = ColorPalettePanel()
        self.right_tabs.addTab(self.palette_panel, "Palette")

        self.ai_gen_panel = AIGenPanel()
        self.right_tabs.addTab(self.ai_gen_panel, "Generate")

        self.ai_chat_panel = AIChatPanel()
        self.right_tabs.addTab(self.ai_chat_panel, "AI Chat")

        # 3D preview panel kept headless (not a tab).
        # Full 3D controls live in the Stack workspace.
        self.preview_panel = Preview3DPanel()

        self.right_tabs.currentChanged.connect(self._on_tab_changed)
        self.main_splitter.addWidget(self.right_tabs)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([46, 900, 280])

        self.creation_workspace = QWidget()
        cws_layout = QVBoxLayout(self.creation_workspace)
        cws_layout.setContentsMargins(0, 0, 0, 0)
        cws_layout.setSpacing(0)
        cws_layout.addWidget(self.main_splitter)

        self.stack_workspace = self._build_sandbox_workspace()
        self.animate_workspace = self._build_animate_workspace()
        self.texture_workspace = self._build_texture_workspace()

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self.creation_workspace)
        self.workspace_stack.addWidget(self.stack_workspace)
        self.workspace_stack.addWidget(self.animate_workspace)
        self.workspace_stack.addWidget(self.texture_workspace)
        
        # FIX: Connect workspace stack change to stop/start 3D timer
        self.workspace_stack.currentChanged.connect(self._on_workspace_changed)
        
        root.addWidget(self.workspace_stack)

        # ── Status bar (Aseprite style) ────────────────────────────
        _sb_item_style = (
            f"color: {_A['text_muted']}; background: transparent; "
            f"font-family: '{_A['font']}'; font-size: {_A['font_size']}pt; "
            "padding: 0 2px;"
        )
        _sb_hi_style = (
            f"color: {_A['text']}; background: transparent; font-weight: bold; "
            f"font-family: '{_A['font']}'; font-size: {_A['font_size']}pt;"
        )

        def _sb_pair(prefix: str, init: str):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(3)
            lbl_pfx = QLabel(prefix)
            lbl_pfx.setStyleSheet(_sb_item_style)
            lbl_val = QLabel(init)
            lbl_val.setStyleSheet(_sb_hi_style)
            h.addWidget(lbl_pfx)
            h.addWidget(lbl_val)
            return w, lbl_val

        def _sb_sep():
            sep = QLabel("|")
            sep.setStyleSheet(
                f"color: {_A['border']}; background: transparent; "
                f"font-size: {_A['font_size']}pt; padding: 0 2px;"
            )
            return sep

        _tool_w,  self.tool_label  = _sb_pair("Tool:", "Pencil")
        _pos_w,   self.pos_label   = _sb_pair("Pos:", "-")
        _size_w,  self.size_label  = _sb_pair("Canvas:", "64 x 64")
        _frame_w, self.frame_label = _sb_pair("Frame:", "1 / 1")
        _zoom_w,  self.zoom_label  = _sb_pair("Zoom:", "8x")

        for item in (_tool_w, _sb_sep(), _pos_w, _sb_sep(), _size_w,
                     _sb_sep(), _frame_w, _sb_sep(), _zoom_w):
            self.statusBar().addWidget(item)

        _brand = QLabel("SpriteStack Studio  v2.4")
        _brand.setStyleSheet(
            f"color: {_A['text_dim']}; background: transparent; "
            f"font-family: '{_A['font']}'; font-size: {_A['font_size']}pt; "
            "margin-right: 8px;"
        )
        self.statusBar().addPermanentWidget(_brand)
        self.statusBar().showMessage("")

        QTimer.singleShot(100, self.canvas.fit_canvas)

    def _on_workspace_changed(self, index: int):
        """FIX: Start/stop 3D timer based on whether 3D is needed in current workspace."""
        current_mode = ["create", "sandbox", "animate", "texture"][index]
        needs_3d = current_mode in ("sandbox", "texture")
        
        if needs_3d and not self.preview_timer.isActive():
            self.preview_timer.start(500)
        elif not needs_3d and self.preview_timer.isActive():
            self.preview_timer.stop()
            # Also hide inline 3D if it was active
            if hasattr(self, '_inline_3d_active') and self._inline_3d_active:
                self._toggle_inline_3d(False)

    def _deferred_refresh(self):
        """FIX: Called ~150ms after the last canvas_modified; does the heavier work.
        Added recursion guard to prevent infinite loops."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_timeline()
            self._sync_sandbox_workspace_from_canvas()
        finally:
            self._refreshing = False

    def _build_top_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("TopHeader")
        header.setFixedHeight(38)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)

        lay.addWidget(self._build_logo_mark())

        brand = QLabel("SPRITESTACK STUDIO")
        brand.setObjectName("HeaderBrand")
        lay.addWidget(brand)

        sub = QLabel("retro voxel editor")
        sub.setObjectName("HeaderSubtext")
        lay.addWidget(sub)

        lay.addSpacing(6)
        lay.addWidget(self._header_icon_button("NEW",  "New project", _A['accent'], self._new_project))
        lay.addWidget(self._header_icon_button("SAVE", "Save project", _A['green'], self._save_project))
        self.ws_create_btn = QPushButton("Create")
        self.ws_create_btn.setObjectName("WorkspaceToggle")
        self.ws_create_btn.setCheckable(True)
        self.ws_create_btn.setChecked(True)
        self.ws_create_btn.clicked.connect(lambda: self._switch_workspace("create"))
        lay.addWidget(self.ws_create_btn)
        self.ws_stack_btn = QPushButton("Sandbox")
        self.ws_stack_btn.setObjectName("WorkspaceToggle")
        self.ws_stack_btn.setCheckable(True)
        self.ws_stack_btn.clicked.connect(lambda: self._switch_workspace("sandbox"))
        lay.addWidget(self.ws_stack_btn)
        self.ws_animate_btn = QPushButton("Animate")
        self.ws_animate_btn.setObjectName("WorkspaceToggle")
        self.ws_animate_btn.setCheckable(True)
        self.ws_animate_btn.clicked.connect(lambda: self._switch_workspace("animate"))
        lay.addWidget(self.ws_animate_btn)
        self.ws_texture_btn = QPushButton("Texture")
        self.ws_texture_btn.setObjectName("WorkspaceToggle")
        self.ws_texture_btn.setCheckable(True)
        self.ws_texture_btn.clicked.connect(lambda: self._switch_workspace("texture"))
        lay.addWidget(self.ws_texture_btn)

        # ── Scene Management UI ─────────────────────────────────
        lay.addSpacing(12)
        scene_lbl = QLabel("SCENE:")
        scene_lbl.setStyleSheet(f"color: {_A['text_muted']}; font-family: '{_A['font']}'; font-size: {_A['font_size']}pt;")
        lay.addWidget(scene_lbl)

        self.scene_combo = QComboBox()
        self.scene_combo.setMinimumWidth(120)
        self.scene_combo.currentIndexChanged.connect(self._on_scene_changed)
        lay.addWidget(self.scene_combo)

        self.scene_add_btn = QPushButton("+")
        self.scene_add_btn.setFixedWidth(24)
        self.scene_add_btn.setToolTip("Add new scene")
        self.scene_add_btn.clicked.connect(self._add_new_scene)
        lay.addWidget(self.scene_add_btn)

        self.scene_dup_btn = QPushButton("D")
        self.scene_dup_btn.setFixedWidth(24)
        self.scene_dup_btn.setToolTip("Duplicate current scene")
        self.scene_dup_btn.clicked.connect(self._duplicate_current_scene)
        lay.addWidget(self.scene_dup_btn)

        self.scene_del_btn = QPushButton("-")
        self.scene_del_btn.setFixedWidth(24)
        self.scene_del_btn.setToolTip("Delete current scene")
        self.scene_del_btn.clicked.connect(self._delete_current_scene)
        lay.addWidget(self.scene_del_btn)

        self.scene_rename_btn = QPushButton("R")
        self.scene_rename_btn.setFixedWidth(24)
        self.scene_rename_btn.setToolTip("Rename current scene")
        self.scene_rename_btn.clicked.connect(self._rename_current_scene)
        lay.addWidget(self.scene_rename_btn)

        lay.addStretch(1)
        return header

    def _build_logo_mark(self) -> QWidget:
        logo = QWidget()
        logo.setObjectName("LogoMark")
        logo.setFixedSize(22, 22)
        grid = QGridLayout(logo)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        colors = [
            _A['accent'], _A['accent'], _A['text_muted'],
            _A['accent'], _A['accent'], _A['text_muted'],
            _A['text_muted'], _A['text_muted'], _A['accent'],
        ]
        idx = 0
        for r in range(3):
            for c in range(3):
                cell = QFrame()
                cell.setObjectName("LogoCell")
                cell.setStyleSheet(f"QFrame#LogoCell {{ background-color: {colors[idx]}; }}")
                idx += 1
                grid.addWidget(cell, r, c)
        return logo

    def _header_icon_button(self, text: str, tip: str, accent: str, slot):
        btn = QPushButton(text)
        btn.setObjectName("HeaderIconButton")
        btn.setToolTip(tip)
        btn.setStyleSheet(
            f"QPushButton#HeaderIconButton {{ color: {accent}; }}"
            f"QPushButton#HeaderIconButton:hover {{ border-color: {accent}; color: {_A['text_bright']}; }}"
        )
        btn.clicked.connect(slot)
        return btn

    def _cloud_sync_stub(self):
        self.statusBar().showMessage("Cloud sync is not configured yet.", 2400)

    def _share_stub(self):
        self.statusBar().showMessage("Social share is not configured yet.", 2400)

    def _publish_stub(self):
        self.statusBar().showMessage("Publish pipeline is not configured yet.", 2400)

    def _login_stub(self):
        self.statusBar().showMessage("Login flow is not configured yet.", 2400)

    @staticmethod
    def _layer_type_for_object_type(object_type: str) -> str:
        if object_type == "sprite":
            return "sprite"
        if object_type == "texture":
            return "texture"
        return "slice"

    @staticmethod
    def _object_type_for_layer_type(layer_type: str) -> str:
        if layer_type == "sprite":
            return "sprite"
        if layer_type == "texture":
            return "texture"
        return "stack"

    def _get_canvas_object(self, object_id: str):
        return next((o for o in self.canvas.object_layers if o.get("id") == object_id), None)

    def _active_scene_object_ids(self) -> list[str]:
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if scene is None:
            return [
                o.get("id") for o in getattr(self.canvas, "object_layers", [])
                if isinstance(o, dict) and o.get("id")
            ]
        return [
            p.object_id for p in scene.placements
            if p.object_id
        ]

    def _objects_for_active_scene(self) -> list[dict]:
        object_map = {
            o.get("id"): o
            for o in getattr(self.canvas, "object_layers", [])
            if isinstance(o, dict) and o.get("id")
        }
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        objects = []
        for oid in self._active_scene_object_ids():
            if oid not in object_map:
                continue
            item = dict(object_map[oid])
            if scene:
                placement = scene.get_placement(oid)
                if placement:
                    item["visible"] = placement.visible
            objects.append(item)
        return objects

    def _object_meta(self, object_id: str) -> dict | None:
        return next(
            (o for o in getattr(self.canvas, "object_layers", [])
             if isinstance(o, dict) and o.get("id") == object_id),
            None,
        )

    def _ensure_object_defaults(self, obj: dict):
        if "type" not in obj or obj.get("type") not in ("stack", "sprite", "texture"):
            obj["type"] = "stack"
        obj.setdefault("visible", True)
        obj.setdefault("texture_layer_index", -1)
        obj.setdefault("texture_enabled", False)
        obj.setdefault("texture_tile_x", 1)
        obj.setdefault("texture_tile_y", 1)
        obj.setdefault("texture_strength", 100)

    # ------------------------------------------------------------------
    # Per-object canvas state management
    # ------------------------------------------------------------------

    def _rebuild_scene_model_from_canvas(self):
        """
        Rebuild the SceneManager structure from the canvas's legacy metadata.
        Creates a default scene with placements for all global objects.
        Called after loading a project file.
        """
        # Create SceneManager with one default scene
        self.scene_manager = SceneManager()
        scene = self.scene_manager.add_scene(name="Default Scene")
        self._active_scene_id = scene.id
        self._object_canvas_data.clear()

        # Add placements for all global objects found in canvas.object_layers
        for obj_meta in getattr(self.canvas, 'object_layers', []):
            if isinstance(obj_meta, dict) and "id" in obj_meta:
                oid = obj_meta.get("id")
                # Create a default placement for this object in the scene
                scene.add_object(
                    object_id=oid,
                    visible=obj_meta.get("visible", True),
                    offset_x=0.0,
                    offset_y=0.0,
                    offset_z=0.0,
                    scale=1.0,
                    rotation=0.0,
                    opacity=255,
                )

    def _save_canvas_to_object(self, oid):
        """Persist current canvas state into the per-object dictionary and SceneManager."""
        if not oid:
            return
        self.canvas.save_current_frame()
        self._object_canvas_data[oid] = {
            "canvas_width":  self.canvas.canvas_width,
            "canvas_height": self.canvas.canvas_height,
            "layers":        [l.copy() for l in self.canvas.layers],
            "layer_names":   list(self.canvas.layer_names),
            "layer_visible": list(self.canvas.layer_visible),
            "layer_opacity": list(self.canvas.layer_opacity),
            "layer_locked":  list(self.canvas.layer_locked),
            "layer_types":   list(self.canvas.layer_types),
            "layer_object_ids": list(self.canvas.layer_object_ids),
            "layer_blend_modes": list(getattr(self.canvas, 'layer_blend_modes',
                                              ["Normal"] * len(self.canvas.layers))),
            "frames":        [[l.copy() for l in fr] for fr in self.canvas.frames],
            "current_frame": self.canvas.current_frame,
            "active_layer":  self.canvas.active_layer,
        }
        # Also sync into SceneManager's active scene (placements only store transforms)
        scene = self.scene_manager.get_active_scene()
        if scene:
            placement = scene.get_placement(oid)
            if placement:
                # Placement only stores transform, not layer data
                # Layer data is stored in _object_canvas_data
                pass

    def _load_canvas_from_object(self, oid):
        """Load an object's canvas state into the live canvas widget."""
        data = self._object_canvas_data.get(oid)
        if not data:
            return False
        self.canvas.canvas_width  = data["canvas_width"]
        self.canvas.canvas_height = data["canvas_height"]
        self.canvas.layers        = [l.copy() for l in data["layers"]]
        self.canvas.layer_names   = list(data["layer_names"])
        self.canvas.layer_visible = list(data["layer_visible"])
        self.canvas.layer_opacity = list(data["layer_opacity"])
        self.canvas.layer_locked  = list(data["layer_locked"])
        self.canvas.layer_types   = list(data["layer_types"])
        self.canvas.layer_object_ids = list(data["layer_object_ids"])
        self.canvas.layer_blend_modes = list(data["layer_blend_modes"])
        self.canvas.frames        = [[l.copy() for l in fr] for fr in data["frames"]]
        self.canvas.current_frame = data["current_frame"]
        self.canvas.active_layer  = data["active_layer"]
        if hasattr(self.canvas, 'reset_undo'):
            self.canvas.reset_undo()
        self.canvas._checker_cache = None
        self.canvas.update()
        return True

    def _switch_to_object(self, new_oid):
        """Switch the canvas display to a different scene object."""
        if not new_oid or new_oid == self._active_object_id:
            return
        # Save current object state
        if self._active_object_id:
            self._save_canvas_to_object(self._active_object_id)
        # Load new object state
        if new_oid in self._object_canvas_data:
            self._load_canvas_from_object(new_oid)
        else:
            scene = self.scene_manager.get_active_scene()
            if scene and scene.get_placement(new_oid):
                self._load_scene_object_into_canvas(new_oid)
        self._active_object_id = new_oid
        # Update active scene's active object
        scene = self.scene_manager.get_active_scene()
        if scene:
            scene.active_object_id = new_oid
        self._refresh_layers()

    def _build_sandbox_workspace(self) -> QWidget:
        """
        Section B: sandbox – AI-populated level-design stage.
        """
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scene_ui_panel = SceneUIPanel()
        self.scene_ui_panel.scene_parsed.connect(self._on_scene_parsed)
        self.scene_ui_panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 2500))
        self.scene_ui_panel.get_left_context_callback = self._get_left_context_for_ui
        lay.insertWidget(0, self.scene_ui_panel)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(8)
        split.setChildrenCollapsible(True)
        lay.addWidget(split, 1)

        left = QWidget()
        left.setMinimumWidth(120)
        left.setStyleSheet(f"background:{_A['bg_panel']};border-right:1px solid {_A['border_dark']};")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(8, 8, 8, 8)
        lcol.setSpacing(6)
        lcol.addWidget(QLabel("SCENE"))
        for txt, cb in [
            ("New Object Layer", self._create_object_layer),
            ("Assign Slice -> Object", self._assign_active_slice_to_active_object),
            ("Detach Slice", self._detach_active_slice_from_object),
        ]:
            btn = QPushButton(txt)
            btn.clicked.connect(cb)
            lcol.addWidget(btn)

        lcol.addSpacing(6)
        lcol.addWidget(QLabel("VIEW"))
        self.sandbox_preview_toggle = QPushButton("Preview Map")
        self.sandbox_preview_toggle.setCheckable(True)
        self.sandbox_preview_toggle.setToolTip("Toggle between layout labels and sprite preview map")
        self.sandbox_preview_toggle.toggled.connect(self._toggle_sandbox_stage_preview)
        lcol.addWidget(self.sandbox_preview_toggle)
        for txt, cb in [
            ("Zoom In", lambda: self._zoom_sandbox_stage(1.25)),
            ("Zoom Out", lambda: self._zoom_sandbox_stage(0.8)),
            ("Reset Stage View", self._reset_sandbox_stage_view),
        ]:
            btn = QPushButton(txt)
            btn.clicked.connect(cb)
            lcol.addWidget(btn)

        lcol.addSpacing(6)
        lcol.addWidget(QLabel("EDIT"))
        for txt, cb in [
            ("Create Cube", lambda: self._create_primitive("cube")),
            ("Resize Active Slice", self._resize_active_slice),
            ("Export OBJ/MTL", self._export_obj_mtl),
        ]:
            btn = QPushButton(txt)
            btn.clicked.connect(cb)
            lcol.addWidget(btn)

        lcol.addStretch(1)
        split.addWidget(left)

        center = QWidget()
        center.setStyleSheet(f"background:{_A['bg']};")
        ccol = QVBoxLayout(center)
        ccol.setContentsMargins(0, 0, 0, 0)
        ccol.setSpacing(0)
        center_split = QSplitter(Qt.Vertical)
        center_split.setChildrenCollapsible(True)
        center_split.setHandleWidth(8)
        self.sandbox_scroll = QScrollArea()
        self.sandbox_scroll.setWidgetResizable(False)
        self.sandbox_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.sandbox_scroll.setStyleSheet(f"border:0px;background:{_A['bg']};")
        self.sandbox_stage = SandboxStage()
        self.sandbox_stage.show_grid = (self._settings.value("pref/show_grid", "true") == "true")
        self.sandbox_stage.object_moved.connect(self._on_stage_object_moved)
        self.sandbox_stage.object_selected.connect(self._on_stage_object_selected)
        self.sandbox_scroll.setWidget(self.sandbox_stage)
        center_split.addWidget(self.sandbox_scroll)

        transform_strip = QWidget()
        transform_strip.setMinimumHeight(96)
        transform_strip.setStyleSheet(f"background:{_A['bg_panel']};border-top:1px solid {_A['border_dark']};")
        tcol = QHBoxLayout(transform_strip)
        tcol.setContentsMargins(8, 8, 8, 8)
        tcol.setSpacing(8)
        self.stack_hierarchy = QTreeWidget()
        self.stack_hierarchy.setHeaderLabels(["Object", "Type"])
        self.stack_hierarchy.itemSelectionChanged.connect(self._on_stack_hierarchy_selected)
        self.stack_hierarchy.itemChanged.connect(self._on_stack_hierarchy_item_changed)
        self.stack_hierarchy.itemDoubleClicked.connect(self._on_stack_hierarchy_double_clicked)
        self.stack_hierarchy.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stack_hierarchy.customContextMenuRequested.connect(self._show_stack_hierarchy_context_menu)
        self.stack_hierarchy.setMaximumWidth(260)
        tcol.addWidget(self.stack_hierarchy, 1)

        insp_box = QGroupBox("OBJECT INSPECTOR")
        insp_layout = QVBoxLayout(insp_box)
        insp_layout.setContentsMargins(8, 8, 8, 8)
        insp_layout.setSpacing(6)
        self.obj_inspector_name = QLabel("No object selected")
        insp_layout.addWidget(self.obj_inspector_name)
        self.obj_inspector_visible = QCheckBox("Visible in Ensemble")
        self.obj_inspector_visible.toggled.connect(self._on_object_inspector_visible_toggled)
        insp_layout.addWidget(self.obj_inspector_visible)
        self.obj_inspector_rename_btn = QPushButton("Rename Object")
        self.obj_inspector_rename_btn.clicked.connect(self._rename_selected_object_from_inspector)
        insp_layout.addWidget(self.obj_inspector_rename_btn)
        self.obj_inspector_resize_btn = QPushButton("Resize All Slices...")
        self.obj_inspector_resize_btn.clicked.connect(self._resize_selected_object_slices)
        insp_layout.addWidget(self.obj_inspector_resize_btn)
        tcol.addWidget(insp_box, 1)

        tf_box = QGroupBox("TRANSFORM")
        tf_form = QFormLayout(tf_box)
        self.stack_tx = QDoubleSpinBox(); self.stack_tx.setRange(-4096, 4096)
        self.stack_ty = QDoubleSpinBox(); self.stack_ty.setRange(-4096, 4096)
        self.stack_scale = QDoubleSpinBox(); self.stack_scale.setRange(0.01, 100.0); self.stack_scale.setValue(1.0)
        self.stack_rot = QDoubleSpinBox(); self.stack_rot.setRange(-360, 360)
        self.stack_stage_w = QDoubleSpinBox(); self.stack_stage_w.setRange(0.1, 100.0); self.stack_stage_w.setDecimals(2); self.stack_stage_w.setSingleStep(0.5); self.stack_stage_w.setValue(12.0); self.stack_stage_w.setSuffix("%")
        self.stack_stage_h = QDoubleSpinBox(); self.stack_stage_h.setRange(0.1, 100.0); self.stack_stage_h.setDecimals(2); self.stack_stage_h.setSingleStep(0.5); self.stack_stage_h.setValue(12.0); self.stack_stage_h.setSuffix("%")
        self.stack_depth = QDoubleSpinBox(); self.stack_depth.setRange(-9999.0, 9999.0)
        self.stack_opacity = QSpinBox(); self.stack_opacity.setRange(0, 255); self.stack_opacity.setValue(255)
        tf_form.addRow("X", self.stack_tx)
        tf_form.addRow("Y", self.stack_ty)
        tf_form.addRow("W", self.stack_stage_w)
        tf_form.addRow("H", self.stack_stage_h)
        tf_form.addRow("Depth", self.stack_depth)
        tf_form.addRow("Scale", self.stack_scale)
        tf_form.addRow("Rotation", self.stack_rot)
        tf_form.addRow("Opacity", self.stack_opacity)
        self.stack_tx.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_ty.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_stage_w.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_stage_h.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_depth.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_scale.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_rot.valueChanged.connect(self._on_stack_transform_changed)
        self.stack_opacity.valueChanged.connect(self._on_stack_opacity_changed)
        tcol.addWidget(tf_box, 1)

        center_split.addWidget(transform_strip)
        center_split.setStretchFactor(0, 6)
        center_split.setStretchFactor(1, 1)
        center_split.setSizes([900, 150])
        ccol.addWidget(center_split, 1)
        split.addWidget(center)

        right = QWidget()
        right.setMinimumWidth(280)
        right.setStyleSheet(f"background:{_A['bg_panel']};border-left:1px solid {_A['border_dark']};")
        rcol = QVBoxLayout(right)
        rcol.setContentsMargins(8, 8, 8, 8)
        rcol.setSpacing(6)

        title = QLabel("Scene Objects")
        title.setStyleSheet(f"color:{_A['text_bright']};font-weight:bold;")
        rcol.addWidget(title)
        screen_control_row = QHBoxLayout()
        screen_label = QLabel("Level Width:")
        screen_label.setStyleSheet(f"color:{_A['text']};")
        self.screen_spin = QSpinBox()
        self.screen_spin.setRange(1, 5)
        self.screen_spin.setValue(1)
        self.screen_spin.setSuffix(" screen")
        self.screen_spin.valueChanged.connect(self._on_screens_changed)
        screen_control_row.addWidget(screen_label)
        screen_control_row.addWidget(self.screen_spin)
        rcol.addLayout(screen_control_row)
        self.sandbox_object_list = QListWidget()
        self.sandbox_object_list.itemClicked.connect(self._on_sandbox_object_item_clicked)
        rcol.addWidget(self.sandbox_object_list, 3)
        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self._delete_selected_placement)
        btn_row.addWidget(self.delete_btn)
        clear_btn = QPushButton("Clear Scene")
        clear_btn.clicked.connect(self._clear_sandbox_scene)
        btn_row.addWidget(clear_btn)
        rcol.addLayout(btn_row)

        self.sandbox_chat = AIChatPanel()
        self.sandbox_chat.input_edit.setPlaceholderText("Ask about scene layouts or prompt tips…")
        self.sandbox_chat.set_suggestions([
            "How do I place objects on the left?",
            "What syntax puts a tree behind a rock?",
            "Give me a dungeon room layout prompt",
            "How do I use x/y coordinates?",
        ])
        self.sandbox_chat.send_requested.connect(self._on_sandbox_chat_send)
        rcol.addWidget(self.sandbox_chat, 6)

        self.scene_tips_toggle = QPushButton("▸ Scene Prompt Tips")
        self.scene_tips_toggle.setCheckable(True)
        rcol.addWidget(self.scene_tips_toggle)
        self.scene_tips_frame = QFrame()
        tips_lay = QVBoxLayout(self.scene_tips_frame)
        tips_lay.setContentsMargins(0, 0, 0, 0)
        self.scene_tips_text = QPlainTextEdit()
        self.scene_tips_text.setReadOnly(True)
        self.scene_tips_text.setMaximumBlockCount(12)
        self.scene_tips_text.setFixedHeight(self.scene_tips_text.fontMetrics().lineSpacing() * 6 + 12)
        self.scene_tips_text.setPlainText(self._scene_prompt_tips_text())
        tips_lay.addWidget(self.scene_tips_text)
        self.scene_tips_frame.setVisible(False)
        self.scene_tips_toggle.toggled.connect(self._toggle_scene_tips)
        rcol.addWidget(self.scene_tips_frame)
        split.addWidget(right)

        split.setSizes([170, 820, 310])
        return root

    def _build_animate_workspace(self) -> QWidget:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top_bar = QFrame()
        top_bar.setStyleSheet(f"background:{_A['bg_header']};border-bottom:1px solid {_A['border']};")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(8, 6, 8, 6)
        top_lay.setSpacing(6)
        top_lay.addWidget(QLabel("Animate Target:"))
        self.animate_target_combo = QComboBox()
        self.animate_target_combo.currentIndexChanged.connect(self._on_animate_target_changed)
        top_lay.addWidget(self.animate_target_combo, 1)
        lay.addWidget(top_bar)

        # Splitter: tool_bar | canvas+timeline | right_tabs
        # tool_bar and right_tabs are reparented here by _mount_canvas_in_animate()
        self.animate_splitter = QSplitter(Qt.Horizontal)
        self.animate_splitter.setHandleWidth(8)
        self.animate_splitter.setChildrenCollapsible(True)

        self.animate_center = QWidget()
        self.animate_center.setStyleSheet(f"background:{_A['bg']};")
        self.animate_center_layout = QVBoxLayout(self.animate_center)
        self.animate_center_layout.setContentsMargins(0, 0, 0, 0)
        self.animate_center_layout.setSpacing(0)
        self.animate_splitter.addWidget(self.animate_center)

        lay.addWidget(self.animate_splitter, 1)
        return root

    def _build_texture_workspace(self) -> QWidget:
        """
        Section D: texturing workspace – apply pixel-art textures to voxel
        object facades.  UV mapping operates on a 128x128 pixel texture sheet.
        """
        root = QWidget()
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(8)
        split.setChildrenCollapsible(True)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(split)

        # ── Left: texture tools ─────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(160)
        left.setStyleSheet(
            f"background:{_A['bg_panel']};border-right:1px solid {_A['border_dark']};")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(8, 8, 8, 8)
        lcol.setSpacing(6)
        lcol.addWidget(QLabel("TEXTURE TOOLS"))

        # Face selection
        face_grp = QGroupBox("Facade Selection")
        face_lay = QVBoxLayout(face_grp)
        face_lay.setContentsMargins(6, 6, 6, 6)
        face_lay.setSpacing(4)
        self.tex_face_combo = QComboBox()
        self.tex_face_combo.addItems([
            "Front (+Z)", "Back (-Z)", "Left (-X)", "Right (+X)",
            "Top (+Y)", "Bottom (-Y)", "All Faces"
        ])
        self.tex_face_combo.currentIndexChanged.connect(self._on_tex_face_changed)
        face_lay.addWidget(self.tex_face_combo)
        self.tex_auto_face = QCheckBox("Auto-detect on click")
        self.tex_auto_face.setChecked(True)
        face_lay.addWidget(self.tex_auto_face)
        lcol.addWidget(face_grp)

        # Texture source
        src_grp = QGroupBox("Texture Source")
        src_lay = QVBoxLayout(src_grp)
        src_lay.setContentsMargins(6, 6, 6, 6)
        src_lay.setSpacing(4)
        self.tex_source_combo = QComboBox()
        self.tex_source_combo.addItems(["(None – solid colour)"])
        self._refresh_texture_sources()
        src_lay.addWidget(self.tex_source_combo)
        imp_btn = QPushButton("Import Texture...")
        imp_btn.clicked.connect(self._import_texture_for_workspace)
        src_lay.addWidget(imp_btn)
        lcol.addWidget(src_grp)

        # UV controls
        uv_grp = QGroupBox("UV Mapping  (128x128)")
        uv_lay = QFormLayout(uv_grp)
        uv_lay.setContentsMargins(6, 6, 6, 6)
        uv_lay.setSpacing(4)
        self.tex_tile_x = QSpinBox(); self.tex_tile_x.setRange(1, 32); self.tex_tile_x.setValue(1)
        self.tex_tile_y = QSpinBox(); self.tex_tile_y.setRange(1, 32); self.tex_tile_y.setValue(1)
        self.tex_offset_x = QSpinBox(); self.tex_offset_x.setRange(-128, 128); self.tex_offset_x.setValue(0)
        self.tex_offset_y = QSpinBox(); self.tex_offset_y.setRange(-128, 128); self.tex_offset_y.setValue(0)
        self.tex_rotation = QComboBox()
        self.tex_rotation.addItems(["0°", "90°", "180°", "270°"])
        self.tex_strength = QSpinBox()
        self.tex_strength.setRange(0, 100); self.tex_strength.setValue(100); self.tex_strength.setSuffix("%")
        uv_lay.addRow("Tile X", self.tex_tile_x)
        uv_lay.addRow("Tile Y", self.tex_tile_y)
        uv_lay.addRow("Offset X", self.tex_offset_x)
        uv_lay.addRow("Offset Y", self.tex_offset_y)
        uv_lay.addRow("Rotation", self.tex_rotation)
        uv_lay.addRow("Strength", self.tex_strength)
        lcol.addWidget(uv_grp)

        apply_btn = QPushButton("Apply Texture to Face")
        apply_btn.clicked.connect(self._apply_texture_to_face)
        lcol.addWidget(apply_btn)

        clear_btn = QPushButton("Clear Face Texture")
        clear_btn.clicked.connect(self._clear_face_texture)
        lcol.addWidget(clear_btn)

        lcol.addStretch(1)
        split.addWidget(left)

        # ── Centre: 3D preview with face highlight ──────────────
        center = QWidget()
        center.setStyleSheet(f"background:{_A['bg']};")
        ccol = QVBoxLayout(center)
        ccol.setContentsMargins(0, 0, 0, 0)
        ccol.setSpacing(0)
        self.tex_preview_panel = Preview3DPanel()
        ccol.addWidget(self.tex_preview_panel, 1)
        split.addWidget(center)

        # ── Right: UV sheet preview + object picker ─────────────
        right = QWidget()
        right.setMinimumWidth(180)
        right.setStyleSheet(
            f"background:{_A['bg_panel']};border-left:1px solid {_A['border_dark']};")
        rcol = QVBoxLayout(right)
        rcol.setContentsMargins(8, 8, 8, 8)
        rcol.setSpacing(6)

        rcol.addWidget(QLabel("OBJECT"))
        self.tex_object_combo = QComboBox()
        self.tex_object_combo.currentIndexChanged.connect(self._on_tex_object_changed)
        rcol.addWidget(self.tex_object_combo)

        rcol.addWidget(QLabel("UV MAP PREVIEW"))
        self.tex_uv_label = QLabel()
        self.tex_uv_label.setFixedSize(128, 128)
        self.tex_uv_label.setStyleSheet(
            f"background: #1a1a2e; border: 1px solid {_A['border']};")
        self.tex_uv_label.setAlignment(Qt.AlignCenter)
        self.tex_uv_label.setText("128x128")
        rcol.addWidget(self.tex_uv_label)

        rcol.addWidget(QLabel("TEXTURE PREVIEW"))
        self.tex_preview_label = QLabel()
        self.tex_preview_label.setFixedSize(128, 128)
        self.tex_preview_label.setStyleSheet(
            f"background: #1a1a2e; border: 1px solid {_A['border']};")
        self.tex_preview_label.setAlignment(Qt.AlignCenter)
        self.tex_preview_label.setText("No texture")
        rcol.addWidget(self.tex_preview_label)

        rcol.addStretch(1)
        split.addWidget(right)

        split.setSizes([230, 700, 220])
        return root

    def _switch_workspace(self, mode: str):
        if mode not in ("create", "sandbox", "animate", "texture"):
            mode = "create"
        self.current_workspace = mode
        self.ws_create_btn.setChecked(mode == "create")
        self.ws_stack_btn.setChecked(mode == "sandbox")
        self.ws_animate_btn.setChecked(mode == "animate")
        self.ws_texture_btn.setChecked(mode == "texture")
        if mode == "create":
            self._mount_canvas_in_creation()
            self.workspace_stack.setCurrentIndex(0)
        elif mode == "sandbox":
            self._mount_canvas_in_sandbox()
            self.workspace_stack.setCurrentIndex(1)
            QTimer.singleShot(50, self._update_sandbox_stage_size)
        elif mode == "animate":
            self._mount_canvas_in_animate()
            self.workspace_stack.setCurrentIndex(2)
        elif mode == "texture":
            self._mount_canvas_in_texture()
            self.workspace_stack.setCurrentIndex(3)
        self.menuBar().setVisible(True)
        self._settings.setValue("workspace_mode", mode)

        self._sync_sandbox_workspace_from_canvas()
        if mode in ("sandbox", "texture"):
            self._canvas_dirty_for_3d = True
            self._update_3d_preview()
            self._canvas_dirty_for_3d = False

    @staticmethod
    def _detach_widget(widget: QWidget):
        parent = widget.parentWidget()
        if parent is None:
            return
        lay = parent.layout()
        if lay is None:
            return
        lay.removeWidget(widget)

    def _mount_canvas_in_creation(self):
        self._detach_widget(self.canvas)
        self.creation_center_layout.insertWidget(0, self.canvas, 1)
        self.canvas.setVisible(True)
        self.timeline.setVisible(False)
        # Re-parent tool_bar and right_tabs back into main_splitter
        self.main_splitter.insertWidget(0, self.tool_bar)
        self.main_splitter.addWidget(self.right_tabs)
        self.tool_bar.setVisible(True)
        self.right_tabs.setVisible(True)
        self.main_splitter.setSizes([46, 900, 280])
        # Re-raise overlay buttons above the re-inserted canvas
        self._3d_toggle_btn.raise_()
        self._axis_toggle_btn.raise_()
        if self._inline_3d_active:
            self.inline_3d_preview.raise_()
            self._3d_toggle_btn.raise_()
            self._axis_toggle_btn.raise_()

    def _mount_canvas_in_sandbox(self):
        self.canvas.setVisible(False)
        self.timeline.setVisible(False)

    def _mount_canvas_in_animate(self):
        self._detach_widget(self.canvas)
        self._detach_widget(self.timeline)
        # Reparent tool_bar and right_tabs into animate splitter
        self.animate_splitter.insertWidget(0, self.tool_bar)
        self.animate_center_layout.addWidget(self.canvas, 1)
        self.animate_center_layout.addWidget(self.timeline, 0)
        self.animate_splitter.addWidget(self.right_tabs)
        self.tool_bar.setVisible(True)
        self.right_tabs.setVisible(True)
        self.canvas.setVisible(True)
        self.timeline.setVisible(True)
        self.animate_splitter.setSizes([46, 900, 280])
        self._rebuild_animate_targets()

    def _mount_canvas_in_texture(self):
        """Texture workspace: canvas hidden, 3D preview drives interaction."""
        self.canvas.setVisible(False)
        self.timeline.setVisible(False)
        # Refresh the texture workspace preview
        self._refresh_tex_workspace()
        self._rebuild_animate_targets()

    def _sync_sandbox_workspace_from_canvas(self):
        """Rebuild the sandbox hierarchy for the active scene only."""
        if not hasattr(self, "stack_hierarchy"):
            return
        
        # Save current object's canvas state before syncing
        if self._active_object_id:
            self._save_canvas_to_object(self._active_object_id)
        
        self._ensure_stack_node_state()
        self._syncing_stack_tree = True
        self.stack_hierarchy.clear()
        root = QTreeWidgetItem(["Scene", "Root"])
        root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
        self.stack_hierarchy.addTopLevelItem(root)

        # Get visibility from active scene placements
        scene = self.scene_manager.get_active_scene()
        placement_map = {}
        if scene:
            for p in scene.placements:
                placement_map[p.object_id] = p

        from collections import Counter as _Counter
        scene_objects = self._objects_for_active_scene()
        _name_counts = _Counter(
            o.get("name", "") for o in scene_objects
            if isinstance(o, dict)
        )

        # Build hierarchy from objects placed in the active scene.
        for obj in scene_objects:
            if not isinstance(obj, dict):
                continue
            oid = obj.get("id")
            if not oid:
                continue
            
            obj_name = obj.get("name", "Object")
            obj_type = obj.get("type", "stack")
            
            # Get visibility from placement or fallback to object
            placement = placement_map.get(oid)
            is_visible = placement.visible if placement else obj.get("visible", True)
            
            # Create object item
            type_tag = {"stack": "STK", "sprite": "SPR", "texture": "TEX"}.get(obj_type, "OBJ")
            _n = _name_counts.get(obj_name, 1)
            _count_suffix = f" (×{_n})" if _n > 1 else ""
            obj_item = QTreeWidgetItem([f"[{type_tag}] {obj_name}{_count_suffix}", "Object"])
            obj_item.setData(0, Qt.UserRole, oid)
            obj_item.setData(0, Qt.UserRole + 2, "object")
            obj_item.setFlags(obj_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            obj_item.setCheckState(0, Qt.Checked if is_visible else Qt.Unchecked)
            root.addChild(obj_item)
            
            # Get layer data for this object
            if oid == self._active_object_id:
                # Active object - use live canvas data
                layer_names = self.canvas.layer_names
                layer_visible = self.canvas.layer_visible
            elif oid in self._object_canvas_data:
                # Cached object data
                cached = self._object_canvas_data[oid]
                layer_names = cached.get("layer_names", [])
                layer_visible = cached.get("layer_visible", [])
            else:
                # No data yet - show placeholder
                layer_names = ["(No layers)"]
                layer_visible = [True]
            
            # Add layer children
            for i, lname in enumerate(layer_names):
                lvis = layer_visible[i] if i < len(layer_visible) else True
                child = QTreeWidgetItem([lname, "Slice" if obj_type == "stack" else "Layer"])
                child.setData(0, Qt.UserRole, i)
                child.setData(0, Qt.UserRole + 1, oid)  # Store object id for layer
                child.setData(0, Qt.UserRole + 2, "layer")
                child.setFlags(child.flags() | Qt.ItemIsSelectable)
                if not lvis:
                    child.setForeground(0, QColor("#6870A0"))
                obj_item.addChild(child)
            
            obj_item.setExpanded(oid == self._active_object_id)

        root.setExpanded(True)
        self._syncing_stack_tree = False
        
        if hasattr(self, "stack_preview_panel"):
            scene_items = self._build_scene_items_for_preview()
            self.stack_preview_panel.update_scene(
                scene_items,
                self._preview_scene_scope,
                self._preview_focus_id,
            )
            px, py = self.canvas.pivot
            self.stack_preview_panel.set_pivot(
                px / max(1, self.canvas.canvas_width),
                py / max(1, self.canvas.canvas_height),
            )
        self._sync_stack_controls_for_active_layer()
        self._sync_object_inspector()
        self._sync_sandbox_stage_from_active_scene()
        if hasattr(self, "animate_target_combo"):
            self._rebuild_animate_targets()

    def _rebuild_animate_targets(self):
        if not hasattr(self, "animate_target_combo"):
            return
        self.animate_target_combo.blockSignals(True)
        self.animate_target_combo.clear()
        # Populate from objects placed in the active scene.
        scene = self.scene_manager.get_active_scene()
        scene_objects = self._objects_for_active_scene()
        if scene_objects:
            for obj_meta in scene_objects:
                if isinstance(obj_meta, dict) and "id" in obj_meta:
                    tag = {"stack": "STK", "sprite": "SPR", "texture": "TEX"}.get(obj_meta.get("type", "stack"), "OBJ")
                    self.animate_target_combo.addItem(f"[{tag}] {obj_meta.get('name', 'Object')}", obj_meta.get("id"))
            # Use active placement from scene if available
            active_id = None
            if scene and scene.placements:
                for p in scene.placements:
                    if p.object_id == self._active_object_id:
                        active_id = p.object_id
                        break
            for ci in range(self.animate_target_combo.count()):
                if self.animate_target_combo.itemData(ci) == active_id:
                    self.animate_target_combo.setCurrentIndex(ci)
                    break
        else:
            # Fallback: use canvas layer names
            for i, name in enumerate(self.canvas.layer_names):
                ltype = self.canvas.layer_types[i] if i < len(self.canvas.layer_types) else "slice"
                if ltype in ("slice", "sprite"):
                    tag = "OBJ" if ltype == "slice" else "SPR"
                    self.animate_target_combo.addItem(f"[{tag}] {name}", i)
            current = self.canvas.active_layer
            for ci in range(self.animate_target_combo.count()):
                if self.animate_target_combo.itemData(ci) == current:
                    self.animate_target_combo.setCurrentIndex(ci)
                    break
        self.animate_target_combo.blockSignals(False)

    def _on_animate_target_changed(self, _idx: int):
        if not hasattr(self, "animate_target_combo"):
            return
        data = self.animate_target_combo.currentData()
        if data is None:
            return
        # If data is an object ID string (scene path)
        if isinstance(data, str) and self.scene_manager:
            scene = self.scene_manager.get_active_scene()
            if scene:
                scene.active_object_id = data
            # Activate the first layer of that object in the canvas
            for i, oid in enumerate(self.canvas.layer_object_ids):
                if oid == data:
                    self.canvas.active_layer = i
                    break
            self._refresh_layers()
            return
        # Fallback: data is a layer index (legacy path)
        layer_idx = data
        if isinstance(layer_idx, int) and 0 <= layer_idx < len(self.canvas.layers):
            self.canvas.active_layer = layer_idx
            self._refresh_layers()

    def _on_stack_hierarchy_selected(self):
        items = self.stack_hierarchy.selectedItems()
        if not items:
            return
        item = items[0]
        role_type = item.data(0, Qt.UserRole + 2)
        if role_type == "object":
            # Track the selected object for transforms, but stay in ensemble view
            self._preview_focus_id = item.data(0, Qt.UserRole)
            # Only switch to focus mode on double-click (not single selection)
            # This allows users to see all objects while editing one's transforms
            self._update_3d_preview()
            self._sync_object_inspector()
            self._sync_stack_controls_for_active_layer()  # Sync transform controls for the selected object
            return
        idx = item.data(0, Qt.UserRole)
        if 0 <= idx < len(self.canvas.layers):
            self._activate_stack_layer(idx)
            if self._preview_scene_scope == "focus":
                self._preview_focus_active()
        self._sync_object_inspector()

    def _on_stack_hierarchy_double_clicked(self, item, column):
        """Double-click: toggle focus/ensemble view for the object"""
        role_type = item.data(0, Qt.UserRole + 2)
        if role_type == "object":
            oid = item.data(0, Qt.UserRole)
            if self._preview_scene_scope == "focus" and self._preview_focus_id == oid:
                # Already focused on this object - switch to ensemble
                self._preview_ensemble()
            else:
                # Focus on this object
                self._preview_scene_scope = "focus"
                self._preview_focus_id = oid
                self._update_3d_preview()

    def _activate_stack_layer(self, idx: int):
        if not (0 <= idx < len(self.canvas.layers)):
            return
        self.canvas.active_layer = idx
        if hasattr(self.layer_panel, '_select_layer_in_tree'):
            self.layer_panel._select_layer_in_tree(self._active_object_id, idx)
        self._sync_stack_controls_for_active_layer()

    def _on_stack_hierarchy_item_changed(self, item, column):
        if getattr(self, "_syncing_stack_tree", False):
            return
        if column != 0:
            return
        if item.data(0, Qt.UserRole + 2) != "object":
            return
        oid = item.data(0, Qt.UserRole)
        visible = (item.checkState(0) == Qt.Checked)
        
        # Update scene placement visibility (not global object visibility)
        scene = self.scene_manager.get_active_scene()
        if scene:
            placement = scene.get_placement(oid)
            if placement:
                placement.visible = visible
            else:
                # If no placement exists, create one
                scene.add_object(object_id=oid, visible=visible)
        
        # Also update global visibility as fallback
        for obj in getattr(self.canvas, "object_layers", []):
            if isinstance(obj, dict) and obj.get("id") == oid:
                obj["visible"] = visible
                break
        
        self._canvas_dirty_for_3d = True
        self._mark_modified()
        self._update_3d_preview()
        self._sync_sandbox_stage_from_active_scene()
        self._sync_object_inspector()

    def _selected_object_id_in_hierarchy(self):
        items = self.stack_hierarchy.selectedItems() if hasattr(self, "stack_hierarchy") else []
        if not items:
            return None
        item = items[0]
        if item.data(0, Qt.UserRole + 2) == "object":
            return item.data(0, Qt.UserRole)
        parent = item.parent()
        if parent and parent.data(0, Qt.UserRole + 2) == "object":
            return parent.data(0, Qt.UserRole)
        return None

    def _texture_layer_choices(self):
        choices = [(-1, "(None)")]
        for i, name in enumerate(self.canvas.layer_names):
            ltype = self.canvas.layer_types[i] if i < len(self.canvas.layer_types) else "slice"
            if ltype == "texture":
                choices.append((i, name))
        return choices

    def _sync_object_inspector(self):
        if not hasattr(self, "obj_inspector_name"):
            return
        oid = self._selected_object_id_in_hierarchy()
        obj = None
        if oid:
            obj = next((o for o in self.canvas.object_layers if o.get("id") == oid), None)
        has_obj = obj is not None
        self.obj_inspector_name.setText(obj.get("name", "Object") if has_obj else "No object selected")
        self.obj_inspector_visible.blockSignals(True)
        self.obj_inspector_visible.setChecked(bool(obj.get("visible", True)) if has_obj else False)
        self.obj_inspector_visible.blockSignals(False)

        # Texture controls (only present in Texture workspace)
        if hasattr(self, "obj_texture_combo"):
            choices = self._texture_layer_choices()
            self.obj_texture_combo.blockSignals(True)
            self.obj_texture_combo.clear()
            for _idx, label in choices:
                self.obj_texture_combo.addItem(label)
            selected_tex = int(obj.get("texture_layer_index", -1)) if has_obj else -1
            combo_idx = 0
            for ci, (li, _label) in enumerate(choices):
                if li == selected_tex:
                    combo_idx = ci
                    break
            self.obj_texture_combo.setCurrentIndex(combo_idx)
            self.obj_texture_combo.blockSignals(False)
            self.obj_texture_combo.setEnabled(has_obj)

        if hasattr(self, "obj_texture_enabled"):
            self.obj_texture_enabled.blockSignals(True)
            self.obj_texture_enabled.setChecked(bool(obj.get("texture_enabled", False)) if has_obj else False)
            self.obj_texture_enabled.blockSignals(False)
            self.obj_texture_enabled.setEnabled(has_obj)

        if hasattr(self, "obj_texture_tile_x"):
            self.obj_texture_tile_x.blockSignals(True)
            self.obj_texture_tile_x.setValue(int(obj.get("texture_tile_x", 1)) if has_obj else 1)
            self.obj_texture_tile_x.blockSignals(False)
            self.obj_texture_tile_y.blockSignals(True)
            self.obj_texture_tile_y.setValue(int(obj.get("texture_tile_y", 1)) if has_obj else 1)
            self.obj_texture_tile_y.blockSignals(False)
            self.obj_texture_strength.blockSignals(True)
            self.obj_texture_strength.setValue(int(obj.get("texture_strength", 100)) if has_obj else 100)
            self.obj_texture_strength.blockSignals(False)
            tex_enabled = has_obj and getattr(self, 'obj_texture_enabled', None) and self.obj_texture_enabled.isChecked()
            self.obj_texture_tile_x.setEnabled(tex_enabled)
            self.obj_texture_tile_y.setEnabled(tex_enabled)
            self.obj_texture_strength.setEnabled(tex_enabled)

        self.obj_inspector_visible.setEnabled(has_obj)
        self.obj_inspector_rename_btn.setEnabled(has_obj)
        self.obj_inspector_resize_btn.setEnabled(has_obj)
        if hasattr(self, "obj_inspector_untexture_btn"):
            self.obj_inspector_untexture_btn.setEnabled(has_obj)

    def _selected_object_entry(self):
        oid = self._selected_object_id_in_hierarchy()
        if not oid:
            return None
        return next((o for o in self.canvas.object_layers if o.get("id") == oid), None)

    def _on_object_inspector_visible_toggled(self, checked: bool):
        oid = self._selected_object_id_in_hierarchy()
        if not oid:
            return
        for obj in self.canvas.object_layers:
            if obj.get("id") == oid:
                obj["visible"] = checked
                break
        
        # Update scene placement visibility
        scene = self.scene_manager.get_active_scene()
        if scene:
            placement = scene.get_placement(oid)
            if placement:
                placement.visible = checked
        
        # Update hierarchy checkbox without full rebuild
        self._syncing_stack_tree = True
        root = self.stack_hierarchy.topLevelItem(0)
        if root:
            for i in range(root.childCount()):
                item = root.child(i)
                if item.data(0, Qt.UserRole) == oid:
                    item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                    break
        self._syncing_stack_tree = False
        
        self._mark_modified()
        self._update_3d_preview()

    def _on_object_texture_source_changed(self, combo_index: int):
        obj = self._selected_object_entry()
        if not obj:
            return
        choices = self._texture_layer_choices()
        layer_idx = choices[combo_index][0] if 0 <= combo_index < len(choices) else -1
        obj["texture_layer_index"] = layer_idx
        if layer_idx < 0:
            obj["texture_enabled"] = False
        self._mark_modified()
        self._update_3d_preview()
        self._sync_object_inspector()

    def _on_object_texture_enabled_toggled(self, checked: bool):
        obj = self._selected_object_entry()
        if not obj:
            return
        if int(obj.get("texture_layer_index", -1)) < 0:
            obj["texture_enabled"] = False
            self._sync_object_inspector()
            return
        obj["texture_enabled"] = bool(checked)
        self._mark_modified()
        self._update_3d_preview()
        self._sync_object_inspector()

    def _on_object_texture_params_changed(self, _value: int):
        obj = self._selected_object_entry()
        if not obj:
            return
        obj["texture_tile_x"] = self.obj_texture_tile_x.value()
        obj["texture_tile_y"] = self.obj_texture_tile_y.value()
        obj["texture_strength"] = self.obj_texture_strength.value()
        self._mark_modified()
        self._update_3d_preview()

    def _rename_selected_object_from_inspector(self):
        oid = self._selected_object_id_in_hierarchy()
        if oid:
            self._rename_object_layer(oid)

    def _slice_indices_for_object(self, oid: str):
        if not oid:
            return []
        out = []
        for i in range(len(self.canvas.layers)):
            ltype = self.canvas.layer_types[i] if i < len(self.canvas.layer_types) else "slice"
            loid = self.canvas.layer_object_ids[i] if i < len(self.canvas.layer_object_ids) else None
            if ltype == "slice" and loid == oid:
                out.append(i)
        return out

    def _resize_slice_indices(self, indices, percent: int):
        scale = max(0.1, min(4.0, percent / 100.0))
        for idx in indices:
            bounds = self.canvas._non_transparent_bounds([idx])
            if not bounds:
                continue
            x0, y0, x1, y1 = bounds
            src = self.canvas.layers[idx]
            crop = src.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            nw = max(1, int(crop.width() * scale))
            nh = max(1, int(crop.height() * scale))
            scaled = crop.scaled(nw, nh, Qt.KeepAspectRatio, Qt.FastTransformation)
            cx = (x0 + x1 + 1) // 2
            cy = (y0 + y1 + 1) // 2
            ox = cx - scaled.width() // 2
            oy = cy - scaled.height() // 2
            out = QImage(self.canvas.canvas_width, self.canvas.canvas_height, QImage.Format_ARGB32)
            out.fill(Qt.transparent)
            p = QPainter(out)
            p.drawImage(ox, oy, scaled)
            p.end()
            self.canvas.layers[idx] = out

    def _untexture_slice_indices(self, indices):
        neutral = QColor(240, 240, 240, 255)
        for idx in indices:
            src = self.canvas.layers[idx]
            out = QImage(src.width(), src.height(), QImage.Format_ARGB32)
            out.fill(Qt.transparent)
            for y in range(src.height()):
                for x in range(src.width()):
                    c = src.pixelColor(x, y)
                    if c.alpha() > 0:
                        out.setPixelColor(x, y, QColor(neutral.red(), neutral.green(), neutral.blue(), c.alpha()))
            self.canvas.layers[idx] = out

    def _resize_selected_object_slices(self):
        oid = self._selected_object_id_in_hierarchy()
        indices = self._slice_indices_for_object(oid)
        if not indices:
            return
        percent, ok = QInputDialog.getInt(
            self, "Resize Object Slices", "Scale all slices (%):", 100, 10, 400
        )
        if not ok:
            return
        self.canvas.save_undo_state()
        self._resize_slice_indices(indices, percent)
        self.canvas.save_current_frame()
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"Resized {len(indices)} slices to {percent}%.", 2500)

    def _untexture_selected_object_slices(self):
        obj = self._selected_object_entry()
        if not obj:
            return
        obj["texture_enabled"] = False
        obj["texture_layer_index"] = -1
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage("Object texture mapping removed.", 2500)

    def _ensure_stack_node_state(self):
        if not hasattr(self, "_stack_node_state"):
            self._stack_node_state = {}
        valid = set(range(len(self.canvas.layers)))
        for key in list(self._stack_node_state.keys()):
            if key not in valid:
                self._stack_node_state.pop(key, None)
        for i, layer in enumerate(self.canvas.layers):
            state = self._stack_node_state.get(i)
            if state is None:
                self._stack_node_state[i] = {
                    "tx": 0.0,
                    "ty": 0.0,
                    "scale": 1.0,
                    "rot": 0.0,
                    "opacity": self.canvas.layer_opacity[i],
                    "source": layer.copy(),
                }
            else:
                no_transform = (
                    abs(state["tx"]) < 1e-9 and
                    abs(state["ty"]) < 1e-9 and
                    abs(state["rot"]) < 1e-9 and
                    abs(state["scale"] - 1.0) < 1e-9
                )
                if no_transform:
                    state["source"] = layer.copy()
                state["opacity"] = self.canvas.layer_opacity[i]

    def _sync_stack_controls_for_active_layer(self):
        # If an object is selected in the hierarchy, sync from its placement
        oid = self._selected_object_id_in_hierarchy()
        if oid:
            scene = self.scene_manager.get_active_scene()
            if scene:
                placement = scene.get_placement(oid)
                if placement:
                    for w, val in (
                        (self.stack_tx, placement.offset_x),
                        (self.stack_ty, placement.offset_y),
                        (self.stack_scale, placement.scale),
                        (self.stack_rot, placement.rotation),
                        (self.stack_stage_w, float(getattr(placement, "size_w", 0.12)) * 100.0),
                        (self.stack_stage_h, float(getattr(placement, "size_h", 0.12)) * 100.0),
                        (self.stack_depth, getattr(placement, "offset_z", 0.0)),
                    ):
                        w.blockSignals(True)
                        w.setValue(val)
                        w.blockSignals(False)
                    self.stack_opacity.blockSignals(True)
                    self.stack_opacity.setValue(placement.opacity)
                    self.stack_opacity.blockSignals(False)
                    return
        
        # Fallback: layer-level state
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        self._ensure_stack_node_state()
        state = self._stack_node_state[idx]
        for w, val in (
            (self.stack_tx, state["tx"]),
            (self.stack_ty, state["ty"]),
            (self.stack_scale, state["scale"]),
            (self.stack_rot, state["rot"]),
        ):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)
        self.stack_opacity.blockSignals(True)
        self.stack_opacity.setValue(self.canvas.layer_opacity[idx])
        self.stack_opacity.blockSignals(False)

    def _apply_stack_transform(self, idx: int):
        if not (0 <= idx < len(self.canvas.layers)):
            return
        self._ensure_stack_node_state()
        st = self._stack_node_state[idx]
        src = st["source"]
        out = QImage(self.canvas.canvas_width, self.canvas.canvas_height, QImage.Format_ARGB32)
        out.fill(Qt.transparent)

        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        cx = (self.canvas.canvas_width / 2.0) + st["tx"]
        cy = (self.canvas.canvas_height / 2.0) + st["ty"]
        p.translate(cx, cy)
        p.rotate(st["rot"])
        p.scale(st["scale"], st["scale"])
        p.drawImage(int(-src.width() / 2), int(-src.height() / 2), src)
        p.end()

        self.canvas.layers[idx] = out
        self.canvas.layer_opacity[idx] = st["opacity"]
        self.canvas.save_current_frame()
        self.canvas.update()
        self.layer_panel.update_thumbnail(idx, self.canvas.layers[idx])
        self._canvas_dirty_for_3d = True

    def _on_stack_transform_changed(self, _value):
        # Get selected object in hierarchy for placement-level transforms
        oid = self._selected_object_id_in_hierarchy()
        if oid:
            # Update scene placement transforms
            scene = self.scene_manager.get_active_scene()
            if scene:
                placement = scene.get_placement(oid)
                if placement:
                    placement.offset_x = self.stack_tx.value()
                    placement.offset_y = self.stack_ty.value()
                    placement.size_w = max(0.001, min(1.0, self.stack_stage_w.value() / 100.0))
                    placement.size_h = max(0.001, min(1.0, self.stack_stage_h.value() / 100.0))
                    placement.offset_z = self.stack_depth.value()
                    placement.scale = self.stack_scale.value()
                    placement.rotation = self.stack_rot.value()
            self._canvas_dirty_for_3d = True
            self._update_3d_preview()
            self._sync_sandbox_stage_from_active_scene()
            self._mark_modified()
            return
        
        # Fallback: layer-level transform for backward compatibility
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        self._ensure_stack_node_state()
        st = self._stack_node_state[idx]
        st["tx"] = self.stack_tx.value()
        st["ty"] = self.stack_ty.value()
        st["scale"] = self.stack_scale.value()
        st["rot"] = self.stack_rot.value()
        self._apply_stack_transform(idx)
        self._mark_modified()

    def _on_stack_opacity_changed(self, value: int):
        # Get selected object in hierarchy for placement-level opacity
        oid = self._selected_object_id_in_hierarchy()
        if oid:
            scene = self.scene_manager.get_active_scene()
            if scene:
                placement = scene.get_placement(oid)
                if placement:
                    placement.opacity = value
            self._canvas_dirty_for_3d = True
            self._update_3d_preview()
            self._mark_modified()
            return
            
        # Fallback: layer-level opacity
        idx = self.canvas.active_layer
        if 0 <= idx < len(self.canvas.layer_opacity):
            self._ensure_stack_node_state()
            self._stack_node_state[idx]["opacity"] = value
            self._apply_stack_transform(idx)
            self._mark_modified()

    def _focused_scene_id_for_active_layer(self) -> str | None:
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return None
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        layer_type = self.canvas.layer_types[idx] if idx < len(self.canvas.layer_types) else "slice"
        if layer_type == "texture":
            return None
        if layer_type == "slice":
            oid = self.canvas.layer_object_ids[idx] if idx < len(self.canvas.layer_object_ids) else None
            return oid or f"slice_{idx}"
        return f"sprite_{idx}"

    def _preview_ensemble(self):
        self._preview_scene_scope = "ensemble"
        self._preview_focus_id = None
        self._canvas_dirty_for_3d = True
        # FIX: Always update 3D preview immediately when switching to ensemble view
        # regardless of which workspace is active
        self._update_3d_preview()
        self.statusBar().showMessage("Ensemble view: showing all visible objects", 2000)

    def _preview_focus_active(self):
        focus_id = self._focused_scene_id_for_active_layer()
        if not focus_id:
            self.statusBar().showMessage("Active layer cannot be focused in 3D.", 2500)
            return
        self._preview_scene_scope = "focus"
        self._preview_focus_id = focus_id
        self._canvas_dirty_for_3d = True
        # FIX: Always update 3D preview immediately when switching focus
        self._update_3d_preview()
        self.statusBar().showMessage(f"Focus view: object {focus_id[:8]}...", 2000)

    def _create_object_layer(self):
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        name, ok = QInputDialog.getText(
            self, "New Object Layer", "Object layer name:",
            text=f"Object {len(self.canvas.object_layers) + 1}"
        )
        if not ok:
            return
        name = (name or "").strip() or f"Object {len(self.canvas.object_layers) + 1}"
        oid = f"obj_{uuid.uuid4().hex[:8]}"
        self.canvas.object_layers.append({
            "id": oid,
            "name": name,
            "type": "stack",
            "visible": True,
            "texture_layer_index": -1,
            "texture_enabled": False,
            "texture_tile_x": 1,
            "texture_tile_y": 1,
            "texture_strength": 100,
        })
        # Add placement to active scene with automatic offset to avoid overlap
        scene = self.scene_manager.get_active_scene()
        if scene:
            # Calculate offset based on number of existing objects
            num_objects = len(scene.placements)
            auto_offset_x = float(num_objects * 80)  # Spread objects horizontally
            scene.add_object(
                object_id=oid,
                visible=True,
                offset_x=auto_offset_x,
                offset_y=0.0,
                offset_z=0.0,
                scale=1.0,
                rotation=0.0,
                opacity=255,
            )
        self._mark_modified()
        self._sync_sandbox_workspace_from_canvas()
        self.statusBar().showMessage(f"Object layer created: {name}", 2500)

    def _assign_active_slice_to_active_object(self):
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        if idx >= len(self.canvas.layer_types) or self.canvas.layer_types[idx] != "slice":
            QMessageBox.information(self, "Assign Slice", "Active layer must be an Object Slice.")
            return

        selected = self.stack_hierarchy.selectedItems() if hasattr(self, "stack_hierarchy") else []
        target_oid = None
        if selected:
            item = selected[0]
            if item.data(0, Qt.UserRole + 2) == "object":
                target_oid = item.data(0, Qt.UserRole)
            elif item.parent() and item.parent().data(0, Qt.UserRole + 2) == "object":
                target_oid = item.parent().data(0, Qt.UserRole)

        if not target_oid and self.canvas.object_layers:
            target_oid = self.canvas.object_layers[0].get("id")
        if not target_oid:
            self._create_object_layer()
            if self.canvas.object_layers:
                target_oid = self.canvas.object_layers[-1].get("id")
        if not target_oid:
            return

        self.canvas.layer_object_ids[idx] = target_oid
        self._mark_modified()
        self._sync_sandbox_workspace_from_canvas()
        self._canvas_dirty_for_3d = True
        self._update_3d_preview()
        self.statusBar().showMessage("Assigned active slice to object layer.", 2500)

    def _detach_active_slice_from_object(self):
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        if idx >= len(self.canvas.layer_types) or self.canvas.layer_types[idx] != "slice":
            QMessageBox.information(self, "Detach Slice", "Active layer must be an Object Slice.")
            return
        self.canvas.layer_object_ids[idx] = None
        self._mark_modified()
        self._sync_sandbox_workspace_from_canvas()
        self._update_3d_preview()
        self.statusBar().showMessage("Slice detached from object layer.", 2500)

    def _resize_active_slice(self):
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        if idx >= len(self.canvas.layer_types) or self.canvas.layer_types[idx] != "slice":
            QMessageBox.information(self, "Resize Slice", "Active layer must be an Object Slice.")
            return

        percent, ok = QInputDialog.getInt(
            self, "Resize Active Slice", "Scale (%):", 100, 10, 400
        )
        if not ok:
            return
        scale = percent / 100.0

        bounds = self.canvas._non_transparent_bounds([idx])
        if not bounds:
            return
        x0, y0, x1, y1 = bounds
        src = self.canvas.layers[idx]
        crop = src.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        nw = max(1, int(crop.width() * scale))
        nh = max(1, int(crop.height() * scale))
        scaled = crop.scaled(nw, nh, Qt.KeepAspectRatio, Qt.FastTransformation)

        cx = (x0 + x1 + 1) // 2
        cy = (y0 + y1 + 1) // 2
        ox = cx - scaled.width() // 2
        oy = cy - scaled.height() // 2

        out = QImage(self.canvas.canvas_width, self.canvas.canvas_height, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(ox, oy, scaled)
        p.end()

        self.canvas.save_undo_state()
        self.canvas.layers[idx] = out
        self.canvas.save_current_frame()
        self.canvas.update()
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"Slice resized to {percent}%.", 2500)

    def _untexture_active_slice(self):
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        if idx >= len(self.canvas.layer_types) or self.canvas.layer_types[idx] != "slice":
            QMessageBox.information(self, "Untexture Slice", "Active layer must be an Object Slice.")
            return

        src = self.canvas.layers[idx]
        out = QImage(src.width(), src.height(), QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        neutral = QColor(240, 240, 240, 255)
        for y in range(src.height()):
            for x in range(src.width()):
                c = src.pixelColor(x, y)
                if c.alpha() > 0:
                    out.setPixelColor(x, y, QColor(neutral.red(), neutral.green(), neutral.blue(), c.alpha()))

        self.canvas.save_undo_state()
        self.canvas.layers[idx] = out
        self.canvas.save_current_frame()
        self.canvas.update()
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage("Slice untextured (neutral albedo).", 2500)

    def _rename_object_layer(self, object_id: str):
        if not object_id:
            return
        obj = next((o for o in self.canvas.object_layers if o.get("id") == object_id), None)
        if not obj:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Object Layer", "New name:", text=obj.get("name", "Object")
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        obj["name"] = name
        self._mark_modified()
        self._sync_sandbox_workspace_from_canvas()

    def _delete_object_layer(self, object_id: str):
        if not object_id:
            return
        reply = QMessageBox.question(
            self,
            "Delete Object Layer",
            "Delete this object layer?\n\nIts slice layers will remain but become unassigned.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Remove from global registry
        self.canvas.object_layers = [o for o in self.canvas.object_layers if o.get("id") != object_id]
        for i, oid in enumerate(self.canvas.layer_object_ids):
            if oid == object_id:
                self.canvas.layer_object_ids[i] = None
        self._object_canvas_data.pop(object_id, None)

        # Remove placement from active scene
        scene = self.scene_manager.get_active_scene()
        if scene:
            scene.remove_object(object_id)

        # Pick a scene-appropriate replacement for active object
        if self._active_object_id == object_id:
            scene_oids = self._active_scene_object_ids()
            if scene_oids:
                new_oid = scene_oids[0]
                self._active_object_id = new_oid
                self._load_scene_object_into_canvas(new_oid)
            else:
                self._active_object_id = None

        if self._preview_focus_id == object_id:
            self._preview_ensemble()
        self._mark_modified()
        self._sync_sandbox_workspace_from_canvas()
        self._update_3d_preview()

    def _show_stack_hierarchy_context_menu(self, pos):
        item = self.stack_hierarchy.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        role_type = item.data(0, Qt.UserRole + 2)

        if role_type == "object":
            oid = item.data(0, Qt.UserRole)
            menu.addAction("Focus Object").triggered.connect(
                lambda: (setattr(self, "_preview_scene_scope", "focus"),
                         setattr(self, "_preview_focus_id", oid),
                         self._update_3d_preview())
            )
            menu.addAction("Rename Object Layer...").triggered.connect(
                lambda: self._rename_object_layer(oid)
            )
            menu.addAction("Delete Object Layer").triggered.connect(
                lambda: self._delete_object_layer(oid)
            )
        else:
            idx = item.data(0, Qt.UserRole)
            if isinstance(idx, int) and 0 <= idx < len(self.canvas.layers):
                menu.addAction("Select Layer").triggered.connect(
                    lambda i=idx: self._activate_stack_layer(i)
                )
                ltype = self.canvas.layer_types[idx] if idx < len(self.canvas.layer_types) else "slice"
                if ltype == "slice":
                    menu.addAction("Resize Slice...").triggered.connect(
                        lambda i=idx: (self._activate_stack_layer(i), self._resize_active_slice())
                    )
                    menu.addAction("Untexture Slice").triggered.connect(
                        lambda i=idx: (self._activate_stack_layer(i), self._untexture_active_slice())
                    )
                    menu.addAction("Detach From Object").triggered.connect(
                        lambda i=idx: (self._activate_stack_layer(i), self._detach_active_slice_from_object())
                    )

        if menu.actions():
            menu.exec_(self.stack_hierarchy.mapToGlobal(pos))

    def _build_scene_items_for_preview(self):
        """Build scene items for 3D preview from ALL project objects."""
        # Save current object state first
        if self._active_object_id:
            self._save_canvas_to_object(self._active_object_id)
        
        # Get active scene and its placements for visibility/transform data
        scene = self.scene_manager.get_active_scene()
        placement_map = {}
        if scene:
            for p in scene.placements:
                placement_map[p.object_id] = p

        # Build map of global object metadata
        object_map = {
            o.get("id"): o
            for o in getattr(self.canvas, "object_layers", [])
            if isinstance(o, dict)
        }

        items = []
        
        # Build scene items from objects placed in the active scene.
        for obj in self._objects_for_active_scene():
            if not isinstance(obj, dict):
                continue
            oid = obj.get("id")
            if not oid:
                continue
            
            obj_type = obj.get("type", "stack")
            obj_name = obj.get("name", "Object")
            
            # Get placement for transforms
            placement = placement_map.get(oid)
            if placement:
                obj_visible = placement.visible
                obj_offset_x = placement.offset_x
                obj_offset_y = placement.offset_y
                obj_offset_z = placement.offset_z
                obj_scale = placement.scale
                obj_rotation = placement.rotation
                obj_opacity = placement.opacity
            else:
                continue
            
            # Get layer data from the right source
            if oid == self._active_object_id:
                # Active object - use live canvas
                layers = self.canvas.layers
                layer_visible = self.canvas.layer_visible
                layer_types = self.canvas.layer_types
            elif oid in self._object_canvas_data:
                # Cached object data
                cached = self._object_canvas_data[oid]
                layers = cached.get("layers", [])
                layer_visible = cached.get("layer_visible", [])
                layer_types = cached.get("layer_types", [])
            else:
                # No data yet
                layers = []
                layer_visible = []
                layer_types = []
            
            # Collect visible layers for this object
            visible_layers = []
            for i, layer in enumerate(layers):
                lvis = layer_visible[i] if i < len(layer_visible) else True
                ltype = layer_types[i] if i < len(layer_types) else "slice"
                if lvis and ltype != "texture":
                    visible_layers.append(layer)
            
            if not visible_layers:
                continue
            
            # Determine kind based on object type
            kind = "stack" if obj_type == "stack" else "sprite"
            
            item = {
                "id": oid,
                "name": obj_name,
                "kind": kind,
                "visible": obj_visible,
                "layers": visible_layers,
                "offset_x": obj_offset_x,
                "offset_y": obj_offset_y,
                "offset_z": obj_offset_z,
                "scale": obj_scale,
                "rotation": obj_rotation,
                "opacity": obj_opacity,
            }
            items.append(item)
        
        # Auto-spread objects that don't have placements
        for j, item in enumerate(items):
            if item["kind"] == "stack" and item.get("offset_x", 0.0) == 0.0 and item.get("offset_y", 0.0) == 0.0:
                if item.get("id") not in placement_map:
                    item["offset_x"] = float((j - len(items) / 2.0) * 1.5)

        # Apply texture mapping to stack objects
        for item in items:
            if item.get("kind") != "stack":
                continue
            om = object_map.get(item.get("id"), {})
            if not bool(om.get("texture_enabled", False)):
                continue
            t_idx = int(om.get("texture_layer_index", -1))
            
            # Get texture from active canvas or cached data
            oid = item.get("id")
            if oid == self._active_object_id:
                tex_layers = self.canvas.layers
                tex_types = self.canvas.layer_types
            elif oid in self._object_canvas_data:
                tex_layers = self._object_canvas_data[oid].get("layers", [])
                tex_types = self._object_canvas_data[oid].get("layer_types", [])
            else:
                continue
                
            if not (0 <= t_idx < len(tex_layers)):
                continue
            t_type = tex_types[t_idx] if t_idx < len(tex_types) else "slice"
            if t_type != "texture":
                continue
            tex = tex_layers[t_idx]
            if tex is None or tex.isNull():
                continue
            try:
                item["layers"] = apply_texture_to_layers(
                    item["layers"],
                    tex,
                    map_mode="full",
                    tile_x=int(om.get("texture_tile_x", 1)),
                    tile_y=int(om.get("texture_tile_y", 1)),
                    strength=int(om.get("texture_strength", 100)),
                )
            except Exception:
                pass
        return items

    def _stack_slice_stub(self):
        self.statusBar().showMessage("Slice/Divide tool is available from Stack workflow.", 2200)

    def _stack_separate_stub(self):
        self.statusBar().showMessage("Object separation uses existing layer stack logic.", 2200)

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _setup_menus(self):
        mb = self.menuBar()

        # ── File ──────────────────────────────────────────────────────
        file_menu = mb.addMenu("&File")

        self._add_action(file_menu, "&New...",          "Ctrl+N",       self._new_project)
        self._add_action(file_menu, "&Open Project...", "Ctrl+O",       self._open_project)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Save Project",  "Ctrl+S",       self._save_project)
        self._add_action(file_menu, "Save &As...",      "Ctrl+Shift+S", self._save_project_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Import...",       "Ctrl+I",       self._import)
        self._add_action(file_menu, "&Export...",       "Ctrl+E",       self._export)
        self._add_action(file_menu, "Quick Export PNG","Ctrl+Shift+E", self._quick_export_png)
        file_menu.addSeparator()

        # Recent files sub-menu
        self.recent_menu = file_menu.addMenu("Recent Files")
        self._rebuild_recent_menu()
        file_menu.addSeparator()

        self._add_action(file_menu, "E&xit", "Alt+F4", self.close)

        # ── Edit ──────────────────────────────────────────────────────
        edit_menu = mb.addMenu("&Edit")

        self._add_action(edit_menu, "&Undo",              "Ctrl+Z",  self._undo)
        self._add_action(edit_menu, "&Redo",              "Ctrl+Y",  self._redo)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Cu&t",               "Ctrl+X",  self._cut)
        self._add_action(edit_menu, "&Copy",              "Ctrl+C",  self._copy)
        self._add_action(edit_menu, "&Paste",             "Ctrl+V",  self._paste)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select &All",        "Ctrl+A",  self._select_all)
        self._add_action(edit_menu, "&Deselect",          "Ctrl+D",  self._deselect)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Clear Layer",        "Delete",   self._clear_layer)
        self._add_action(edit_menu, "Fill Layer with Color", None,    self._fill_layer)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Resize Canvas...",     None,       self._resize_canvas)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Preferences...",     "Ctrl+,",   self._show_preferences)

        # ── View ──────────────────────────────────────────────────────
        view_menu = mb.addMenu("&View")

        self._add_action(view_menu, "Zoom In",     "Ctrl++",  lambda: self._zoom(1.5))
        self._add_action(view_menu, "Zoom Out",    "Ctrl+-",  lambda: self._zoom(1 / 1.5))
        self._add_action(view_menu, "Fit Canvas",  "Ctrl+0",  self.canvas.fit_canvas)
        self._add_action(view_menu, "Center Canvas","Home",   self.canvas.center_canvas)
        view_menu.addSeparator()
        self._add_action(view_menu, "Toggle Grid", "Ctrl+G",  self._toggle_grid)
        self.view_mirror_x_action = QAction("Mirror X Symmetry", self)
        self.view_mirror_x_action.setCheckable(True)
        self.view_mirror_x_action.toggled.connect(self._set_mirror_x_from_menu)
        view_menu.addAction(self.view_mirror_x_action)
        self.view_mirror_y_action = QAction("Mirror Y Symmetry", self)
        self.view_mirror_y_action.setCheckable(True)
        self.view_mirror_y_action.toggled.connect(self._set_mirror_y_from_menu)
        view_menu.addAction(self.view_mirror_y_action)
        self.view_onion_action = QAction("Onion Skin", self)
        self.view_onion_action.setCheckable(True)
        self.view_onion_action.toggled.connect(self._on_onion_toggled)
        view_menu.addAction(self.view_onion_action)

        # ── Layer ─────────────────────────────────────────────────────
        layer_menu = mb.addMenu("&Layer")

        self._add_action(layer_menu, "Add Layer",        "Ctrl+Shift+N", self._prompt_add_layer)
        self._add_action(layer_menu, "Duplicate Layer",  "Ctrl+Shift+D", lambda: self._duplicate_layer())
        self._add_action(layer_menu, "Delete Layer",     None,           lambda: self._remove_layer())
        layer_menu.addSeparator()
        self._add_action(layer_menu, "Centre Object",    "Ctrl+Shift+C", self._centre_object)
        layer_menu.addSeparator()
        self._add_action(layer_menu, "Merge Down",       "Ctrl+Shift+M", lambda: self._merge_layer_down())
        self._add_action(layer_menu, "Merge Visible",    None,           self._merge_visible_layers)
        self._add_action(layer_menu, "Flatten All",      None,           self._flatten_layers)
        layer_menu.addSeparator()
        self._add_action(layer_menu, "Set Type: Object Slice", None,
                         lambda: self._set_active_layer_type("slice"))
        self._add_action(layer_menu, "Set Type: Sprite Layer", None,
                         lambda: self._set_active_layer_type("sprite"))
        self._add_action(layer_menu, "Set Type: Texture Layer", None,
                         lambda: self._set_active_layer_type("texture"))

        # ── Animation ─────────────────────────────────────────────────
        anim_menu = mb.addMenu("&Animation")

        self._add_action(anim_menu, "Add Frame",       "F5",    lambda: self._add_frame(False))
        self._add_action(anim_menu, "Duplicate Frame", "F6",    lambda: self._add_frame(True))
        self._add_action(anim_menu, "Delete Frame",    "F7",
                         lambda: self._delete_frame(self.canvas.current_frame))
        anim_menu.addSeparator()
        self._add_action(anim_menu, "Play / Pause",    "Space", self._toggle_play)

        # ── Stack ─────────────────────────────────────────────────────
        stack_menu = mb.addMenu("&Stack")

        self._add_action(stack_menu, "Auto-Generate Layers from Base", None,
                         self._auto_generate_stack)
        stack_menu.addSeparator()
        primitive_menu = stack_menu.addMenu("Create Primitive")
        self._add_action(primitive_menu, "Cube", None,
                         lambda: self._create_primitive("cube"))
        self._add_action(primitive_menu, "Pyramid", None,
                         lambda: self._create_primitive("pyramid"))
        self._add_action(primitive_menu, "Prism", None,
                         lambda: self._create_primitive("prism"))
        self._add_action(primitive_menu, "Cylinder", None,
                         lambda: self._create_primitive("cylinder"))
        stack_menu.addSeparator()
        self._add_action(stack_menu, "Import Texture PNG...", None,
                         self._import_texture_png)
        self._add_action(stack_menu, "Import Layer Strip...", None,
                         self._import_layer_strip)
        stack_menu.addSeparator()
        self._add_action(stack_menu, "Export Rotation Sheet...", None,
                         self._export_rotation_sheet)
        self._add_action(stack_menu, "Export Layer Strip...",    None,
                         self._export_layer_strip)
        self._add_action(stack_menu, "Export OBJ/MTL...", None,
                         self._export_obj_mtl)

        # ── Help ──────────────────────────────────────────────────────
        help_menu = mb.addMenu("&Help")

        self._add_action(help_menu, "Keyboard Shortcuts", None, self._show_shortcuts)
        self._add_action(help_menu, "About",              None, self._show_about)

    @staticmethod
    def _add_action(menu: QMenu, label: str, shortcut: str | None,
                    slot) -> QAction:
        """Helper: create and add a QAction in one line."""
        action = QAction(label, menu.parent() or menu)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------
    # Signal connections - clean, no hasattr guards
    # ------------------------------------------------------------------

    def _connect_signals(self):
        tb = self.tool_bar
        cv = self.canvas
        lp = self.layer_panel
        pp = self.palette_panel
        tl = self.timeline

        # ── ToolBar → Canvas ──────────────────────────────────────────
        tb.tool_changed.connect(self._on_tool_changed)
        tb.brush_size_changed.connect(self._on_brush_size_changed)
        tb.brush_shape_changed.connect(self._on_brush_shape_changed)
        tb.brush_hardness_changed.connect(self._on_brush_hardness_changed)   # FIX: was missing
        tb.brush_opacity_changed.connect(self._on_brush_opacity_changed)     # FIX: was missing
        tb.tolerance_changed.connect(self._on_tolerance_changed)             # FIX: was missing
        tb.gradient_mode_changed.connect(lambda m: setattr(cv, 'gradient_mode', m))
        tb.gradient_start_color_changed.connect(lambda c: setattr(cv, 'gradient_start_color', c))
        tb.gradient_end_color_changed.connect(lambda c: setattr(cv, 'gradient_end_color', c))
        tb.mirror_x_changed.connect(self._set_mirror_x_from_menu)
        tb.mirror_y_changed.connect(self._set_mirror_y_from_menu)
        if hasattr(tb, "symmetry_axis_count_changed"):
            tb.symmetry_axis_count_changed.connect(self._on_symmetry_axis_count_changed)
        if hasattr(tb, "symmetry_inverse_changed"):
            tb.symmetry_inverse_changed.connect(self._on_symmetry_inverse_changed)
        tb.grid_toggled.connect(self._toggle_grid_cb)                        # FIX: use signal
        tb.onion_toggled.connect(self._on_onion_toggled)                     # FIX: was missing
        tb.onion_frames_changed.connect(self._on_onion_frames_changed)       # FIX: was missing
        # Fix 4: connect Centre Object button from updated tools.py
        if hasattr(tb, 'center_object_clicked'):
            tb.center_object_clicked.connect(self._centre_object)
        # Selection mode, contour shape options
        tb.selection_mode_changed.connect(lambda m: setattr(cv, 'selection_mode', m))

        # ── Canvas → Window ───────────────────────────────────────────
        cv.canvas_modified.connect(self._on_canvas_modified)
        cv.canvas_modified.connect(self._refresh_ai_panel_context)
        cv.color_picked.connect(self._on_color_picked)
        cv.cursor_pos_changed.connect(self._on_cursor_moved)
        cv.pivot_changed.connect(self._on_pivot_changed)
        # Fix 1: canvas.frame_changed keeps status bar frame_label in sync
        cv.frame_changed.connect(self._on_canvas_frame_changed)
        self.right_tabs.currentChanged.connect(self._refresh_ai_panel_context)

        # ── Palette ───────────────────────────────────────────────────
        pp.color_changed.connect(self._on_palette_color_changed)
        pp.secondary_color_changed.connect(
            lambda c: setattr(cv, 'secondary_color', c)
        )
        if hasattr(tb, "set_gradient_colors"):
            tb.set_gradient_colors(pp.primary_color, pp.secondary_color)
        cv.gradient_start_color = QColor(pp.primary_color)
        cv.gradient_end_color = QColor(pp.secondary_color)

        if hasattr(self, "scene_ui_panel"):
            pass
        if hasattr(self, "ai_gen_panel"):
            self.ai_gen_panel.generate_requested.connect(self._on_ai_generate_requested)
            self.ai_gen_panel.status_message.connect(
                lambda msg: self.statusBar().showMessage(msg, 2500)
            )
        if hasattr(self, "ai_chat_panel"):
            self.ai_chat_panel.send_requested.connect(self._on_ai_chat_send)

        # ── LayerPanel → Window ───────────────────────────────────────
        lp.layer_selected.connect(self._on_layer_selected)
        lp.layer_added.connect(self._add_layer)                              # FIX: accepts name str
        lp.layer_removed.connect(self._remove_layer)
        lp.layer_duplicated.connect(self._duplicate_layer)
        lp.layer_moved.connect(self._move_layer)
        lp.layer_opacity_changed.connect(self._change_layer_opacity)
        lp.layer_blend_mode_changed.connect(self._change_layer_blend_mode)   # FIX: was missing
        lp.layer_merged_down.connect(self._merge_layer_down)
        lp.merge_visible_requested.connect(self._merge_visible_layers)       # FIX: was missing
        lp.layer_visibility_changed.connect(self._toggle_layer_visibility)
        lp.layer_renamed.connect(self._rename_layer)
        lp.layer_locked_changed.connect(self._toggle_layer_lock)
        lp.flatten_requested.connect(self._flatten_layers)

        # ── LayerPanel object-level signals ──
        if hasattr(lp, 'object_selected'):
            lp.object_selected.connect(self._on_object_selected)
        if hasattr(lp, 'object_add_requested'):
            lp.object_add_requested.connect(self._on_object_add_requested)
        if hasattr(lp, 'object_remove_requested'):
            lp.object_remove_requested.connect(self._on_object_remove_requested)
        if hasattr(lp, 'object_renamed'):
            lp.object_renamed.connect(self._on_object_renamed)
        if hasattr(lp, 'object_type_converted'):
            lp.object_type_converted.connect(self._on_object_type_converted)

        # ── Timeline ──────────────────────────────────────────────────
        tl.frame_selected.connect(self._on_frame_selected)
        tl.frame_added.connect(self._add_frame)
        tl.frame_deleted.connect(self._delete_frame)
        # Fix 9: new signals from updated timeline.py
        if hasattr(tl, 'frame_inserted_before'):
            tl.frame_inserted_before.connect(cv.insert_frame_before)
        if hasattr(tl, 'frame_inserted_after'):
            tl.frame_inserted_after.connect(cv.insert_frame_after)
        if hasattr(tl, 'frame_moved'):
            tl.frame_moved.connect(cv.move_frame)
        if hasattr(tl, 'frame_cleared'):
            tl.frame_cleared.connect(self._on_frame_cleared)
        if hasattr(tl, 'onion_skin_changed'):
            tl.onion_skin_changed.connect(cv.set_onion_skin)
        if hasattr(tl, 'playback_mode_changed'):
            tl.playback_mode_changed.connect(
                lambda mode: self.statusBar().showMessage(f"Playback: {mode}", 2000))
        if hasattr(tl, 'loop_range_changed'):
            tl.loop_range_changed.connect(self._on_loop_range_changed)
        if hasattr(tl, 'frame_duration_changed'):
            tl.frame_duration_changed.connect(self._on_frame_duration_changed)
        if hasattr(tl, 'predict_intermediate_requested'):
            tl.predict_intermediate_requested.connect(self._predict_intermediate_frames)

        # ── Inline 3D overlay signals ─────────────────────────────
        if hasattr(self, 'inline_3d_preview'):
            self.inline_3d_preview.nudge_requested.connect(self._on_3d_nudge)
            self.inline_3d_preview.scale_changed.connect(self._on_3d_scale)
            self.inline_3d_preview._center_btn.clicked.connect(self._centre_object)

        self._refresh_ai_panel_context()

    # ------------------------------------------------------------------
    # Signal handlers - Canvas / Tools
    # ------------------------------------------------------------------

    def _on_tool_changed(self, tool_id: str):
        if self._suppress_tool_change:
            self.canvas.current_tool = tool_id
            if tool_id != "symmetry":
                self._last_non_symmetry_tool = tool_id
            self._last_tool_id = tool_id
            return

        if tool_id == "symmetry":
            if (self.canvas.mirror_x or self.canvas.mirror_y) and self._last_tool_id == "symmetry":
                self._set_mirror_x_from_menu(False)
                self._set_mirror_y_from_menu(False)
                self.canvas.update()
                if self._last_non_symmetry_tool:
                    self._suppress_tool_change = True
                    self.tool_bar.select_tool(self._last_non_symmetry_tool)
                    self._suppress_tool_change = False
                self._last_tool_id = self._last_non_symmetry_tool
                return
            if not (self.canvas.mirror_x or self.canvas.mirror_y):
                self._set_mirror_x_from_menu(True)
                self._set_mirror_y_from_menu(True)
                self.canvas.update()

        self.canvas.current_tool = tool_id
        self.tool_label.setText(tool_id.replace("_", " ").title())
        self.statusBar().showMessage(f"Tool: {tool_id}", 2000)
        if hasattr(self.canvas, 'hide_context_bar'):
            self.canvas.hide_context_bar()
        if tool_id == "ai_assist":
            self._open_ai_assist_prompt()
        if tool_id != "symmetry":
            self._last_non_symmetry_tool = tool_id
        self._last_tool_id = tool_id

    def _on_brush_size_changed(self, size: int):
        self.canvas.brush_size = size

    def _on_brush_shape_changed(self, shape: str):
        self.canvas.brush_shape = shape.lower()

    def _on_brush_hardness_changed(self, value: int):
        """FIX: was never connected. Passes hardness (0-100) to canvas."""
        if hasattr(self.canvas, 'brush_hardness'):
            self.canvas.brush_hardness = value

    def _on_brush_opacity_changed(self, value: int):
        """FIX: was never connected. Passes opacity (0-100) to canvas."""
        if hasattr(self.canvas, 'brush_opacity'):
            self.canvas.brush_opacity = value

    def _on_tolerance_changed(self, value: int):
        """FIX: was never connected. Passes tolerance (0-255) to canvas."""
        if hasattr(self.canvas, 'fill_tolerance'):
            self.canvas.fill_tolerance = value

    def _on_symmetry_axis_count_changed(self, value: int):
        self.canvas.symmetry_axis_count = max(1, int(value))
        self.canvas.update()

    def _on_symmetry_inverse_changed(self, enabled: bool):
        self.canvas.symmetry_inverse = bool(enabled)
        self.canvas.update()

    def _on_onion_toggled(self, enabled: bool):
        self.canvas.onion_skin_enabled = enabled
        if hasattr(self, "view_onion_action"):
            self.view_onion_action.blockSignals(True)
            self.view_onion_action.setChecked(enabled)
            self.view_onion_action.blockSignals(False)
        self.canvas.update()

    def _on_onion_frames_changed(self, frames: int):
        """FIX: was never connected."""
        if hasattr(self.canvas, 'onion_skin_frames'):
            self.canvas.onion_skin_frames = frames
            self.canvas.update()

    # Fix 1: canvas.frame_changed → status bar label sync
    def _on_canvas_frame_changed(self, current: int, total: int):
        self.frame_label.setText(f"Frame {current + 1}/{total}")
        self._refresh_timeline()

    # Fix 9: timeline new signal handlers
    def _on_frame_cleared(self, idx: int):
        self.canvas.clear_frame(idx)
        self._mark_modified()
        self._refresh_timeline()

    def _on_loop_range_changed(self, in_idx: int, out_idx: int):
        """Store loop range on canvas for potential future use; no-op if canvas doesn't support it."""
        if hasattr(self.canvas, 'loop_in'):
            self.canvas.loop_in  = in_idx
            self.canvas.loop_out = out_idx

    def _on_frame_duration_changed(self, frame_idx: int, multiplier: int):
        """Store per-frame duration multiplier on canvas if supported."""
        if hasattr(self.canvas, '_frame_durations'):
            self.canvas._frame_durations[frame_idx] = multiplier

    def _post_ai_json(self, endpoint: str, payload: dict, on_success, action_label: str, on_error=None):
        req = QNetworkRequest(QUrl(f"http://127.0.0.1:8000{endpoint}"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        body = QByteArray(json.dumps(payload).encode("utf-8"))
        reply = self._ai_network.post(req, body)

        def _finished():
            try:
                if reply.error():
                    self.statusBar().showMessage(
                        f"{action_label} failed: {reply.errorString()}",
                        3500,
                    )
                    if callable(on_error):
                        on_error(reply.errorString())
                    return
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                on_success(data)
            except Exception as exc:
                self.statusBar().showMessage(f"{action_label} error: {exc}", 3500)
                if callable(on_error):
                    on_error(str(exc))
            finally:
                reply.deleteLater()
        reply.finished.connect(_finished)

    def _qimage_to_hex(self, image: QImage) -> str:
        if image is None or image.isNull():
            return ""
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        ptr = rgba.bits()
        ptr.setsize(rgba.byteCount())
        return bytes(ptr).hex()

    def _get_selection_region_hex(self) -> dict | None:
        """
        If a selection is active, return a dict with the cropped region hex
        and the full-layer context hex (for inpainting).
        Returns None if no selection is active.
        """
        if self.canvas.selection_rect is None:
            return None
        rect = self.canvas.selection_rect
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        layer = self.canvas.layers[self.canvas.active_layer]
        region = layer.copy(rect)
        return {
            "x": rect.x(),
            "y": rect.y(),
            "w": rect.width(),
            "h": rect.height(),
            "region_hex": self._qimage_to_hex(region),
            "context_hex": self._qimage_to_hex(layer),
            "width": rect.width(),
            "height": rect.height(),
        }

    def _tokens_to_image(self, tokens: list[str], width: int, height: int) -> QImage | None:
        if not tokens:
            return None
        pixel_count = len(tokens)
        if width <= 0 or height <= 0 or width * height != pixel_count:
            side = int(pixel_count ** 0.5)
            if side > 0 and side * side == pixel_count:
                width = side
                height = side
            else:
                return None

        img = QImage(width, height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        for i, token in enumerate(tokens):
            token = token.strip().lstrip("#")
            if len(token) == 6:
                token = token + "FF"
            if len(token) != 8:
                continue
            try:
                r = int(token[0:2], 16)
                g = int(token[2:4], 16)
                b = int(token[4:6], 16)
                a = int(token[6:8], 16)
            except ValueError:
                continue
            x = i % width
            y = i // width
            if y >= height:
                break
            img.setPixelColor(x, y, QColor(r, g, b, a))
        return img

    def _decode_ai_image(self, payload) -> QImage | None:
        if payload is None:
            return None

        width = self.canvas.canvas_width
        height = self.canvas.canvas_height
        source = payload

        if isinstance(payload, dict):
            if isinstance(payload.get("frames"), list) and payload["frames"]:
                return self._decode_ai_image(payload["frames"][0])
            if isinstance(payload.get("intermediate_frames"), list) and payload["intermediate_frames"]:
                return self._decode_ai_image(payload["intermediate_frames"][0])
            source = (
                payload.get("hex")
                or payload.get("pixels")
                or payload.get("pixel_hex")
                or payload.get("data")
                or payload.get("image")
            )
            try:
                width = int(payload.get("width") or payload.get("w") or width)
            except (TypeError, ValueError):
                width = self.canvas.canvas_width
            try:
                height = int(payload.get("height") or payload.get("h") or height)
            except (TypeError, ValueError):
                height = self.canvas.canvas_height

        if isinstance(source, dict):
            return self._decode_ai_image(source)

        if isinstance(source, list):
            tokens = [str(tok).strip().lstrip("#") for tok in source]
            if tokens and all(len(tok) in (6, 8) for tok in tokens):
                return self._tokens_to_image(tokens, width, height)
            source = "".join(tokens)

        if not isinstance(source, str):
            return None

        hex_only = "".join(ch for ch in source if ch in string.hexdigits)
        if not hex_only:
            return None

        expected_pixels = max(1, width * height)
        if len(hex_only) == expected_pixels * 8:
            tokens = [hex_only[i:i + 8] for i in range(0, len(hex_only), 8)]
            return self._tokens_to_image(tokens, width, height)
        if len(hex_only) == expected_pixels * 6:
            tokens = [hex_only[i:i + 6] for i in range(0, len(hex_only), 6)]
            return self._tokens_to_image(tokens, width, height)
        if len(hex_only) % 8 == 0 and len(hex_only) % 6 != 0:
            tokens = [hex_only[i:i + 8] for i in range(0, len(hex_only), 8)]
            return self._tokens_to_image(tokens, width, height)
        if len(hex_only) % 6 == 0:
            tokens = [hex_only[i:i + 6] for i in range(0, len(hex_only), 6)]
            return self._tokens_to_image(tokens, width, height)
        return None

    def _linear_interpolate_image(self, current_img: QImage, next_img: QImage, t: float = 0.5) -> QImage:
        a = current_img.convertToFormat(QImage.Format_RGBA8888)
        b = next_img.convertToFormat(QImage.Format_RGBA8888)
        if a.size() != b.size():
            b = b.scaled(a.width(), a.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation)

        a_bits = a.bits()
        b_bits = b.bits()
        a_bits.setsize(a.byteCount())
        b_bits.setsize(b.byteCount())

        h, w = a.height(), a.width()
        arr_a = np.frombuffer(bytes(a_bits), dtype=np.uint8).reshape((h, w, 4)).astype(np.float32)
        arr_b = np.frombuffer(bytes(b_bits), dtype=np.uint8).reshape((h, w, 4)).astype(np.float32)
        arr_out = np.clip(arr_a * (1.0 - t) + arr_b * t, 0, 255).astype(np.uint8)
        qimg = QImage(arr_out.data, w, h, w * 4, QImage.Format_RGBA8888)
        return qimg.copy()

    def _build_blank_object_canvas_data(self, object_id: str, object_type: str) -> dict:
        width = self.canvas.canvas_width
        height = self.canvas.canvas_height
        count = 8 if object_type == "stack" else 1
        layer_type = "slice" if object_type == "stack" else object_type
        layer_prefix = "Slice" if object_type == "stack" else "Layer"
        layers = []
        for _ in range(count):
            img = QImage(width, height, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            layers.append(img)
        return {
            "canvas_width": width,
            "canvas_height": height,
            "layers": [l.copy() for l in layers],
            "layer_names": [f"{layer_prefix} {i + 1}" for i in range(count)],
            "layer_visible": [True] * count,
            "layer_opacity": [255] * count,
            "layer_locked": [False] * count,
            "layer_types": [layer_type] * count,
            "layer_object_ids": [object_id] * count,
            "layer_blend_modes": ["Normal"] * count,
            "frames": [[l.copy() for l in layers]],
            "current_frame": 0,
            "active_layer": 0,
        }

    def _ensure_ai_object(self, item: dict) -> str | None:
        name = str(item.get("name") or "Sprite").strip() or "Sprite"
        obj_type = str(item.get("type") or "sprite").lower()
        if obj_type not in ("stack", "sprite", "texture"):
            obj_type = "sprite"

        theme = str(item.get("scene_type") or "default").strip().lower()
        oid = None
        for obj in self.canvas.object_layers:
            if not isinstance(obj, dict):
                continue
            if str(obj.get("name", "")).strip().lower() == name.lower():
                oid = obj.get("id")
                obj["scene_type"] = theme
                break

        if oid is None:
            oid = f"obj_{uuid.uuid4().hex[:8]}"
            self.canvas.object_layers.append({
                "id": oid,
                "name": name,
                "type": obj_type,
                "visible": True,
                "texture_layer_index": -1,
                "texture_enabled": False,
                "texture_tile_x": 1,
                "texture_tile_y": 1,
                "texture_strength": 100,
                "scene_type": theme,
            })

        name_lower = name.lower()
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
                "climbable": "#32CD32", "player": "#1E90FF", "default": "#A0522D",
            },
        }
        palette = palettes.get(theme, palettes["default"])
        placeholder_color = QColor(palette.get("default", "#A0522D"))
        for key, value in palette.items():
            if key != "default" and key in name_lower:
                placeholder_color = QColor(value)
                break

        blank_data = self._build_blank_object_canvas_data(oid, obj_type)
        ph_img = blank_data["layers"][0]
        ph_w = ph_img.width()
        ph_h = ph_img.height()
        p = QPainter(ph_img)
        p.fillRect(0, 0, ph_w, ph_h, placeholder_color)
        if "solid" in name_lower:
            if theme == "dungeon":
                p.setPen(QPen(QColor("#1F2F2F"), 2))
                p.drawLine(0, 16, ph_w, 16)
                p.drawLine(0, 32, ph_w, 32)
                p.drawLine(0, 48, ph_w, 48)
                p.drawLine(16, 0, 16, 16)
                p.drawLine(48, 0, 48, 16)
                p.drawLine(32, 16, 32, 32)
                p.drawLine(16, 32, 16, 48)
                p.drawLine(48, 32, 48, 48)
                p.drawLine(32, 48, 32, 64)
            elif theme == "desert":
                p.setPen(QPen(QColor("#A08060"), 2))
                p.drawLine(0, 12, ph_w, 15)
                p.drawLine(0, 28, ph_w, 24)
                p.drawLine(0, 44, ph_w, 47)
                p.setPen(QPen(QColor("#C09070"), 2))
                p.drawLine(0, 20, ph_w, 18)
                p.drawLine(0, 36, ph_w, 39)
                p.drawLine(0, 52, ph_w, 50)
            else:  # grassland
                p.fillRect(0, 0, ph_w, 16, QColor("#228B22"))
                p.setPen(QPen(QColor("#1e7b1e"), 2))
                for x_pos in range(0, ph_w, 8):
                    p.drawLine(x_pos, 16, x_pos + 4, 22)
                    p.drawLine(x_pos + 4, 16, x_pos + 2, 20)
                p.setPen(QPen(QColor("#5C3A21"), 2))
                p.drawPoint(12, 28)
                p.drawPoint(36, 40)
                p.drawPoint(24, 52)
                p.drawPoint(48, 32)
        elif "climbable" in name_lower:
            rail_color = QColor("#5A4A42") if theme == "dungeon" else (QColor("#A0522D") if theme == "desert" else QColor("#2E8B57"))
            rung_color = QColor("#807060") if theme == "dungeon" else (QColor("#CD853F") if theme == "desert" else QColor("#32CD32"))
            p.setPen(QPen(rail_color, 4))
            p.drawLine(8, 0, 8, ph_h)
            p.drawLine(ph_w - 8, 0, ph_w - 8, ph_h)
            p.setPen(QPen(rung_color, 3))
            for y_pos in range(8, ph_h, 12):
                p.drawLine(8, y_pos, ph_w - 8, y_pos)
        elif "loot" in name_lower:
            p.setPen(QPen(QColor("#4A3B32"), 3))
            p.drawRect(8, 16, ph_w - 16, ph_h - 24)
            p.fillRect(ph_w // 2 - 4, 28, 8, 8, QColor("#FFD700"))
            p.setPen(QPen(QColor("#000000"), 1))
            p.drawRect(ph_w // 2 - 4, 28, 8, 8)
        elif "enemy" in name_lower:
            p.setPen(QPen(QColor("#7B0000") if theme == "dungeon" else QColor("#5C0000"), 4))
            p.drawLine(12, 12, ph_w - 12, ph_h - 12)
            p.drawLine(ph_w - 12, 12, 12, ph_h - 12)
        elif "player" in name_lower:
            p.setPen(QPen(QColor("#00008B"), 3))
            p.drawRoundedRect(16, 8, ph_w - 32, ph_h - 16, 12, 12)
            p.fillRect(24, 16, ph_w - 48, 12, QColor("#E0FFFF"))
        p.end()
        blank_data["layers"][0] = ph_img
        blank_data["frames"][0][0] = ph_img.copy()

        self._object_canvas_data[oid] = blank_data
        return oid

    def _on_scene_parsed(self, payload: dict, prompt: str):
        self._on_ai_scene_parsed(payload, prompt)

    def _get_left_context_for_ui(self) -> list[list[int]] | None:
        if not hasattr(self, "scene_ui_panel") or not hasattr(self.scene_ui_panel, "target_screen_spin"):
            return None
        target_idx = self.scene_ui_panel.target_screen_spin.value() - 1
        if target_idx <= 0:
            return None
        prev_grid = self._get_screen_grid(target_idx - 1)
        return [row[-8:] for row in prev_grid]

    def _get_screen_grid(self, screen_idx: int) -> list[list[int]]:
        grid = [[0 for _ in range(16)] for _ in range(16)]
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if not scene:
            return grid

        num_screens = self.sandbox_stage.num_screens if hasattr(self, "sandbox_stage") else 1
        cols = 16 * num_screens
        object_map = {
            o.get("id"): o
            for o in getattr(self.canvas, "object_layers", [])
            if isinstance(o, dict) and o.get("id")
        }
        value_by_name = {
            "solid": 1,
            "loot": 2,
            "enemy": 3,
            "climbable": 4,
            "player": 5,
        }

        for placement in scene.placements:
            meta = object_map.get(placement.object_id)
            if not meta:
                continue
            name = str(meta.get("name", "")).strip().lower()
            value = next((v for key, v in value_by_name.items() if key in name), 0)
            if not value:
                continue
            nx = max(0.0, min(1.0, 0.5 + placement.offset_x / max(1.0, float(self.canvas.canvas_width))))
            ny = max(0.0, min(1.0, 0.5 + placement.offset_y / max(1.0, float(self.canvas.canvas_height))))
            size_w = max(0.001, min(1.0, float(getattr(placement, "size_w", 0.0625 / max(1, num_screens)))))
            size_h = max(0.001, min(1.0, float(getattr(placement, "size_h", 0.0625))))
            col_global = int(round((nx - size_w / 2.0) * cols))
            row = int(round((ny - size_h / 2.0) * 16))
            obj_screen = col_global // 16
            obj_local_col = col_global % 16
            if obj_screen == screen_idx and 0 <= obj_local_col < 16 and 0 <= row < 16:
                grid[row][obj_local_col] = value
        return grid

    def _on_ai_scene_parsed(self, payload: dict, prompt: str):
        # -- Problem 2: gate to Sandbox only --
        current_ws = getattr(self, "current_workspace", "create")
        if current_ws != "sandbox":
            reply = QMessageBox.question(
                self,
                "AI Scene",
                "AI Scene generation places objects in the Sandbox workspace.\n"
                "Switch to Sandbox now and apply the scene?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return
            self._switch_workspace("sandbox")

        placements = parse_ai_scene_payload(payload)
        if not placements:
            self.statusBar().showMessage("AI scene parser returned no objects.", 2500)
            return

        target_screen = 0
        if hasattr(self, "scene_ui_panel") and hasattr(self.scene_ui_panel, "target_screen_spin"):
            target_screen = self.scene_ui_panel.target_screen_spin.value() - 1
        num_screens = self.sandbox_stage.num_screens if hasattr(self, "sandbox_stage") else 1

        applied = apply_ai_scene_layout(
            self.scene_manager,
            self._active_scene_id,
            placements,
            self._ensure_ai_object,
            self.canvas.canvas_width,
            self.canvas.canvas_height,
            target_screen=target_screen,
            num_screens=num_screens,
        )
        if not applied:
            self.statusBar().showMessage("AI scene application failed.", 2500)
            return

        target_object_id = applied[0].object_id
        if target_object_id != self._active_object_id:
            self._switch_to_object(target_object_id)
        else:
            self._active_object_id = target_object_id
        self._mark_modified()
        self._refresh_all()
        from collections import Counter
        name_counts = Counter(
            str(obj.get("name", "")).strip()
            for obj in placements
            if str(obj.get("name", "")).strip()
        )
        parts = [f"{n}× {name}" for name, n in name_counts.items()]
        objects_str = ", ".join(parts)
        theme = (payload.get("scene_metadata") or {}).get("global_theme", "")
        model = payload.get("model", "AI")
        if theme and theme not in ("default", ""):
            summary = f"Scene parsed [{model}] — {theme}: {objects_str}"
        else:
            summary = f"Scene parsed [{model}] — {objects_str}"
        self.statusBar().showMessage(summary, 4500)
        if hasattr(self, "ai_chat_panel"):
            self.ai_chat_panel.add_message("ai", summary)

    def _open_ai_assist_prompt(self):
        idx = self.right_tabs.indexOf(self.ai_gen_panel)
        if idx >= 0:
            self.right_tabs.setCurrentIndex(idx)

    def _refresh_sandbox_object_list(self, objects):
        if not hasattr(self, "sandbox_object_list"):
            return
        self.sandbox_object_list.clear()
        for obj in objects or []:
            if not isinstance(obj, dict):
                continue
            label = str(obj.get("label") or obj.get("name") or obj.get("object") or "Object")
            try:
                x = float(obj.get("x", 0.0))
                y = float(obj.get("y", 0.0))
                w = float(obj.get("w", 0.0))
                h = float(obj.get("h", 0.0))
                depth = float(obj.get("depth", 0.0))
            except (TypeError, ValueError):
                x, y, w, h, depth = 0.0, 0.0, 0.0, 0.0, 0.0
            item = QListWidgetItem(f"{label} ({x:.0%}, {y:.0%}) {w:.0%}x{h:.0%} z{depth:g}")
            item.setData(Qt.UserRole, str(obj.get("id") or ""))
            self.sandbox_object_list.addItem(item)

    def _on_sandbox_object_item_clicked(self, item):
        object_id = item.data(Qt.UserRole)
        if hasattr(self, "sandbox_stage"):
            self.sandbox_stage.select_object(str(object_id or ""))
        self._on_stage_object_selected(str(object_id or ""))

    def _toggle_sandbox_stage_preview(self, checked: bool):
        if not hasattr(self, "sandbox_stage"):
            return
        self.sandbox_stage.set_preview_enabled(checked)
        if checked:
            self._refresh_sandbox_stage_sprites()
        self.statusBar().showMessage(
            "Sandbox stage preview map enabled." if checked else "Sandbox stage layout view enabled.",
            1600,
        )

    def _zoom_sandbox_stage(self, factor: float):
        if not hasattr(self, "sandbox_stage"):
            return
        self.sandbox_stage.zoom_view(factor)
        self.statusBar().showMessage(
            f"Sandbox stage zoom: {self.sandbox_stage.view_zoom():.2f}x",
            1200,
        )

    def _reset_sandbox_stage_view(self):
        if not hasattr(self, "sandbox_stage"):
            return
        self.sandbox_stage.reset_view()
        self.statusBar().showMessage("Sandbox stage view reset.", 1200)

    def _on_stage_object_selected(self, object_id: str):
        if hasattr(self, "sandbox_object_list"):
            for i in range(self.sandbox_object_list.count()):
                item = self.sandbox_object_list.item(i)
                if item.data(Qt.UserRole) == object_id:
                    self.sandbox_object_list.setCurrentRow(i)
                    break
        stage_obj = None
        if hasattr(self, "sandbox_stage"):
            stage_obj = next((o for o in self.sandbox_stage.objects() if str(o.get("id", "")) == str(object_id or "")), None)
        self._select_stack_hierarchy_object(str((stage_obj or {}).get("object_id") or object_id or ""))
        self._sync_stack_controls_for_active_layer()

    def _select_stack_hierarchy_object(self, object_id: str):
        if not object_id or not hasattr(self, "stack_hierarchy"):
            return
        for i in range(self.stack_hierarchy.topLevelItemCount()):
            root = self.stack_hierarchy.topLevelItem(i)
            for j in range(root.childCount()):
                item = root.child(j)
                if item.data(0, Qt.UserRole + 2) == "object" and item.data(0, Qt.UserRole) == object_id:
                    self.stack_hierarchy.blockSignals(True)
                    self.stack_hierarchy.setCurrentItem(item)
                    self.stack_hierarchy.blockSignals(False)
                    return

    def _on_stage_object_moved(self, object_id: str, new_x: float, new_y: float):
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if scene:
            placement = scene.get_placement_by_id(str(object_id or "")) or scene.get_placement(str(object_id or ""))
            if placement:
                num_sc = self.sandbox_stage.num_screens if hasattr(self, "sandbox_stage") else 1
                obj_w = 0.0625 / num_sc
                obj_h = 0.0625
                if hasattr(self, "sandbox_stage"):
                    for obj in self.sandbox_stage.objects():
                        if str(obj.get("id", "")) == str(object_id or ""):
                            obj_w = float(obj.get("w", obj_w) or obj_w)
                            obj_h = float(obj.get("h", obj_h) or obj_h)
                            break
                center_x = float(new_x) + obj_w / 2.0
                center_y = float(new_y) + obj_h / 2.0
                placement.offset_x = (center_x - 0.5) * float(self.canvas.canvas_width)
                placement.offset_y = (center_y - 0.5) * float(self.canvas.canvas_height)
                self._canvas_dirty_for_3d = True
                self._mark_modified()
                self._update_3d_preview()
        if hasattr(self, "sandbox_stage"):
            self._refresh_sandbox_object_list(self.sandbox_stage.objects())
        self.statusBar().showMessage(f"Moved object to ({new_x:.0%}, {new_y:.0%}).", 1600)

    def _sync_sandbox_stage_from_active_scene(self):
        if not hasattr(self, "sandbox_stage"):
            return
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if scene is None:
            self.sandbox_stage.clear_scene()
            self._refresh_sandbox_object_list([])
            return

        object_map = {
            o.get("id"): o
            for o in getattr(self.canvas, "object_layers", [])
            if isinstance(o, dict) and o.get("id")
        }
        num_screens = self.sandbox_stage.num_screens
        stage_objects = []
        for placement in scene.placements:
            meta = object_map.get(placement.object_id)
            if not meta:
                continue
            nx = max(0.0, min(1.0, 0.5 + placement.offset_x / max(1.0, float(self.canvas.canvas_width))))
            ny = max(0.0, min(1.0, 0.5 + placement.offset_y / max(1.0, float(self.canvas.canvas_height))))
            size = max(0.01, min(1.0, 0.0625 * float(placement.scale or 1.0)))
            w_size = size / num_screens
            stage_objects.append({
                "id": placement.id,
                "object_id": placement.object_id,
                "label": meta.get("name", "Object"),
                "name": meta.get("name", "Object"),
                "type": meta.get("type", "stack"),
                "x": max(0.0, min(1.0 - w_size, nx - w_size / 2.0)),
                "y": max(0.0, min(1.0 - size, ny - size / 2.0)),
                "w": w_size,
                "h": size,
                "visible": placement.visible,
                "scene_type": meta.get("scene_type", "default"),
            })
        self.sandbox_stage.set_scene(stage_objects)
        self._refresh_sandbox_stage_sprites()
        self._refresh_sandbox_object_list(self.sandbox_stage.objects())

    def _refresh_sandbox_stage_sprites(self):
        if not hasattr(self, "sandbox_stage"):
            return
        images = {}
        for obj in self.sandbox_stage.objects():
            if not isinstance(obj, dict):
                continue
            pid = str(obj.get("id") or "")
            oid = str(obj.get("object_id") or obj.get("id") or "")
            if not pid or not oid:
                continue
            pixmap = self._sandbox_sprite_pixmap_for_object(oid)
            if pixmap and not pixmap.isNull():
                images[pid] = pixmap
        self.sandbox_stage.set_sprite_images(images)

    def _sandbox_sprite_pixmap_for_object(self, object_id: str) -> QPixmap | None:
        image = self._compose_object_sprite_image(object_id)
        if image is None or image.isNull():
            return None
        return QPixmap.fromImage(image)

    def _compose_object_sprite_image(self, object_id: str) -> QImage | None:
        if self._active_object_id:
            self._save_canvas_to_object(self._active_object_id)

        data = self._object_canvas_data.get(object_id)
        if object_id == self._active_object_id:
            layers = list(getattr(self.canvas, "layers", []))
            layer_visible = list(getattr(self.canvas, "layer_visible", []))
            layer_opacity = list(getattr(self.canvas, "layer_opacity", []))
            layer_types = list(getattr(self.canvas, "layer_types", []))
            width = int(getattr(self.canvas, "canvas_width", 64))
            height = int(getattr(self.canvas, "canvas_height", 64))
        elif data:
            layers = list(data.get("layers", []))
            layer_visible = list(data.get("layer_visible", []))
            layer_opacity = list(data.get("layer_opacity", []))
            layer_types = list(data.get("layer_types", []))
            width = int(data.get("canvas_width", self.canvas.canvas_width))
            height = int(data.get("canvas_height", self.canvas.canvas_height))
        else:
            return None

        composed = QImage(max(1, width), max(1, height), QImage.Format_ARGB32)
        composed.fill(Qt.transparent)
        painter = QPainter(composed)
        for i, layer in enumerate(layers):
            if not isinstance(layer, QImage) or layer.isNull():
                continue
            if i < len(layer_visible) and not layer_visible[i]:
                continue
            ltype = layer_types[i] if i < len(layer_types) else "slice"
            if ltype == "texture":
                continue
            opacity = layer_opacity[i] if i < len(layer_opacity) else 255
            painter.setOpacity(max(0.0, min(1.0, float(opacity) / 255.0)))
            painter.drawImage(0, 0, layer)
        painter.end()

        if not self._image_has_visible_pixels(composed):
            return None
        return composed

    @staticmethod
    def _image_has_visible_pixels(image: QImage) -> bool:
        if image is None or image.isNull():
            return False
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    return True
        return False

    def _clear_sandbox_scene(self):
        if hasattr(self, "sandbox_stage"):
            self.sandbox_stage.clear_scene()
        if hasattr(self, "sandbox_object_list"):
            self.sandbox_object_list.clear()
        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if scene:
            scene.placements = []
            scene.active_object_id = None
        self._active_object_id = None
        self._mark_modified()
        self._refresh_all()

    def _delete_selected_placement(self):
        if not hasattr(self, "sandbox_stage"):
            return
        selected_id = getattr(self.sandbox_stage, "_selected_id", "")
        if not selected_id and hasattr(self, "sandbox_object_list"):
            item = self.sandbox_object_list.currentItem()
            if item:
                selected_id = item.data(Qt.UserRole)
        if not selected_id:
            self.statusBar().showMessage("No scene object selected to delete.", 1600)
            return

        scene = self.scene_manager.get_active_scene() if self.scene_manager else None
        if not scene:
            return
        removed = scene.remove_placement_by_id(str(selected_id))
        if not removed:
            removed = scene.remove_object(str(selected_id))
        if not removed:
            self.statusBar().showMessage("Failed to delete object placement.", 1600)
            return

        self.sandbox_stage.select_object("")
        self._sync_sandbox_stage_from_active_scene()
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage("Deleted selected object.", 1600)

    def _on_screens_changed(self, value: int):
        if hasattr(self, "sandbox_stage"):
            self.sandbox_stage.num_screens = value
            self._update_sandbox_stage_size()
            self._sync_sandbox_stage_from_active_scene()
        if hasattr(self, "scene_ui_panel") and hasattr(self.scene_ui_panel, "target_screen_spin"):
            self.scene_ui_panel.target_screen_spin.setRange(1, max(1, int(value)))

    def _update_sandbox_stage_size(self):
        if not hasattr(self, "sandbox_stage"):
            return
        viewport_h = 0
        if hasattr(self, "sandbox_scroll"):
            viewport_h = self.sandbox_scroll.viewport().height()
        self.sandbox_stage.update_stage_dimensions(viewport_h or self.sandbox_stage.height())

    def _toggle_scene_tips(self, checked: bool):
        self.scene_tips_toggle.setText(("▾" if checked else "▸") + " Scene Prompt Tips")
        self.scene_tips_frame.setVisible(checked)

    def _scene_prompt_tips_text(self) -> str:
        guide_path = Path(__file__).parent / "ai_prompt_guide.txt"
        if not guide_path.exists():
            return "Use positions like left, right, top-left, foreground, and background."
        lines = guide_path.read_text(encoding="utf-8").splitlines()
        picked = []
        capture = False
        for line in lines:
            upper = line.upper()
            if "SELECTION-BASED GENERATION" in upper or "TIPS" in upper:
                capture = True
            elif capture and line.startswith("#"):
                capture = False
            if capture and line.strip():
                picked.append(line.strip())
            if len(picked) >= 12:
                break
        return "\n".join(picked[:12]) or "Mention objects, counts, and positions: two trees left, rock foreground."

    def _on_sandbox_chat_send(self, text: str, context: dict) -> None:
        guide_path = Path(__file__).parent / "ai_prompt_guide.txt"
        guide = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""
        system = (
            "You are a scene layout assistant for SpriteStack Studio. "
            "Help the user write prompts for the scene parser, which places "
            "2D game objects (trees, rocks, walls, enemies, etc.) on a top-down "
            "level canvas.\n\n"
            f"PROMPT GUIDE:\n{guide}"
        )
        self._dispatch_chat_to_ai(self.sandbox_chat, text, system, context)

    def _dispatch_chat_to_ai(self, panel, text: str, system: str, context: dict):
        payload = {"message": text, "context": {**(context or {}), "system": system}}
        self._post_ai_json(
            "/chat",
            payload,
            lambda data, p=panel: self._on_sandbox_chat_response(p, data),
            "Sandbox AI chat",
            on_error=lambda _err, p=panel: p.set_generating(False),
        )

    def _on_sandbox_chat_response(self, panel, data: dict):
        panel.set_generating(False)
        reply = data.get("reply") or data.get("text") or "No response."
        panel.add_message("ai", str(reply))
        suggestions = data.get("suggestions", [])
        if isinstance(suggestions, list) and suggestions:
            panel.set_suggestions([str(s) for s in suggestions if str(s).strip()])

    def _request_ai_sprite(self, prompt: str):
        pass

    def _on_ai_generate_requested(self, payload: dict):
        """
        Route the generate payload to the correct API endpoint based on mode,
        then apply the result to the canvas.
        """
        mode = str(payload.get("mode") or "full")
        request_payload = dict(payload)
        request_payload["width"] = int(self.canvas.canvas_width)
        request_payload["height"] = int(self.canvas.canvas_height)

        if mode in ("fill_selection", "inpaint"):
            sel = self._get_selection_region_hex()
            if sel is None:
                self.statusBar().showMessage(
                    "No selection active — switch to Full Sprite mode or make a selection.",
                    3000,
                )
                self.ai_gen_panel.set_generating(False)
                return
            request_payload["selection"] = sel
            request_payload["width"] = int(sel["width"])
            request_payload["height"] = int(sel["height"])

        endpoint = "/inpaint-region" if mode in ("fill_selection", "inpaint") else "/generate-sprite"
        self._post_ai_json(
            endpoint,
            request_payload,
            lambda data: self._on_ai_generate_ready(data, request_payload),
            f"AI {mode} generation",
            on_error=lambda _err: self.ai_gen_panel.set_generating(False),
        )
        self.statusBar().showMessage(f"Generating sprite ({mode})…", 0)

    def _on_ai_generate_ready(self, data: dict, original_payload: dict):
        """
        Apply the generated image to the canvas according to output_mode.
        For inpaint/fill_selection modes, composite the result back into
        the selection region only. For full/recolor, use insert_image_layer.
        """
        self.ai_gen_panel.set_generating(False)

        image = self._decode_ai_image(data)
        if image is None:
            self.statusBar().showMessage("AI response contained no valid image data.", 3000)
            return

        mode = str(original_payload.get("mode") or "full")
        output_mode = str(original_payload.get("output_mode") or "new_layer")

        self.canvas.save_undo_state()
        current_idx = self.canvas.active_layer

        if mode in ("fill_selection", "inpaint"):
            if self.canvas.selection_rect is None:
                self.statusBar().showMessage("Selection was cleared before generation completed.", 3000)
                return
            rect = self.canvas.selection_rect
            scaled = image.scaled(rect.width(), rect.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
            scaled = scaled.convertToFormat(QImage.Format_ARGB32)
            selection_mask = self.canvas.selection_mask

            if output_mode == "new_layer":
                full = QImage(self.canvas.canvas_width, self.canvas.canvas_height, QImage.Format_ARGB32)
                full.fill(Qt.transparent)
                if selection_mask is not None:
                    for dy in range(rect.height()):
                        for dx in range(rect.width()):
                            cx = rect.x() + dx
                            cy = rect.y() + dy
                            if not (0 <= cx < full.width() and 0 <= cy < full.height()):
                                continue
                            if selection_mask.pixelColor(cx, cy).alpha() <= 0:
                                continue
                            full.setPixelColor(cx, cy, scaled.pixelColor(dx, dy))
                else:
                    painter = QPainter(full)
                    painter.drawImage(rect.x(), rect.y(), scaled)
                    painter.end()
                self.canvas.insert_image_layer(full, name=f"AI Fill {len(self.canvas.layer_names) + 1}")
            else:
                layer = self.canvas.layers[current_idx]
                if selection_mask is not None:
                    for dy in range(rect.height()):
                        for dx in range(rect.width()):
                            cx = rect.x() + dx
                            cy = rect.y() + dy
                            if not (0 <= cx < layer.width() and 0 <= cy < layer.height()):
                                continue
                            if selection_mask.pixelColor(cx, cy).alpha() <= 0:
                                continue
                            src = scaled.pixelColor(dx, dy)
                            if output_mode == "blend":
                                dst = layer.pixelColor(cx, cy)
                                layer.setPixelColor(
                                    cx,
                                    cy,
                                    QColor(
                                        int(dst.red() * 0.3 + src.red() * 0.7),
                                        int(dst.green() * 0.3 + src.green() * 0.7),
                                        int(dst.blue() * 0.3 + src.blue() * 0.7),
                                        int(dst.alpha() * 0.3 + src.alpha() * 0.7),
                                    ),
                                )
                            else:
                                layer.setPixelColor(cx, cy, src)
                else:
                    painter = QPainter(layer)
                    if output_mode == "blend":
                        painter.setOpacity(0.7)
                    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    painter.drawImage(rect.x(), rect.y(), scaled)
                    painter.end()
                self.canvas.active_layer = current_idx
                self.canvas.save_current_frame()
        else:
            self.canvas.insert_image_layer(image, name=f"AI Sprite {len(self.canvas.layer_names) + 1}")

        self.canvas.update()
        self.canvas.canvas_modified.emit()
        self._mark_modified()
        self._refresh_layers()
        self._refresh_timeline()
        self.statusBar().showMessage("AI generation complete.", 3000)

        if hasattr(self, "ai_chat_panel"):
            suggestions = [
                "Make it more detailed",
                "Change the colour palette",
                "Add an outline",
                "Generate a variation",
            ]
            self.ai_chat_panel.set_suggestions(suggestions)
            self.ai_chat_panel.add_message(
                "ai",
                f"Done! Generated using mode '{mode}'. "
                "Try selecting a region and using 'Inpaint Region' to refine specific parts.",
            )

        self._refresh_ai_panel_context()

    def _on_ai_chat_send(self, message: str, context: dict):
        """Forward a chat message to /chat and display the response."""
        payload = {"message": message, "context": context}
        self._post_ai_json(
            "/chat",
            payload,
            self._on_ai_chat_response,
            "AI chat",
            on_error=lambda _err: self.ai_chat_panel.set_generating(False),
        )

    def _on_ai_chat_response(self, data: dict):
        self.ai_chat_panel.set_generating(False)
        reply = data.get("reply") or data.get("text") or "No response."
        self.ai_chat_panel.add_message("ai", str(reply))
        suggestions = data.get("suggestions", [])
        if isinstance(suggestions, list) and suggestions:
            self.ai_chat_panel.set_suggestions([str(s) for s in suggestions if str(s).strip()])

    def _refresh_ai_panel_context(self, *_args):
        if hasattr(self, "ai_gen_panel"):
            self.ai_gen_panel.refresh_context(self.canvas)
        if hasattr(self, "ai_chat_panel"):
            mode = "full"
            if hasattr(self, "ai_gen_panel"):
                mode = self.ai_gen_panel.current_mode()
            self.ai_chat_panel.set_current_mode(mode)
            self.ai_chat_panel.update_context(self.canvas)

    def _on_ai_sprite_ready(self, payload, prompt: str):
        # -- Problem 1: only allow in Create or Animate --
        current_workspace = getattr(self, "current_workspace", "create")
        if current_workspace in ("sandbox", "texture"):
            QMessageBox.information(
                self,
                "AI Sprite",
                "AI sprite generation only works in the Create or Animate workspace.",
            )
            return

        image = self._decode_ai_image(payload)
        if image is None:
            self.statusBar().showMessage("AI sprite response missing valid hex image data.", 3000)
            return

        # Scale to canvas dimensions if needed
        cw, ch = self.canvas.canvas_width, self.canvas.canvas_height
        if image.width() != cw or image.height() != ch:
            image = image.scaled(cw, ch, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        self.canvas.save_undo_state()
        layer_name = f"AI: {prompt[:24]}"
        idx = self.canvas.insert_image_layer(image, name=layer_name)
        if idx < 0:
            self.statusBar().showMessage("Failed to insert AI sprite layer.", 2500)
            return
        self.canvas.active_layer = idx
        self._mark_modified()
        self._refresh_layers()
        self._refresh_timeline()
        self.statusBar().showMessage(f"AI sprite added from prompt: {prompt}", 3000)

    def _predict_intermediate_frames(self):
        total = self.canvas.get_frame_count()
        pair = self.timeline.selected_frame_pair() if hasattr(self.timeline, "selected_frame_pair") else None
        if pair is None or abs(pair[1] - pair[0]) != 1:
            self.statusBar().showMessage("Select two adjacent frames to use AI Tween.", 2800)
            return
        current_idx, next_idx = pair

        current_img = self.canvas.get_flat_frame(current_idx)
        next_img = self.canvas.get_flat_frame(next_idx)
        if current_img is None or next_img is None:
            self.statusBar().showMessage("Could not read source frames for prediction.", 2800)
            return

        payload = {
            "current_frame": {
                "width": current_img.width(),
                "height": current_img.height(),
                "hex": self._qimage_to_hex(current_img),
            },
            "next_frame": {
                "width": next_img.width(),
                "height": next_img.height(),
                "hex": self._qimage_to_hex(next_img),
            },
            "num_intermediate": 1,
        }
        self._post_ai_json(
            "/tween-frames",
            payload,
            lambda data: self._on_tween_frames_ready(data, current_idx, current_img, next_img),
            "Tween prediction",
            on_error=lambda _err: self.statusBar().showMessage(
                "AI Tween failed. Select two adjacent frames and try again.", 3200
            ),
        )
        self.statusBar().showMessage("Generating AI tween frame...", 2200)

    def _on_tween_frames_ready(self, payload, current_idx: int, current_img: QImage, next_img: QImage):
        confidence = 0.0
        ai_frame_payload = None

        if isinstance(payload, dict):
            try:
                confidence = float(payload.get("confidence", payload.get("score", 0.0)))
            except (TypeError, ValueError):
                confidence = 0.0
            if isinstance(payload.get("frames"), list) and payload["frames"]:
                ai_frame_payload = payload["frames"][0]
            elif isinstance(payload.get("intermediate_frames"), list) and payload["intermediate_frames"]:
                ai_frame_payload = payload["intermediate_frames"][0]
            else:
                ai_frame_payload = payload.get("frame") or payload.get("intermediate") or payload.get("result")

        ai_frame = self._decode_ai_image(ai_frame_payload) if ai_frame_payload is not None else None
        if ai_frame is not None and confidence >= self._ai_tween_confidence_threshold:
            chosen = ai_frame
            source = "AI model"
        else:
            chosen = self._linear_interpolate_image(current_img, next_img, 0.5)
            source = "NumPy interpolation fallback"

        self.canvas.save_undo_state()
        self.canvas.insert_frame_after(current_idx)
        inserted_idx = current_idx + 1
        if not self.canvas.set_frame_flat_image(inserted_idx, chosen, self.canvas.active_layer):
            self.statusBar().showMessage("Failed to apply predicted frame.", 2500)
            return
        self.canvas.load_frame(inserted_idx)
        if hasattr(self.timeline, "clear_secondary_selection"):
            self.timeline.clear_secondary_selection()
        self._mark_modified()
        self._refresh_timeline()
        self._refresh_layers()
        self.statusBar().showMessage(f"Intermediate frame generated using {source}.", 2800)

    # ------------------------------------------------------------------
    # Signal handlers - Canvas events
    # ------------------------------------------------------------------

    def _on_canvas_modified(self):
        """
        FIX: no longer calls full _refresh_layers() on every stroke.
        Instead updates only the active layer's thumbnail incrementally,
        then schedules a full refresh at low priority via a single-shot timer
        so rapid strokes are coalesced into one panel update.
        """
        self.is_modified = True
        self._canvas_dirty_for_3d = True
        self._update_title()

        # Incremental thumbnail update for the active layer
        idx = self.canvas.active_layer
        if 0 <= idx < len(self.canvas.layers):
            self.layer_panel.update_thumbnail(idx, self.canvas.layers[idx])

        # Coalesce rapid canvas_modified signals into one delayed full refresh
        # Fix 8: timer already created in __init__ - no hasattr guard needed
        self._refresh_timer.start(150)   # ms - coalesces fast strokes

    def _on_color_picked(self, color: QColor):
        self.palette_panel.set_primary_color(color)

    def _on_cursor_moved(self, x: int, y: int):
        self.pos_label.setText(f"{x}, {y}")
        self.zoom_label.setText(f"Zoom: {self.canvas.zoom:.1f}x")

    def _on_pivot_changed(self, px: int, py: int):
        nx = px / max(1, self.canvas.canvas_width)
        ny = py / max(1, self.canvas.canvas_height)
        self.preview_panel.set_pivot(nx, ny)
        if hasattr(self, "stack_preview_panel"):
            self.stack_preview_panel.set_pivot(nx, ny)

    def _on_tab_changed(self, index: int):
        """Track which tab is active (0=Scene, 1=Palette)."""
        pass  # No 3D tab in sidebar now; preview lives in Stack workspace

    def _toggle_inline_3d(self, checked: bool):
        """Toggle the inline 3D stack preview overlay on the canvas area."""
        self._inline_3d_active = checked
        if checked:
            # Show the 3D preview on top of the canvas
            self.inline_3d_preview.setGeometry(self.canvas.geometry())
            self.inline_3d_preview.setVisible(True)
            self.inline_3d_preview.raise_()
            self._3d_toggle_btn.raise_()
            self._axis_toggle_btn.raise_()
            # Feed current layers to the inline preview
            vis_layers = [
                self.canvas.layers[i]
                for i in range(len(self.canvas.layers))
                if i < len(self.canvas.layer_visible) and self.canvas.layer_visible[i]
            ]
            self.inline_3d_preview.set_layers(vis_layers)
        else:
            self.inline_3d_preview.setVisible(False)
        self._3d_toggle_btn.setText("2D" if checked else "3D")

    def _toggle_axis_planes(self, checked: bool):
        """Toggle the visibility of green/red axis guide planes on the canvas."""
        if hasattr(self.canvas, 'show_axis_planes'):
            self.canvas.show_axis_planes = checked
        if hasattr(self.canvas, 'show_3d_plane'):
            self.canvas.show_3d_plane = checked
        self.canvas.update()

    def _on_palette_color_changed(self, color: QColor):
        self.canvas.primary_color = color

    def _on_layer_selected(self, idx: int):
        self.canvas.active_layer = idx
        self.canvas.update()
        self._rebuild_animate_targets()
        if hasattr(self.canvas, 'hide_context_bar'):
            self.canvas.hide_context_bar()

    def _on_frame_selected(self, idx: int):
        self.canvas.load_frame(idx)
        self._refresh_layers()
        self.frame_label.setText(
            f"Frame {idx + 1}/{self.canvas.get_frame_count()}"
        )

    # ------------------------------------------------------------------
    # Layer operations
    # ------------------------------------------------------------------

    def _prompt_add_layer(self):
        """Called from the Layer menu (no name pre-supplied)."""
        n = len(self.canvas.layers) + 1
        name, ok = QInputDialog.getText(self, "New Layer", "Layer name:",
                                        text=f"Layer {n}")
        if ok:
            self._add_layer(name.strip() or f"Layer {n}")

    def _add_layer(self, name: str = ""):
        """
        FIX: accepts the name str emitted by layer_added(str).
        Original took no argument → TypeError at runtime.
        """
        if not name:
            name = f"Layer {len(self.canvas.layers) + 1}"
        self.canvas.save_undo_state()
        self.canvas.add_layer(name=name)
        # Ensure blend_modes list stays in sync
        if hasattr(self.canvas, 'layer_blend_modes'):
            while len(self.canvas.layer_blend_modes) < len(self.canvas.layers):
                self.canvas.layer_blend_modes.append("Normal")
        self._mark_modified()
        self._refresh_layers()

    def _remove_layer(self, idx: int = None):
        self.canvas.save_undo_state()
        self.canvas.remove_layer(idx)
        if hasattr(self.canvas, 'layer_blend_modes') and idx is not None:
            if 0 <= idx < len(self.canvas.layer_blend_modes):
                self.canvas.layer_blend_modes.pop(idx)
        self._mark_modified()
        self._refresh_layers()

    def _duplicate_layer(self, idx: int = None):
        self.canvas.save_undo_state()
        self.canvas.duplicate_layer(idx)
        if hasattr(self.canvas, 'layer_blend_modes') and idx is not None:
            if 0 <= idx < len(self.canvas.layer_blend_modes):
                self.canvas.layer_blend_modes.insert(
                    idx + 1, self.canvas.layer_blend_modes[idx]
                )
        self._mark_modified()
        self._refresh_layers()

    def _move_layer(self, from_idx: int, to_idx: int):
        """FIX: now saves undo state before moving."""
        self.canvas.save_undo_state()
        self.canvas.move_layer(from_idx, to_idx)
        if hasattr(self.canvas, 'layer_blend_modes'):
            bm = self.canvas.layer_blend_modes
            if 0 <= from_idx < len(bm) and 0 <= to_idx < len(bm):
                bm.insert(to_idx, bm.pop(from_idx))
        self._mark_modified()
        self._refresh_layers()

    def _change_layer_opacity(self, idx: int, value: int):
        if 0 <= idx < len(self.canvas.layer_opacity):
            self.canvas.layer_opacity[idx] = value
            self.canvas.update()
            self._mark_modified()   # FIX: opacity change was not marking dirty

    def _change_layer_blend_mode(self, idx: int, mode: str):
        """FIX: was entirely missing - blend mode changes now persist."""
        if hasattr(self.canvas, 'layer_blend_modes'):
            while len(self.canvas.layer_blend_modes) < len(self.canvas.layers):
                self.canvas.layer_blend_modes.append("Normal")
            if 0 <= idx < len(self.canvas.layer_blend_modes):
                self.canvas.layer_blend_modes[idx] = mode
                self.canvas.update()
                self._mark_modified()

    def _toggle_layer_visibility(self, idx: int, state: bool):
        """
        FIX: original ignored the emitted bool and always negated, causing
        the panel UI and canvas to drift out of sync on rapid toggles.
        Now uses the exact state the layer panel emitted.
        """
        if 0 <= idx < len(self.canvas.layer_visible):
            self.canvas.layer_visible[idx] = state
            self.canvas.update()
            self._mark_modified()
            # Only update the one row widget, not the whole list
            self.layer_panel.update_thumbnail(idx, self.canvas.layers[idx])

    def _toggle_layer_lock(self, idx: int, locked: bool):
        if 0 <= idx < len(self.canvas.layer_locked):
            self.canvas.layer_locked[idx] = locked
            self._mark_modified()   # FIX: lock change was not marking dirty

    def _rename_layer(self, idx: int, name: str):
        if 0 <= idx < len(self.canvas.layer_names):
            self.canvas.layer_names[idx] = name
            self._mark_modified()
            self._refresh_layers()

    def _centre_object(self):
        """
        Centre the sprite object in the canvas.
        Prefer stack centering (all visible layers move together).
        """
        if hasattr(self.canvas, 'center_stack_content'):
            self.canvas.center_stack_content()
            self._refresh_layers()
            self._refresh_timeline()
            self._mark_modified()
            self.statusBar().showMessage("Object centred on canvas.", 2000)
        elif hasattr(self.canvas, 'center_layer_content'):
            self.canvas.center_layer_content()
            self._refresh_layers()
            self._refresh_timeline()
            self._mark_modified()
            self.statusBar().showMessage("Object centred on canvas.", 2000)
        else:
            QMessageBox.information(
                self, "Not Available",
                "canvas.center_stack_content() is not available.\n"
                "Please update canvas.py from the latest version.")

    def _on_3d_nudge(self, dx: int, dy: int):
        """Nudge all visible layers by (dx, dy) pixels — d-pad handler."""
        cv = self.canvas
        layer_indices = [i for i, vis in enumerate(cv.layer_visible) if vis]
        if not layer_indices:
            return
        cv.save_undo_state()
        cv._shift_layers(layer_indices, dx, dy)
        cv.save_current_frame()
        cv.update()
        self._mark_modified()
        self._canvas_dirty_for_3d = True
        self.statusBar().showMessage(f"Nudged ({dx}, {dy}) px", 1200)

    def _on_3d_scale(self, delta: float):
        """Scale all slices up or down by 1 px border — real pixel resize."""
        cv = self.canvas
        step = 2 if delta > 0 else -2  # grow or shrink by 2 px total
        new_w = cv.canvas_width + step
        new_h = cv.canvas_height + step
        if new_w < 4 or new_h < 4:
            self.statusBar().showMessage("Canvas too small to shrink further.", 1500)
            return
        cv.save_undo_state()
        if step > 0:
            # Grow: expand canvas, shift content to center
            cv.resize_canvas(new_w, new_h)
            all_idx = list(range(len(cv.layers)))
            cv._shift_layers(all_idx, 1, 1)
        else:
            # Shrink: shift content, then crop
            all_idx = list(range(len(cv.layers)))
            cv._shift_layers(all_idx, -1, -1)
            cv.resize_canvas(new_w, new_h)
        cv.save_current_frame()
        cv.update()
        self._mark_modified()
        self._canvas_dirty_for_3d = True
        factor = new_w / 64.0  # relative to default 64px
        if hasattr(self, 'inline_3d_preview'):
            self.inline_3d_preview.update_scale_label(factor)
        self.statusBar().showMessage(
            f"Canvas resized to {new_w}x{new_h}", 1500)

    # ------------------------------------------------------------------
    # Object-level signal handlers (from LayerPanel tree)
    # ------------------------------------------------------------------

    def _on_object_selected(self, obj_id: str):
        """User clicked an object in the scene tree — switch canvas to it."""
        if obj_id and obj_id != self._active_object_id:
            self._switch_to_object(obj_id)

    def _on_object_add_requested(self, obj_type: str):
        """User requested a new object from the layer panel add menu."""
        if obj_type not in ("stack", "sprite", "texture"):
            obj_type = "sprite"

        w = self.canvas.canvas_width
        h = self.canvas.canvas_height
        n = len(self.canvas.object_layers) + 1
        default_name = f"{obj_type.title()} {n}"
        name, ok = QInputDialog.getText(self, "Add Object", "Object name:",
                                        text=default_name)
        if not ok:
            return
        name = (name or "").strip() or default_name

        initial_layers = 1
        if obj_type == "stack":
            slices, ok2 = QInputDialog.getInt(
                self, "Stack Slices",
                "Number of initial slices:", 8, 1, 256, 1)
            if ok2:
                initial_layers = slices
            else:
                return

        # Create global object in canvas.object_layers
        oid = f"obj_{uuid.uuid4().hex[:8]}"
        self.canvas.object_layers.append({
            "id": oid,
            "name": name,
            "type": obj_type,
            "visible": True,
            "texture_layer_index": -1,
            "texture_enabled": False,
            "texture_tile_x": 1,
            "texture_tile_y": 1,
            "texture_strength": 100,
        })

        # Add placement to active scene with automatic offset
        scene = self.scene_manager.get_active_scene()
        if scene:
            # Calculate offset based on number of existing objects
            num_objects = len(scene.placements)
            auto_offset_x = float(num_objects * 80)  # Spread objects horizontally
            scene.add_object(
                object_id=oid,
                visible=True,
                offset_x=auto_offset_x,
                offset_y=0.0,
                offset_z=0.0,
                scale=1.0,
                rotation=0.0,
                opacity=255,
            )

        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"Object created: {name}", 2000)

    def _on_object_remove_requested(self, obj_id: str):
        """Delete an object and all its layers."""
        scene = self.scene_manager.get_active_scene()
        if not scene:
            return
        # Get object metadata from canvas.object_layers
        obj = next((o for o in self.canvas.object_layers if o.get("id") == obj_id), None)
        if not obj:
            return
        if len(scene.placements) <= 1:
            QMessageBox.information(self, "Cannot Delete",
                                    "At least one object must remain in the scene.")
            return
        reply = QMessageBox.question(
            self, "Delete Object",
            f"Delete '{obj.get('name', 'Object')}' and all its layers?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        was_active = (obj_id == self._active_object_id)
        scene.remove_object(obj_id)

        # Remove from legacy metadata
        self.canvas.object_layers = [o for o in self.canvas.object_layers if o.get("id") != obj_id]
        self._object_canvas_data.pop(obj_id, None)

        if was_active and scene.placements:
            new_oid = scene.placements[0].object_id
            scene.active_object_id = new_oid
            self._active_object_id = new_oid
            if new_oid in self._object_canvas_data:
                self._load_canvas_from_object(new_oid)
            else:
                # Load from SceneModel
                self._load_scene_object_into_canvas(new_oid)
        elif was_active:
            scene.active_object_id = None
            self._active_object_id = None

        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage("Object deleted.", 2000)

    def _on_object_renamed(self, obj_id: str, new_name: str):
        """Rename a scene object."""
        scene = self.scene_manager.get_active_scene()
        if scene:
            scene.rename_object(obj_id, new_name)
        # Sync legacy metadata
        for o in self.canvas.object_layers:
            if o.get("id") == obj_id:
                o["name"] = new_name
                break
        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"Object renamed to '{new_name}'.", 2000)

    def _on_object_type_converted(self, obj_id: str, new_type: str):
        """Convert an object's type (sprite ↔ texture)."""
        scene = self.scene_manager.get_active_scene()
        if scene and scene.convert_object_type(obj_id, new_type):
            # Sync legacy metadata
            for o in self.canvas.object_layers:
                if o.get("id") == obj_id:
                    o["type"] = new_type
                    break
            self._mark_modified()
            self._refresh_all()
            self.statusBar().showMessage(f"Object type changed to {new_type}.", 2000)
        else:
            QMessageBox.information(
                self, "Conversion Not Supported",
                "Only sprite <-> texture conversion is supported.\n"
                "Stack objects cannot be converted.")

    # ------------------------------------------------------------------
    # Scene management methods
    # ------------------------------------------------------------------

    def _refresh_scene_combo(self):
        """Refresh the scene combo box with current scenes."""
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        for scene in self.scene_manager.scenes:
            self.scene_combo.addItem(scene.name, scene.id)
        # Set current index to active scene
        active_id = self.scene_manager.active_scene_id
        for i in range(self.scene_combo.count()):
            if self.scene_combo.itemData(i) == active_id:
                self.scene_combo.setCurrentIndex(i)
                break
        self.scene_combo.blockSignals(False)
        # Enable/disable delete button based on scene count
        self.scene_del_btn.setEnabled(self.scene_manager.scene_count() > 1)

    def _on_scene_changed(self, index: int):
        """Handle scene selection change."""
        if index < 0:
            return
        scene_id = self.scene_combo.itemData(index)
        if scene_id == self._active_scene_id:
            return
        # Save current canvas state before switching
        if self._active_object_id:
            self._save_canvas_to_object(self._active_object_id)
        # Switch to new scene
        self.scene_manager.set_active_scene(scene_id)
        self._active_scene_id = scene_id
        # Keep the combo's visual state in sync when called directly
        # (e.g. from _add_new_scene / _duplicate_current_scene).
        self.scene_combo.blockSignals(True)
        self.scene_combo.setCurrentIndex(index)
        self.scene_combo.blockSignals(False)
        # Load the scene's active object, or the first object from its placements.
        scene = self.scene_manager.get_active_scene()
        if scene and scene.placements:
            scene_ids = [p.object_id for p in scene.placements]
            new_oid = (getattr(scene, 'active_object_id', None)
                       if getattr(scene, 'active_object_id', None) in scene_ids
                       else scene_ids[0])
            self._active_object_id = new_oid
            self._load_scene_object_into_canvas(new_oid)
            scene.active_object_id = new_oid
        else:
            self._active_object_id = None
        self._refresh_all()
        self.statusBar().showMessage(f"Switched to scene: {scene.name if scene else 'Unknown'}", 2000)

    def _add_new_scene(self):
        """Add a new scene to the project."""
        n = self.scene_manager.scene_count() + 1
        name, ok = QInputDialog.getText(self, "New Scene", "Scene name:", text=f"Scene {n}")
        if not ok:
            return
        name = (name or "").strip() or f"Scene {n}"
        scene = self.scene_manager.add_scene(name=name, description="")
        # Create a global object and add placement to the new scene
        oid = f"obj_{uuid.uuid4().hex[:8]}"
        self.canvas.object_layers.append({
            "id": oid,
            "name": "Object 1",
            "type": "stack",
            "visible": True,
            "texture_layer_index": -1,
            "texture_enabled": False,
            "texture_tile_x": 1,
            "texture_tile_y": 1,
            "texture_strength": 100,
        })
        scene.add_object(
            object_id=oid,
            visible=True,
            offset_x=0.0,
            offset_y=0.0,
            offset_z=0.0,
            scale=1.0,
            rotation=0.0,
            opacity=255,
        )
        # Refresh UI
        self._refresh_scene_combo()
        # Switch to the new scene
        self._on_scene_changed(self.scene_combo.count() - 1)
        self._mark_modified()
        self.statusBar().showMessage(f"Created new scene: {name}", 2000)

    def _duplicate_current_scene(self):
        """Duplicate the current scene."""
        scene = self.scene_manager.get_active_scene()
        if not scene:
            return
        new_scene = self.scene_manager.duplicate_scene(scene.id)
        if new_scene:
            self._refresh_scene_combo()
            # Switch to the duplicated scene
            for i in range(self.scene_combo.count()):
                if self.scene_combo.itemData(i) == new_scene.id:
                    self._on_scene_changed(i)
                    break
            self._mark_modified()
            self.statusBar().showMessage(f"Duplicated scene: {scene.name} -> {new_scene.name}", 2000)

    def _delete_current_scene(self):
        """Delete the current scene."""
        if self.scene_manager.scene_count() <= 1:
            QMessageBox.information(self, "Cannot Delete", "At least one scene must remain in the project.")
            return
        scene = self.scene_manager.get_active_scene()
        if not scene:
            return
        reply = QMessageBox.question(
            self, "Delete Scene",
            f"Delete scene '{scene.name}' and all its objects?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.scene_manager.remove_scene(scene.id)
        self._refresh_scene_combo()
        # Scene combo will auto-select first remaining scene
        self._on_scene_changed(0)
        self._mark_modified()
        self.statusBar().showMessage("Scene deleted.", 2000)

    def _rename_current_scene(self):
        """Rename the current scene."""
        scene = self.scene_manager.get_active_scene()
        if not scene:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Scene", "New scene name:", text=scene.name)
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        self.scene_manager.rename_scene(scene.id, name)
        self._refresh_scene_combo()
        self._mark_modified()
        self.statusBar().showMessage(f"Scene renamed to '{name}'.", 2000)

    def _load_scene_object_into_canvas(self, obj_id: str):
        """Load an object's data into the canvas from _object_canvas_data or create blank."""
        # Try to load from cached canvas data first
        if obj_id in self._object_canvas_data:
            self._load_canvas_from_object(obj_id)
            return
        # Otherwise create blank canvas for this object
        obj = next((o for o in self.canvas.object_layers if o.get("id") == obj_id), None)
        if not obj:
            return
        # Create blank canvas for this object type
        obj_type = obj.get("type", "stack")
        w, h = self.canvas.canvas_width, self.canvas.canvas_height
        initial_layers = 8 if obj_type == "stack" else 1
        _blank_layer_stack(self.canvas, w, h, initial_layers)
        self.canvas.layer_types = ["slice" if obj_type == "stack" else obj_type] * initial_layers
        name_prefix = "Slice" if obj_type == "stack" else "Layer"
        self.canvas.layer_names = [f"{name_prefix} {i+1}" for i in range(initial_layers)]
        self.canvas.layer_object_ids = [obj_id] * initial_layers
        self.canvas.current_frame = 0
        self.canvas.frames = [self.canvas._copy_layers()]
        if hasattr(self.canvas, 'reset_undo'):
            self.canvas.reset_undo()
        self.canvas._checker_cache = None
        self.canvas.update()

    def _merge_layer_down(self, idx: int = None):
        if idx is None:
            idx = self.canvas.active_layer
        self.canvas.save_undo_state()
        self.canvas.merge_down(idx)
        if hasattr(self.canvas, 'layer_blend_modes') and idx is not None:
            bm = self.canvas.layer_blend_modes
            if 0 <= idx < len(bm):
                bm.pop(idx)
        self._mark_modified()
        self._refresh_layers()

    def _merge_visible_layers(self):
        """FIX: was entirely missing - no handler existed for merge_visible_requested."""
        if not hasattr(self.canvas, 'merge_visible'):
            # Fallback: flatten visible layers manually
            self.canvas.save_undo_state()
            visible_indices = [i for i, v in enumerate(self.canvas.layer_visible) if v]
            if len(visible_indices) < 2:
                return
            # Composite all visible layers onto the lowest visible one
            base_idx = visible_indices[0]
            base = self.canvas.layers[base_idx].copy()
            painter = QPainter(base)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            for i in visible_indices[1:]:
                painter.setOpacity(self.canvas.layer_opacity[i] / 255)
                painter.drawImage(0, 0, self.canvas.layers[i])
            painter.end()
            # Replace base with composite, remove the rest
            self.canvas.layers[base_idx] = base
            for i in sorted(visible_indices[1:], reverse=True):
                self.canvas.layers.pop(i)
                self.canvas.layer_names.pop(i)
                self.canvas.layer_visible.pop(i)
                self.canvas.layer_opacity.pop(i)
                self.canvas.layer_locked.pop(i)
                if hasattr(self.canvas, 'layer_types') and i < len(self.canvas.layer_types):
                    self.canvas.layer_types.pop(i)
                if hasattr(self.canvas, 'layer_object_ids') and i < len(self.canvas.layer_object_ids):
                    self.canvas.layer_object_ids.pop(i)
                if hasattr(self.canvas, 'layer_blend_modes'):
                    self.canvas.layer_blend_modes.pop(i)
            self.canvas.active_layer = min(base_idx, len(self.canvas.layers) - 1)
        else:
            self.canvas.save_undo_state()
            self.canvas.merge_visible()

        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        self._mark_modified()
        self._refresh_layers()

    def _flatten_layers(self):
        self.canvas.save_undo_state()
        flat = self.canvas.flatten_image()
        self.canvas.layers            = [flat]
        self.canvas.layer_names       = ["Flattened"]
        self.canvas.layer_visible     = [True]
        self.canvas.layer_opacity     = [255]
        self.canvas.layer_locked      = [False]
        self.canvas.layer_types       = ["sprite"]
        self.canvas.layer_object_ids  = [None]
        self.canvas.object_layers     = []
        self.canvas.layer_blend_modes = ["Normal"]  # FIX: reset blend list
        self.canvas.active_layer      = 0
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        self.canvas.update()
        self._mark_modified()
        self._refresh_layers()

    # ------------------------------------------------------------------
    # Frame / animation operations
    # ------------------------------------------------------------------

    def _add_frame(self, copy_current: bool = False):
        self.canvas.add_frame(copy_current)
        self._refresh_timeline()
        self._refresh_layers()

    def _delete_frame(self, idx: int):
        self.canvas.delete_frame(idx)
        self._refresh_timeline()
        self._refresh_layers()

    def _toggle_play(self):
        """
        Fix 3: was calling btn.toggle() then timeline._toggle_play(btn.isChecked()).
        btn.toggle() emits clicked which can itself invoke the play handler again
        if the button's clicked signal is connected - causing a double-fire.
        Now delegates to a public toggle_play() method if available, otherwise
        uses the internal method with a direct state check without toggling.
        """
        if hasattr(self.timeline, 'toggle_play'):
            self.timeline.toggle_play()
        else:
            # Fallback: flip the button state manually without re-emitting clicked
            btn = self.timeline.play_btn
            new_state = not btn.isChecked()
            btn.blockSignals(True)
            btn.setChecked(new_state)
            btn.blockSignals(False)
            self.timeline._toggle_play(new_state)

    # ------------------------------------------------------------------
    # Edit operations
    # ------------------------------------------------------------------

    def _undo(self):
        self.canvas.undo()
        self._sync_blend_modes_length()
        self._refresh_layers()

    def _redo(self):
        self.canvas.redo()
        self._sync_blend_modes_length()
        self._refresh_layers()

    def _sync_blend_modes_length(self):
        """Ensure layer_blend_modes matches len(canvas.layers) after undo/redo."""
        n = len(self.canvas.layers)
        modes = getattr(self.canvas, 'layer_blend_modes', None)
        if modes is None:
            self.canvas.layer_blend_modes = ["Normal"] * n
        elif len(modes) < n:
            modes.extend(["Normal"] * (n - len(modes)))
        elif len(modes) > n:
            self.canvas.layer_blend_modes = modes[:n]

    def _cut(self):
        self.canvas.cut_selection()
        self._refresh_layers()

    def _copy(self):
        self.canvas.copy_selection()

    def _paste(self):
        self.canvas.paste_clipboard()

    def _select_all(self):
        self.canvas.select_all()

    def _deselect(self):
        self.canvas.deselect()

    def _clear_layer(self):
        if self.canvas.selection_rect or self.canvas.selection_mask:
            self.canvas.delete_selection()
            return
        if not (0 <= self.canvas.active_layer < len(self.canvas.layers)):
            return
        self.canvas.save_undo_state()
        self.canvas.layers[self.canvas.active_layer].fill(Qt.transparent)
        self.canvas.update()
        self._mark_modified()

    def _fill_layer(self):
        if not (0 <= self.canvas.active_layer < len(self.canvas.layers)):
            return
        self.canvas.save_undo_state()
        self.canvas.layers[self.canvas.active_layer].fill(self.canvas.primary_color)
        self.canvas.update()
        self._mark_modified()

    def _resize_canvas(self):
        dlg = ResizeCanvasDialog(self, self.canvas.canvas_width,
                                 self.canvas.canvas_height)
        if dlg.exec_() != QDialog.Accepted:
            return
        self.canvas.save_undo_state()
        new_w  = dlg.width_spin.value()
        new_h  = dlg.height_spin.value()
        anchor = dlg.anchor

        # Fix 5: canvas.resize_canvas(w, h) always places content at (0,0).
        # For Centre / Bottom-Right anchors we must manually blit each layer
        # at the correct offset onto a fresh image BEFORE calling resize_canvas,
        # which then only needs to trim / pad the already-repositioned content.
        old_w, old_h = self.canvas.canvas_width, self.canvas.canvas_height

        if anchor == "Top-Left":
            ox, oy = 0, 0
        elif anchor == "Centre":
            ox = (new_w - old_w) // 2
            oy = (new_h - old_h) // 2
        else:  # Bottom-Right
            ox = new_w - old_w
            oy = new_h - old_h

        if ox != 0 or oy != 0:
            # Pre-shift every layer in every frame so resize_canvas (Top-Left)
            # lands them in the right position.
            def _shift(img):
                out = QImage(new_w, new_h, QImage.Format_ARGB32)
                out.fill(Qt.transparent)
                p = QPainter(out)
                p.drawImage(ox, oy, img)
                p.end()
                return out

            self.canvas.layers = [_shift(l) for l in self.canvas.layers]
            self.canvas.frames  = [
                [_shift(l) for l in frame]
                for frame in self.canvas.frames
            ]
            # Tell canvas its new logical size directly before resize
            self.canvas.canvas_width  = new_w
            self.canvas.canvas_height = new_h
            self.canvas.frames[self.canvas.current_frame] = self.canvas._copy_layers()
            self.canvas.pivot = (new_w // 2, new_h // 2)
            self.canvas._checker_cache = None
            self.canvas.update()
        else:
            # Plain top-left resize
            self.canvas.resize_canvas(new_w, new_h)

        self.size_label.setText(
            f"{self.canvas.canvas_width}x{self.canvas.canvas_height}"
        )
        self._mark_modified()
        self._refresh_all()

    # ------------------------------------------------------------------
    # View operations
    # ------------------------------------------------------------------

    def _zoom(self, factor: float):
        self.canvas.zoom = max(
            self.canvas.min_zoom,
            min(self.canvas.max_zoom, self.canvas.zoom * factor)
        )
        self.canvas.center_canvas()
        self.zoom_label.setText(f"Zoom: {self.canvas.zoom:.1f}x")

    def _toggle_grid(self):
        """Called from menu shortcut - also syncs the toolbar checkbox."""
        self.canvas.show_grid = not self.canvas.show_grid
        if hasattr(self, "sandbox_stage"):
            self.sandbox_stage.show_grid = self.canvas.show_grid
            self.sandbox_stage.update()
        if hasattr(self.tool_bar, "grid_cb"):
            self.tool_bar.grid_cb.setChecked(self.canvas.show_grid)
        self.canvas.update()

    def _toggle_grid_cb(self, checked: bool):
        """Called from toolbar checkbox signal."""
        self.canvas.show_grid = checked
        if hasattr(self, "sandbox_stage"):
            self.sandbox_stage.show_grid = checked
            self.sandbox_stage.update()
        self.canvas.update()

    def _set_mirror_x_from_menu(self, checked: bool):
        self.canvas.mirror_x = checked
        if hasattr(self, "view_mirror_x_action"):
            self.view_mirror_x_action.blockSignals(True)
            self.view_mirror_x_action.setChecked(checked)
            self.view_mirror_x_action.blockSignals(False)
        if hasattr(self.tool_bar, "mirror_x_cb"):
            self.tool_bar.mirror_x_cb.blockSignals(True)
            self.tool_bar.mirror_x_cb.setChecked(checked)
            self.tool_bar.mirror_x_cb.blockSignals(False)
        self.canvas.update()

    def _set_mirror_y_from_menu(self, checked: bool):
        self.canvas.mirror_y = checked
        if hasattr(self, "view_mirror_y_action"):
            self.view_mirror_y_action.blockSignals(True)
            self.view_mirror_y_action.setChecked(checked)
            self.view_mirror_y_action.blockSignals(False)
        if hasattr(self.tool_bar, "mirror_y_cb"):
            self.tool_bar.mirror_y_cb.blockSignals(True)
            self.tool_bar.mirror_y_cb.setChecked(checked)
            self.tool_bar.mirror_y_cb.blockSignals(False)
        self.canvas.update()

    # ------------------------------------------------------------------
    # 3D preview (throttled)
    # ------------------------------------------------------------------

    def _maybe_update_3d_preview(self):
        """
        Timer callback: triggers a 3D rebuild when the canvas has been
        modified and either the Sandbox workspace or inline 3D is active.
        """
        stack_ws_active = getattr(self, 'current_workspace', 'create') == 'sandbox'
        tex_ws_active = getattr(self, 'current_workspace', 'create') == 'texture'
        inline_active = getattr(self, '_inline_3d_active', False)

        if self._canvas_dirty_for_3d and (stack_ws_active or tex_ws_active or inline_active):
            self._update_3d_preview()
            self._canvas_dirty_for_3d = False

        # Keep inline 3D preview properly sized and updated
        if inline_active and self.inline_3d_preview.isVisible():
            self.inline_3d_preview.setGeometry(self.canvas.geometry())
            vis_layers = [
                self.canvas.layers[i]
                for i in range(len(self.canvas.layers))
                if i < len(self.canvas.layer_visible) and self.canvas.layer_visible[i]
            ]
            self.inline_3d_preview.set_layers(vis_layers)

    def _update_3d_preview(self):
        scene_items = self._build_scene_items_for_preview()
        self.preview_panel.update_scene(
            scene_items,
            self._preview_scene_scope,
            self._preview_focus_id,
        )
        if hasattr(self, "stack_preview_panel"):
            self.stack_preview_panel.update_scene(
                scene_items,
                self._preview_scene_scope,
                self._preview_focus_id,
            )
        px, py = self.canvas.pivot
        self.preview_panel.set_pivot(
            px / max(1, self.canvas.canvas_width),
            py / max(1, self.canvas.canvas_height),
        )
        if hasattr(self, "stack_preview_panel"):
            self.stack_preview_panel.set_pivot(
                px / max(1, self.canvas.canvas_width),
                py / max(1, self.canvas.canvas_height),
            )
        # Also feed texture workspace preview
        if hasattr(self, "tex_preview_panel"):
            self.tex_preview_panel.update_scene(
                scene_items,
                self._preview_scene_scope,
                self._preview_focus_id,
            )
            self.tex_preview_panel.set_pivot(
                px / max(1, self.canvas.canvas_width),
                py / max(1, self.canvas.canvas_height),
            )

    # ------------------------------------------------------------------
    # Texturing workspace handlers
    # ------------------------------------------------------------------

    def _refresh_texture_sources(self):
        """Rebuild the texture source combo from canvas texture layers."""
        if not hasattr(self, 'tex_source_combo'):
            return
        self.tex_source_combo.blockSignals(True)
        self.tex_source_combo.clear()
        self.tex_source_combo.addItem("(None – solid colour)")
        for i, ltype in enumerate(getattr(self.canvas, 'layer_types', [])):
            if ltype == "texture":
                name = self.canvas.layer_names[i] if i < len(self.canvas.layer_names) else f"Texture {i}"
                self.tex_source_combo.addItem(name, i)
        self.tex_source_combo.blockSignals(False)

    def _refresh_tex_workspace(self):
        """Refresh texture workspace: object list, previews, texture sources."""
        if not hasattr(self, 'tex_object_combo'):
            return
        self.tex_object_combo.blockSignals(True)
        self.tex_object_combo.clear()
        # Show only objects placed in the active scene
        for obj in self._objects_for_active_scene():
            if isinstance(obj, dict):
                oid = obj.get("id", "?")
                name = obj.get("name", oid)
                self.tex_object_combo.addItem(name, oid)
        if self.tex_object_combo.count() == 0:
            self.tex_object_combo.addItem("(No objects)", None)
        self.tex_object_combo.blockSignals(False)
        self._refresh_texture_sources()
        # Feed 3D preview
        self._canvas_dirty_for_3d = True
        self._update_3d_preview()
        self._canvas_dirty_for_3d = False

    def _on_tex_face_changed(self, index: int):
        """User selected a different facade in the combo."""
        face = self.tex_face_combo.currentText()
        self.statusBar().showMessage(f"Selected face: {face}", 1500)

    def _on_tex_object_changed(self, index: int):
        """User picked a different object to texture."""
        oid = self.tex_object_combo.currentData()
        if oid:
            self.statusBar().showMessage(f"Texturing object: {oid}", 1500)

    def _import_texture_for_workspace(self):
        """Import a PNG as a texture layer for use in the texture workspace."""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Texture", "", "Images (*.png *.bmp *.jpg)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            self.statusBar().showMessage("Failed to load image.", 2000)
            return
        # Scale to 128x128 for pixel-art UV mapping
        img = img.scaled(128, 128, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        img = img.convertToFormat(QImage.Format_ARGB32)
        # Add as a texture layer
        self.canvas.save_undo_state()
        self.canvas.add_layer(name="Imported Texture")
        idx = self.canvas.active_layer
        self.canvas.layers[idx] = img
        if idx < len(self.canvas.layer_types):
            self.canvas.layer_types[idx] = "texture"
        self.canvas.save_current_frame()
        self._mark_modified()
        self._refresh_layers()
        self._refresh_texture_sources()
        # Show thumbnail in preview
        self._update_tex_preview(img)
        self.statusBar().showMessage("Texture imported as 128x128 layer.", 2000)

    def _update_tex_preview(self, img: QImage):
        """Show a QImage thumbnail in the texture preview label."""
        if not hasattr(self, 'tex_preview_label'):
            return
        from PyQt5.QtGui import QPixmap
        pm = QPixmap.fromImage(img.scaled(128, 128, Qt.KeepAspectRatio, Qt.FastTransformation))
        self.tex_preview_label.setPixmap(pm)

    def _apply_texture_to_face(self):
        """Apply selected texture to the chosen face of the active object."""
        src_idx = self.tex_source_combo.currentData()
        if src_idx is None:
            self.statusBar().showMessage("No texture source selected.", 2000)
            return
        face = self.tex_face_combo.currentText()
        tile_x = self.tex_tile_x.value()
        tile_y = self.tex_tile_y.value()
        offset_x = self.tex_offset_x.value()
        offset_y = self.tex_offset_y.value()
        rot_text = self.tex_rotation.currentText()
        strength = self.tex_strength.value()

        # Get texture layer image
        if not (0 <= src_idx < len(self.canvas.layers)):
            self.statusBar().showMessage("Texture source layer not found.", 2000)
            return
        tex_img = self.canvas.layers[src_idx].copy()

        # Build tiled / rotated texture
        from PyQt5.QtGui import QPainter, QTransform
        w = self.canvas.canvas_width
        h = self.canvas.canvas_height
        result = QImage(w, h, QImage.Format_ARGB32)
        result.fill(Qt.transparent)

        # Rotation transform
        rot_deg = int(rot_text.replace("°", ""))
        t = QTransform()
        t.rotate(rot_deg)
        tex_img = tex_img.transformed(t, Qt.FastTransformation)

        tw = max(1, tex_img.width() // max(1, tile_x))
        th = max(1, tex_img.height() // max(1, tile_y))

        p = QPainter(result)
        p.setOpacity(strength / 100.0)
        for ty in range(-1, (h // th) + 2):
            for tx_i in range(-1, (w // tw) + 2):
                p.drawImage(tx_i * tw + offset_x, ty * th + offset_y,
                            tex_img, 0, 0, tw, th)
        p.end()

        # Apply to visible slice layers (simple overlay blend)
        self.canvas.save_undo_state()
        for i in range(len(self.canvas.layers)):
            ltype = self.canvas.layer_types[i] if i < len(self.canvas.layer_types) else "slice"
            if ltype != "slice":
                continue
            vis = self.canvas.layer_visible[i] if i < len(self.canvas.layer_visible) else True
            if not vis:
                continue
            layer = self.canvas.layers[i]
            p2 = QPainter(layer)
            p2.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            p2.drawImage(0, 0, result)
            p2.end()
        self.canvas.save_current_frame()
        self.canvas.update()
        self._mark_modified()
        self._canvas_dirty_for_3d = True
        self.statusBar().showMessage(
            f"Texture applied to {face} (tile {tile_x}x{tile_y}, rot {rot_deg}°)", 2000)

    def _clear_face_texture(self):
        """Stub: clear the texture from the selected face."""
        self.statusBar().showMessage("Face texture cleared.", 2000)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _new_project(self):
        """Create a new project with a chosen object type."""
        if not self._confirm_discard():
            return

        dlg = NewCanvasDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return

        w = dlg.width_spin.value()
        h = dlg.height_spin.value()
        obj_type = dlg.object_type
        obj_name = dlg.object_name
        proj_name = dlg.project_name
        initial_layers = dlg.initial_layers

        # Map object type to layer type
        layer_type_map = {"stack": "slice", "sprite": "sprite", "texture": "texture"}
        layer_type = layer_type_map.get(obj_type, "slice")

        # Create a canvas with the right number of layers
        _blank_layer_stack(self.canvas, w, h, initial_layers)
        self.canvas.layer_types = [layer_type] * initial_layers
        name_prefix = "Slice" if obj_type == "stack" else "Layer"
        self.canvas.layer_names = [f"{name_prefix} {i+1}" for i in range(initial_layers)]

        # Build a SceneManager with one scene
        self.scene_manager = SceneManager()
        self.scene_manager.project_name = proj_name
        scene = self.scene_manager.add_scene(name="Scene 1", description="Default scene")
        self._active_scene_id = scene.id

        # Create global object
        oid = f"obj_{uuid.uuid4().hex[:8]}"
        self.canvas.object_layers = [{
            "id": oid,
            "name": obj_name,
            "type": obj_type,
            "visible": True,
            "texture_layer_index": -1,
            "texture_enabled": False,
            "texture_tile_x": 1,
            "texture_tile_y": 1,
            "texture_strength": 100,
        }]
        # Add placement to scene
        scene.add_object(
            object_id=oid,
            visible=True,
            offset_x=0.0,
            offset_y=0.0,
            offset_z=0.0,
            scale=1.0,
            rotation=0.0,
            opacity=255,
        )
        self.canvas.layer_object_ids = [oid] * initial_layers

        self.canvas.current_frame = 0
        self.canvas.frames = [self.canvas._copy_layers()]
        self.canvas.pivot = (w // 2, h // 2)

        if hasattr(self.canvas, 'reset_undo'):
            self.canvas.reset_undo()
        elif hasattr(self.canvas, 'undo_stack'):
            self.canvas.undo_stack.clear() if hasattr(
                self.canvas.undo_stack, 'clear') else None

        # Per-object canvas state
        self._object_canvas_data.clear()
        self._active_object_id = oid
        self._save_canvas_to_object(oid)

        self.project_path = None
        self.is_modified  = False
        self._update_title()
        self._refresh_all()
        self.canvas.fit_canvas()
        self.size_label.setText(f"{w}x{h}")
        self.preview_panel.set_pivot(0.5, 0.5)

    def _open_project(self):
        if not self._confirm_discard():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            f"SpriteStack Studio (*{PROJECT_EXTENSION});;PNG Files (*.png);;All (*)"
        )
        if not path:
            return

        if path.endswith(PROJECT_EXTENSION):
            result = load_project(path, self.canvas, self.scene_manager)
            if result.get("success"):
                # Ensure blend_modes list exists after load
                if not hasattr(self.canvas, 'layer_blend_modes') or \
                        len(self.canvas.layer_blend_modes) != len(self.canvas.layers):
                    self.canvas.layer_blend_modes = \
                        ["Normal"] * len(self.canvas.layers)
                # Rebuild SceneManager from loaded canvas metadata
                self._rebuild_scene_model_from_canvas()
                # Restore sandbox transform state
                sandbox_transforms = result.get("sandbox_transforms", {})
                if sandbox_transforms:
                    self._stack_node_state = {}
                    for layer_idx, tdata in sandbox_transforms.items():
                        source = tdata.get("source")
                        if source is None and 0 <= layer_idx < len(self.canvas.layers):
                            source = self.canvas.layers[layer_idx].copy()
                        self._stack_node_state[layer_idx] = {
                            "tx": tdata["tx"],
                            "ty": tdata["ty"],
                            "scale": tdata["scale"],
                            "rot": tdata["rot"],
                            "opacity": tdata["opacity"],
                            "source": source,
                        }
                self.project_path = path
                self.is_modified  = False
                self._update_title()
                self._refresh_all()
                self.canvas.fit_canvas()
                self._add_to_recent(path)
                self.size_label.setText(
                    f"{self.canvas.canvas_width}x{self.canvas.canvas_height}"
                )
                # Fix 10: sync canvas pivot to 3D preview after load
                px, py = self.canvas.pivot
                self.preview_panel.set_pivot(
                    px / max(1, self.canvas.canvas_width),
                    py / max(1, self.canvas.canvas_height),
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to open project file.")

        elif path.lower().endswith('.png'):
            img = QImage(path)
            if not img.isNull():
                img = img.convertToFormat(QImage.Format_ARGB32)
                _blank_layer_stack(self.canvas, img.width(), img.height(), 1)
                self.canvas.layers[0]      = img
                self.canvas.layer_names[0] = "Imported"
                self.canvas.current_frame  = 0
                self.canvas.frames = [self.canvas._copy_layers()]
                self._refresh_all()
                self.canvas.fit_canvas()

    def _save_project(self):
        if self.project_path:
            sandbox_state = getattr(self, '_stack_node_state', None)
            save_project(self.project_path, self.canvas, self.scene_manager, sandbox_state)
            self.is_modified = False
            self._update_title()
            self.statusBar().showMessage("Project saved.", 3000)
        else:
            self._save_project_as()

    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", "",
            f"SpriteStack Studio (*{PROJECT_EXTENSION})"
        )
        if path:
            if not path.endswith(PROJECT_EXTENSION):
                path += PROJECT_EXTENSION
            sandbox_state = getattr(self, '_stack_node_state', None)
            save_project(path, self.canvas, self.scene_manager, sandbox_state)
            self.project_path = path
            self.is_modified  = False
            self._update_title()
            self._add_to_recent(path)
            self.statusBar().showMessage("Project saved.", 3000)

    def _import(self):
        dlg = ImportDialog(self)
        if dlg.exec_() != QDialog.Accepted or not dlg.imported_images:
            return

        # Fix 11: use import_mode string attribute (from updated ImportDialog)
        # rather than type_combo.currentIndex() which is fragile to item reordering.
        mode = getattr(dlg, 'import_mode', None)
        if mode is None:
            # Fallback for older ImportDialog that lacks import_mode
            mode = ["layer", "frames", "stack_layers", "folder_layers", "folder_frames"][
                dlg.type_combo.currentIndex()]

        self.canvas.save_undo_state()

        if mode == "layer":
            for img in dlg.imported_images:
                resized = img.scaled(
                    self.canvas.canvas_width, self.canvas.canvas_height,
                    Qt.IgnoreAspectRatio, Qt.FastTransformation
                )
                self.canvas.layers.append(resized)
                self.canvas.layer_names.append("Imported")
                self.canvas.layer_visible.append(True)
                self.canvas.layer_opacity.append(255)
                self.canvas.layer_locked.append(False)
                if hasattr(self.canvas, "layer_types"):
                    self.canvas.layer_types.append("sprite")
                    self.canvas.layer_object_ids.append(None)
                if hasattr(self.canvas, 'layer_blend_modes'):
                    self.canvas.layer_blend_modes.append("Normal")
            self.canvas.active_layer = len(self.canvas.layers) - 1

        elif mode in ("frames", "folder_frames"):
            for img in dlg.imported_images:
                resized = img.scaled(
                    self.canvas.canvas_width, self.canvas.canvas_height,
                    Qt.IgnoreAspectRatio, Qt.FastTransformation
                )
                self.canvas.frames.append([resized])

        elif mode in ("stack_layers", "folder_layers"):
            _blank_layer_stack(self.canvas, self.canvas.canvas_width,
                               self.canvas.canvas_height, 0)
            for i, img in enumerate(dlg.imported_images):
                resized = img.scaled(
                    self.canvas.canvas_width, self.canvas.canvas_height,
                    Qt.IgnoreAspectRatio, Qt.FastTransformation
                )
                self.canvas.layers.append(resized)
                self.canvas.layer_names.append(f"Layer {i + 1}")
                self.canvas.layer_visible.append(True)
                self.canvas.layer_opacity.append(255)
                self.canvas.layer_locked.append(False)
                if hasattr(self.canvas, "layer_types"):
                    self.canvas.layer_types.append("slice")
                    self.canvas.layer_object_ids.append(None)
                self.canvas.layer_blend_modes.append("Normal")
            self.canvas.frames = [self.canvas._copy_layers()]

        self._mark_modified()
        self._refresh_all()
        self.canvas.update()

    def _export(self):
        dlg = ExportDialog(self, self.canvas, self.preview_panel)
        dlg.exec_()

    def _quick_export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Quick Export PNG", "", "PNG Files (*.png)"
        )
        if path:
            self.canvas.flatten_image().save(path, "PNG")
            self.statusBar().showMessage(f"Exported: {os.path.basename(path)}", 3000)

    # ------------------------------------------------------------------
    # Stack operations
    # ------------------------------------------------------------------

    def _set_active_layer_type(self, layer_type: str):
        idx = self.canvas.active_layer
        if not (0 <= idx < len(self.canvas.layers)):
            return
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        if idx >= len(self.canvas.layer_types):
            return

        self.canvas.layer_types[idx] = layer_type
        if layer_type == "slice":
            oid = self.canvas.layer_object_ids[idx] if idx < len(self.canvas.layer_object_ids) else None
            if not oid:
                oid = f"obj_{uuid.uuid4().hex[:8]}"
                self.canvas.layer_object_ids[idx] = oid
                self.canvas.object_layers.append({
                    "id": oid,
                    "name": f"Object {len(self.canvas.object_layers) + 1}",
                    "type": "stack",
                    "visible": True,
                    "texture_layer_index": -1,
                    "texture_enabled": False,
                    "texture_tile_x": 1,
                    "texture_tile_y": 1,
                    "texture_strength": 100,
                })
        else:
            self.canvas.layer_object_ids[idx] = None

        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"Layer type set to {layer_type}.", 2500)

    def _auto_generate_stack(self):
        if not self.canvas.layers:
            return
        count, ok = QInputDialog.getInt(
            self, "Generate Stack", "Number of layers to generate:", 8, 2, 64
        )
        if not ok:
            return
        self.canvas.save_undo_state()
        base       = self.canvas.layers[self.canvas.active_layer].copy()
        base_name  = self.canvas.layer_names[self.canvas.active_layer]
        new_layers = [base]
        new_names  = [base_name]
        for i in range(1, count):
            layer = QImage(self.canvas.canvas_width, self.canvas.canvas_height,
                           QImage.Format_ARGB32)
            layer.fill(Qt.transparent)
            scale = max(0.1, 1.0 - i * 0.02)
            sw, sh = int(base.width() * scale), int(base.height() * scale)
            if sw > 0 and sh > 0:
                scaled = base.scaled(sw, sh, Qt.KeepAspectRatio, Qt.FastTransformation)
                ox = (self.canvas.canvas_width  - scaled.width())  // 2
                oy = (self.canvas.canvas_height - scaled.height()) // 2
                p = QPainter(layer)
                p.drawImage(ox, oy, scaled)
                p.end()
            new_layers.append(layer)
            new_names.append(f"Stack {i}")

        self.canvas.layers            = new_layers
        self.canvas.layer_names       = new_names
        self.canvas.layer_visible     = [True]  * len(new_layers)
        self.canvas.layer_opacity     = [255]   * len(new_layers)
        self.canvas.layer_locked      = [False] * len(new_layers)
        self.canvas.layer_types       = ["slice"] * len(new_layers)
        self.canvas.layer_object_ids  = [None] * len(new_layers)
        self.canvas.object_layers     = []
        self.canvas.layer_blend_modes = ["Normal"] * len(new_layers)
        self.canvas.active_layer      = 0
        self.canvas.frames            = [self.canvas._copy_layers()]
        self._mark_modified()
        self._refresh_all()

    def _create_primitive(self, shape: str):
        depth, ok = QInputDialog.getInt(
            self, "Create Primitive",
            f"Number of layers for {shape}:", max(8, len(self.canvas.layers)), 1, 256
        )
        if not ok:
            return

        self.canvas.save_undo_state()
        layers = create_primitive_stack(
            shape, self.canvas.canvas_width, self.canvas.canvas_height, depth
        )

        self.canvas.layers = layers
        self.canvas.layer_names = [f"{shape.title()} {i + 1}" for i in range(depth)]
        self.canvas.layer_visible = [True] * depth
        self.canvas.layer_opacity = [255] * depth
        self.canvas.layer_locked = [False] * depth
        self.canvas.layer_types = ["slice"] * depth
        self.canvas.layer_object_ids = [None] * depth
        self.canvas.object_layers = []
        self.canvas.layer_blend_modes = ["Normal"] * depth
        self.canvas.active_layer = 0
        self.canvas.frames = [self.canvas._copy_layers()]

        self._mark_modified()
        self._refresh_all()
        self.statusBar().showMessage(f"{shape.title()} primitive generated ({depth} layers).", 3000)

    def _import_texture_png(self):
        if not self.canvas.layers:
            QMessageBox.information(self, "Import Texture", "There are no layers to texture.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Texture PNG", "", "PNG Files (*.png);;All (*)"
        )
        if not path:
            return

        tex = QImage(path)
        if tex.isNull():
            QMessageBox.warning(self, "Import Texture", "Could not read the selected PNG.")
            return

        opt = QDialog(self)
        opt.setWindowTitle("Texture Mapping Options")
        form = QFormLayout(opt)
        mode_combo = QComboBox()
        mode_combo.addItems(["Layer Bands (vertical)", "Full Texture (repeat each layer)"])
        tile_x_spin = QSpinBox(); tile_x_spin.setRange(1, 32); tile_x_spin.setValue(1)
        tile_y_spin = QSpinBox(); tile_y_spin.setRange(1, 32); tile_y_spin.setValue(1)
        off_x_spin = QSpinBox(); off_x_spin.setRange(-4096, 4096); off_x_spin.setValue(0)
        off_y_spin = QSpinBox(); off_y_spin.setRange(-4096, 4096); off_y_spin.setValue(0)
        strength_spin = QSpinBox(); strength_spin.setRange(0, 100); strength_spin.setValue(100)
        strength_spin.setSuffix("%")
        form.addRow("Mapping mode:", mode_combo)
        form.addRow("Tile X:", tile_x_spin)
        form.addRow("Tile Y:", tile_y_spin)
        form.addRow("Offset X:", off_x_spin)
        form.addRow("Offset Y:", off_y_spin)
        form.addRow("Texture strength:", strength_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(opt.accept)
        btns.rejected.connect(opt.reject)
        form.addRow(btns)
        if opt.exec_() != QDialog.Accepted:
            return

        map_mode = "bands" if mode_combo.currentIndex() == 0 else "full"

        try:
            self.canvas.save_undo_state()
            self.canvas.layers = apply_texture_to_layers(
                self.canvas.layers,
                tex,
                map_mode=map_mode,
                tile_x=tile_x_spin.value(),
                tile_y=tile_y_spin.value(),
                offset_x=off_x_spin.value(),
                offset_y=off_y_spin.value(),
                strength=strength_spin.value(),
            )
            self.canvas.frames = [self.canvas._copy_layers()]
            if hasattr(self.canvas, "sync_scene_metadata"):
                self.canvas.sync_scene_metadata()
            self._mark_modified()
            self._refresh_all()
            self.statusBar().showMessage("Texture mapped to stack layers.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Import Texture Error", str(e))

    def _import_layer_strip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Layer Strip", "", "PNG Files (*.png);;All (*)"
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            return

        # Fix 12: ask for strip orientation - export.py now defaults to VERTICAL
        from PyQt5.QtWidgets import QMessageBox as _MB
        orientation_reply = _MB.question(
            self, "Strip Orientation",
            "Is this strip laid out vertically (layers stacked top-to-bottom)?\n\n"
            "Yes = Vertical (new default from Export)\n"
            "No  = Horizontal (classic left-to-right)",
            _MB.Yes | _MB.No, _MB.Yes
        )
        vertical = (orientation_reply == _MB.Yes)

        if vertical:
            frame_h, ok = QInputDialog.getInt(
                self, "Layer Strip", "Height of each layer frame:",
                img.width(), 1, img.height()
            )
            if not ok:
                return
            frame_w    = img.width()
            num_layers = img.height() // frame_h
        else:
            frame_w, ok = QInputDialog.getInt(
                self, "Layer Strip", "Width of each layer frame:",
                img.height(), 1, img.width()
            )
            if not ok:
                return
            frame_h    = img.height()
            num_layers = img.width() // frame_w

        self.canvas.save_undo_state()
        _blank_layer_stack(self.canvas, frame_w, frame_h, 0)
        for i in range(num_layers):
            if vertical:
                layer = img.copy(0, i * frame_h, frame_w, frame_h)
            else:
                layer = img.copy(i * frame_w, 0, frame_w, frame_h)
            layer = layer.convertToFormat(QImage.Format_ARGB32)
            self.canvas.layers.append(layer)
            self.canvas.layer_names.append(f"Stack {i}")
            self.canvas.layer_visible.append(True)
            self.canvas.layer_opacity.append(255)
            self.canvas.layer_locked.append(False)
            self.canvas.layer_types.append("slice")
            self.canvas.layer_object_ids.append(None)
            self.canvas.layer_blend_modes.append("Normal")
        self.canvas.active_layer = 0
        self.canvas.frames       = [self.canvas._copy_layers()]
        self.size_label.setText(f"{frame_w}x{frame_h}")
        self._mark_modified()
        self._refresh_all()
        self.canvas.fit_canvas()

    def _export_rotation_sheet(self):
        if not self.preview_panel:
            return
        angles, ok = QInputDialog.getInt(
            self, "Rotation Sheet", "Number of angles:", 8, 4, 72
        )
        if not ok:
            return
        size, ok = QInputDialog.getInt(
            self, "Rotation Sheet", "Render size (px):", 128, 32, 512
        )
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Rotation Sheet", "", "PNG Files (*.png)"
        )
        if path:
            sheet = self.preview_panel.preview.export_rotation_sheet(angles, size)
            sheet.save(path, "PNG")
            self.statusBar().showMessage("Rotation sheet exported.", 3000)

    def _export_layer_strip(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Layer Strip", "", "PNG Files (*.png)"
        )
        if not path:
            return
        from app.project import export_layers_as_stack_image
        scale, ok = QInputDialog.getInt(self, "Scale", "Export scale:", 1, 1, 16)
        if ok:
            export_layers_as_stack_image(self.canvas, path, scale)
            self.statusBar().showMessage("Layer strip exported.", 3000)

    def _export_obj_mtl(self):
        self.canvas.save_current_frame()
        visible_layers = [
            layer for i, layer in enumerate(self.canvas.layers)
            if i < len(self.canvas.layer_visible) and self.canvas.layer_visible[i]
        ]
        if not visible_layers:
            QMessageBox.information(self, "Export OBJ/MTL", "No visible layers to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export OBJ/MTL", "", "Wavefront OBJ Files (*.obj)"
        )
        if not path:
            return

        if not path.lower().endswith(".obj"):
            path += ".obj"

        try:
            obj, mtl, tex = export_stack_to_obj_mtl(visible_layers, path)
            self.statusBar().showMessage("OBJ/MTL export completed.", 3000)
            QMessageBox.information(
                self, "Export Complete",
                "Saved files:\n"
                f"{obj}\n{mtl}\n{tex}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export OBJ/MTL Error", str(e))

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_all(self):
        if hasattr(self.canvas, "sync_scene_metadata"):
            self.canvas.sync_scene_metadata()
        self._refresh_layers()
        self._refresh_timeline()
        self._refresh_scene_combo()  # Refresh scene list
        self._canvas_dirty_for_3d = True
        stack_ws_active = getattr(self, 'current_workspace', 'create') in ('sandbox', 'texture')
        if stack_ws_active or getattr(self, '_inline_3d_active', False):
            self._update_3d_preview()
            self._canvas_dirty_for_3d = False
        self._update_title()
        self.size_label.setText(
            f"{self.canvas.canvas_width}x{self.canvas.canvas_height}"
        )
        self.frame_label.setText(
            f"Frame {self.canvas.current_frame + 1}/{self.canvas.get_frame_count()}"
        )
        self._sync_sandbox_workspace_from_canvas()
        self._refresh_ai_panel_context()

    def _refresh_layers(self):
        """Refresh the layer/scene tree panel using SceneModel."""
        blend_list = getattr(self.canvas, 'layer_blend_modes', None)
        layer_types = getattr(self.canvas, 'layer_types', None)

        # Pass only objects placed in the active scene so the panel follows the scene dropdown.
        objects = self._objects_for_active_scene() if hasattr(self.canvas, 'object_layers') else None
        # Get active scene for placements
        scene = self.scene_manager.get_active_scene()
        # Get active placement from scene
        active_oid = self._active_object_id if self._active_object_id in self._active_scene_object_ids() else None
        if scene and scene.placements:
            for p in scene.placements:
                if p.object_id == self._active_object_id:
                    active_oid = p.object_id
                    break

        self.layer_panel.refresh_layers(
            self.canvas.layer_names,
            self.canvas.layer_visible,
            self.canvas.layer_opacity,
            self.canvas.active_layer,
            self.canvas.layers,
            locked_list = self.canvas.layer_locked,
            blend_list  = blend_list,
            layer_types = layer_types,
            objects     = objects,
            active_object_id = active_oid,
        )

    def _refresh_timeline(self):
        self.canvas.save_current_frame()
        thumbnails = [self.canvas.get_flat_frame(i)
                      for i in range(self.canvas.get_frame_count())]
        self.timeline.refresh_frames(
            self.canvas.get_frame_count(),
            self.canvas.current_frame,
            thumbnails,
        )

    def _update_title(self):
        if self.project_path:
            name = os.path.basename(self.project_path)
        elif self.scene_manager:
            name = self.scene_manager.project_name
        else:
            name = "Untitled"
        mod  = " *" if self.is_modified else ""
        self.setWindowTitle(f"SpriteStack Studio  -  {name}{mod}")

    def _mark_modified(self):
        """Central helper so nothing has to repeat the two-liner."""
        self.is_modified = True
        self._canvas_dirty_for_3d = True
        self._update_title()

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------

    def _add_to_recent(self, path: str):
        recent = self._settings.value("recent_files", [], type=list)
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        recent = recent[:_MAX_RECENT]
        self._settings.setValue("recent_files", recent)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recent = self._settings.value("recent_files", [], type=list)
        if not recent:
            self.recent_menu.addAction("(empty)").setEnabled(False)
            return
        for path in recent:
            label = os.path.basename(path)
            action = self.recent_menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._open_recent(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Recent Files").triggered.connect(
            self._clear_recent
        )

    def _open_recent(self, path: str):
        if not os.path.exists(path):
            QMessageBox.warning(self, "File Not Found",
                                f"The file no longer exists:\n{path}")
            recent = self._settings.value("recent_files", [], type=list)
            if path in recent:
                recent.remove(path)
                self._settings.setValue("recent_files", recent)
                self._rebuild_recent_menu()
            return
        if not self._confirm_discard():
            return
        # FIX: Changed from self.scene_model to self.scene_manager
        result = load_project(path, self.canvas, self.scene_manager)
        if result.get("success"):
            if not hasattr(self.canvas, 'layer_blend_modes') or \
                    len(self.canvas.layer_blend_modes) != len(self.canvas.layers):
                self.canvas.layer_blend_modes = ["Normal"] * len(self.canvas.layers)
            self._rebuild_scene_model_from_canvas()
            # Restore sandbox transform state
            sandbox_transforms = result.get("sandbox_transforms", {})
            if sandbox_transforms:
                self._stack_node_state = {}
                for layer_idx, tdata in sandbox_transforms.items():
                    source = tdata.get("source")
                    if source is None and 0 <= layer_idx < len(self.canvas.layers):
                        source = self.canvas.layers[layer_idx].copy()
                    self._stack_node_state[layer_idx] = {
                        "tx": tdata["tx"],
                        "ty": tdata["ty"],
                        "scale": tdata["scale"],
                        "rot": tdata["rot"],
                        "opacity": tdata["opacity"],
                        "source": source,
                    }
            self.project_path = path
            self.is_modified  = False
            self._update_title()
            self._refresh_all()
            self.canvas.fit_canvas()
            self._add_to_recent(path)
            # Fix 10: sync canvas pivot to 3D preview after load
            px, py = self.canvas.pivot
            self.preview_panel.set_pivot(
                px / max(1, self.canvas.canvas_width),
                py / max(1, self.canvas.canvas_height),
            )
        else:
            QMessageBox.critical(self, "Error", f"Could not open:\n{path}")

    def _clear_recent(self):
        self._settings.setValue("recent_files", [])
        self._rebuild_recent_menu()

    # ------------------------------------------------------------------
    # Unsaved-changes guard
    # ------------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        """
        If the project has unsaved changes, ask the user what to do.
        Returns True if it is safe to proceed (saved or discarded),
        False if the user cancelled.
        """
        if not self.is_modified:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "The current project has unsaved changes. Save now?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if reply == QMessageBox.Save:
            self._save_project()
            return True
        if reply == QMessageBox.Discard:
            return True
        return False   # Cancel

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_about(self):
        QMessageBox.about(
            self, "About SpriteStack Studio",
            "<h2>SpriteStack Studio</h2>"
            "<p>A sprite-stacking and pixel-art editor.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Full pixel art editor with drawing tools</li>"
            "<li>Layer system with opacity, visibility, lock, blend modes</li>"
            "<li>Animation timeline with frame management</li>"
            "<li>Real-time 3D sprite-stack preview</li>"
            "<li>Multiple render modes (stack, voxel, billboard)</li>"
            "<li>Export: PNG, sprite sheets, GIF, rotation sheets</li>"
            "<li>Import: images, sprite sheets, folders</li>"
            "<li>Copy / Cut / Paste with floating selection</li>"
            "<li>Magic wand, move, and advanced selection tools</li>"
            "<li>Color palette management with presets</li>"
            "<li>Symmetry drawing (mirror X / Y)</li>"
            "<li>Undo / Redo support</li>"
            "</ul>"
        )

    def _show_shortcuts(self):
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            # FIX: updated with new tool shortcuts from tools.py fix
            "<b>Tools:</b><br>"
            "B - Pencil<br>"
            "E - Eraser<br>"
            "G - Fill Bucket<br>"
            "I - Eyedropper<br>"
            "L - Line<br>"
            "R - Rectangle (outline)<br>"
            "F - Filled Rectangle<br>"       # FIX: was missing
            "C - Circle (outline)<br>"
            "O - Filled Circle<br>"          # FIX: was missing
            "S - Select (rectangle)<br>"
            "M - Move Selection<br>"
            "W - Magic Wand<br><br>"
            "<b>Edit:</b><br>"
            "Ctrl+Z - Undo<br>"
            "Ctrl+Y - Redo<br>"
            "Ctrl+X - Cut<br>"
            "Ctrl+C - Copy<br>"
            "Ctrl+V - Paste<br>"
            "Ctrl+A - Select All<br>"
            "Ctrl+D - Deselect<br>"
            "Delete - Clear Selection / Layer<br><br>"
            "<b>File:</b><br>"
            "Ctrl+N - New<br>"
            "Ctrl+O - Open<br>"
            "Ctrl+S - Save<br>"
            "Ctrl+Shift+S - Save As<br>"
            "Ctrl+E - Export<br>"
            "Ctrl+Shift+E - Quick Export PNG<br>"
            "Ctrl+I - Import<br><br>"
            "<b>View:</b><br>"
            "Ctrl++ - Zoom In<br>"
            "Ctrl+- - Zoom Out<br>"
            "Ctrl+0 - Fit Canvas<br>"
            "Home - Centre Canvas<br>"
            "Ctrl+G - Toggle Grid<br>"
            "Middle Mouse - Pan<br>"
            "Scroll - Zoom<br><br>"
            "<b>Animation:</b><br>"
            "F5 - Add Frame<br>"
            "F6 - Duplicate Frame<br>"
            "F7 - Delete Frame<br>"
            "Space - Play / Pause<br><br>"
            "<b>Layers:</b><br>"
            "Ctrl+Shift+N - New Layer<br>"
            "Ctrl+Shift+D - Duplicate Layer<br>"
            "Ctrl+Shift+C - Centre Object on Canvas<br>"   # Fix 13
            "Ctrl+Shift+M - Merge Down<br><br>"
            "<b>3D Preview:</b><br>"
            "Left Drag - Rotate<br>"
            "Middle Drag - Pan<br>"
            "Scroll - Zoom<br>"
            "Escape - Deselect / Cancel<br>"
        )

    # ------------------------------------------------------------------
    # Keyboard events
    # FIX: was defined twice - Escape was completely dead.
    # Now unified: Escape deselects; unmodified keys route to tool shortcuts.
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Escape always deselects regardless of modifiers
        if key == Qt.Key_Escape:
            self.canvas.deselect()
            return

        if key in (Qt.Key_Delete, Qt.Key_Backspace) and getattr(self, "current_workspace", "create") == "sandbox":
            self._delete_selected_placement()
            return

        # Fix 2: Space plays/pauses regardless of which widget has focus.
        # A QAction shortcut with "Space" is shadowed by canvas.StrongFocus -
        # Space goes to canvas.keyPressEvent → super() and is lost.
        # Intercepting it here ensures it always reaches _toggle_play.
        if key == Qt.Key_Space and not mods:
            self._toggle_play()
            return

        # Unmodified single-key tool shortcuts
        if not mods:
            if self.tool_bar.keypress_select_tool(key):
                return

        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Preferences dialog
    # ------------------------------------------------------------------

    def _show_preferences(self):
        from PyQt5.QtWidgets import QDialog, QTabWidget, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        dlg.setMinimumSize(520, 420)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(12, 12, 12, 12)
        dlg_layout.setSpacing(8)

        tabs = QTabWidget()

        # ── General tab ──────────────────────────────────────────
        gen = QWidget()
        gen_lay = QFormLayout(gen)
        gen_lay.setContentsMargins(12, 12, 12, 12)
        gen_lay.setSpacing(8)

        self._pref_default_w = QSpinBox()
        self._pref_default_w.setRange(8, 4096)
        self._pref_default_w.setValue(int(self._settings.value("pref/default_canvas_w", 64)))
        gen_lay.addRow("Default Canvas Width", self._pref_default_w)

        self._pref_default_h = QSpinBox()
        self._pref_default_h.setRange(8, 4096)
        self._pref_default_h.setValue(int(self._settings.value("pref/default_canvas_h", 64)))
        gen_lay.addRow("Default Canvas Height", self._pref_default_h)

        self._pref_undo_limit = QSpinBox()
        self._pref_undo_limit.setRange(5, 200)
        self._pref_undo_limit.setValue(int(self._settings.value("pref/undo_limit", 50)))
        gen_lay.addRow("Undo History Limit", self._pref_undo_limit)

        self._pref_autosave = QCheckBox("Enable auto-save")
        self._pref_autosave.setChecked(self._settings.value("pref/autosave", "false") == "true")
        gen_lay.addRow(self._pref_autosave)

        self._pref_autosave_interval = QSpinBox()
        self._pref_autosave_interval.setRange(1, 60)
        self._pref_autosave_interval.setSuffix(" min")
        self._pref_autosave_interval.setValue(int(self._settings.value("pref/autosave_interval", 5)))
        gen_lay.addRow("Auto-save Interval", self._pref_autosave_interval)

        tabs.addTab(gen, "General")

        # ── Canvas tab ───────────────────────────────────────────
        canvas_tab = QWidget()
        canvas_lay = QFormLayout(canvas_tab)
        canvas_lay.setContentsMargins(12, 12, 12, 12)
        canvas_lay.setSpacing(8)

        self._pref_show_grid = QCheckBox("Show grid by default")
        self._pref_show_grid.setChecked(self._settings.value("pref/show_grid", "true") == "true")
        canvas_lay.addRow(self._pref_show_grid)

        self._pref_grid_size = QSpinBox()
        self._pref_grid_size.setRange(1, 128)
        self._pref_grid_size.setValue(int(self._settings.value("pref/grid_size", 1)))
        canvas_lay.addRow("Grid Cell Size", self._pref_grid_size)

        self._pref_checker_bg = QCheckBox("Checker background")
        self._pref_checker_bg.setChecked(self._settings.value("pref/checker_bg", "true") == "true")
        canvas_lay.addRow(self._pref_checker_bg)

        self._pref_smooth_zoom = QCheckBox("Smooth pixel zoom (bilinear)")
        self._pref_smooth_zoom.setChecked(self._settings.value("pref/smooth_zoom", "false") == "true")
        canvas_lay.addRow(self._pref_smooth_zoom)

        tabs.addTab(canvas_tab, "Canvas")

        # ── 3D Preview tab ───────────────────────────────────────
        preview_tab = QWidget()
        preview_lay = QFormLayout(preview_tab)
        preview_lay.setContentsMargins(12, 12, 12, 12)
        preview_lay.setSpacing(8)

        self._pref_default_spacing = QDoubleSpinBox()
        self._pref_default_spacing.setRange(0.1, 20.0)
        self._pref_default_spacing.setSingleStep(0.1)
        self._pref_default_spacing.setValue(float(self._settings.value("pref/default_spacing", 1.0)))
        preview_lay.addRow("Default Layer Spacing", self._pref_default_spacing)

        self._pref_default_tilt = QSpinBox()
        self._pref_default_tilt.setRange(-90, 90)
        self._pref_default_tilt.setValue(int(self._settings.value("pref/default_tilt", 30)))
        preview_lay.addRow("Default Tilt Angle", self._pref_default_tilt)

        self._pref_outline = QCheckBox("Show outlines by default")
        self._pref_outline.setChecked(self._settings.value("pref/outline", "true") == "true")
        preview_lay.addRow(self._pref_outline)

        self._pref_shadow = QCheckBox("Show shadow by default")
        self._pref_shadow.setChecked(self._settings.value("pref/shadow", "true") == "true")
        preview_lay.addRow(self._pref_shadow)

        tabs.addTab(preview_tab, "3D Preview")

        # ── Export tab ───────────────────────────────────────────
        export_tab = QWidget()
        export_lay = QFormLayout(export_tab)
        export_lay.setContentsMargins(12, 12, 12, 12)
        export_lay.setSpacing(8)

        self._pref_export_scale = QSpinBox()
        self._pref_export_scale.setRange(1, 16)
        self._pref_export_scale.setValue(int(self._settings.value("pref/export_scale", 1)))
        export_lay.addRow("Default Export Scale", self._pref_export_scale)

        self._pref_export_bg = QComboBox()
        self._pref_export_bg.addItems(["Transparent", "Black", "White", "Custom..."])
        saved_bg = self._settings.value("pref/export_bg", "Transparent")
        idx = self._pref_export_bg.findText(saved_bg)
        if idx >= 0:
            self._pref_export_bg.setCurrentIndex(idx)
        export_lay.addRow("Default Export Background", self._pref_export_bg)

        tabs.addTab(export_tab, "Export")

        dlg_layout.addWidget(tabs)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btn_box)

        if dlg.exec_() == QDialog.Accepted:
            self._apply_preferences()

    def _apply_preferences(self):
        """Save preference values to QSettings."""
        self._settings.setValue("pref/default_canvas_w", self._pref_default_w.value())
        self._settings.setValue("pref/default_canvas_h", self._pref_default_h.value())
        self._settings.setValue("pref/undo_limit", self._pref_undo_limit.value())
        self._settings.setValue("pref/autosave", "true" if self._pref_autosave.isChecked() else "false")
        self._settings.setValue("pref/autosave_interval", self._pref_autosave_interval.value())
        self._settings.setValue("pref/show_grid", "true" if self._pref_show_grid.isChecked() else "false")
        self._settings.setValue("pref/grid_size", self._pref_grid_size.value())
        self._settings.setValue("pref/checker_bg", "true" if self._pref_checker_bg.isChecked() else "false")
        self._settings.setValue("pref/smooth_zoom", "true" if self._pref_smooth_zoom.isChecked() else "false")
        self._settings.setValue("pref/default_spacing", self._pref_default_spacing.value())
        self._settings.setValue("pref/default_tilt", self._pref_default_tilt.value())
        self._settings.setValue("pref/outline", "true" if self._pref_outline.isChecked() else "false")
        self._settings.setValue("pref/shadow", "true" if self._pref_shadow.isChecked() else "false")
        self._settings.setValue("pref/export_scale", self._pref_export_scale.value())
        self._settings.setValue("pref/export_bg", self._pref_export_bg.currentText())

        # Apply live settings where possible
        if hasattr(self.canvas, 'undo_limit'):
            self.canvas.undo_limit = self._pref_undo_limit.value()
        if hasattr(self.canvas, 'show_grid'):
            self.canvas.show_grid = self._pref_show_grid.isChecked()
            self.canvas.update()

        self.statusBar().showMessage("Preferences saved.", 2000)

    # ------------------------------------------------------------------
    # Close event
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._confirm_discard():
            # Fix 6: persist window geometry AND splitter layout
            self._settings.setValue("geometry",      self.saveGeometry())
            self._settings.setValue("splitter_state", self.main_splitter.saveState())
            event.accept()
        else:
            event.ignore()
