"""
Animation timeline panel — enhanced edition.

New features over original:
  • Frame reordering via drag-and-drop (left/right)
  • Per-frame duration override (right-click context menu)
  • Onion skin controls exposed in UI (frames count + opacity sliders)
  • Loop / ping-pong playback modes
  • Frame range markers (loop-in / loop-out)
  • Keyboard shortcuts: Space=play, Left/Right=prev/next, Home/End=first/last,
    Delete=delete frame, Ctrl+D=duplicate, Ctrl+N=new frame
  • "Preview FPS" label updates live during playback
  • Thumbnail size toggle (small / medium / large)
  • Frame strip context menu: insert before, insert after, duplicate, delete,
    set duration, clear frame
  • Visual playhead (animated highlight)
  • Loop-in / loop-out markers shown on thumbnails
  • Status bar row: total duration display
  • Scrubbing: click-and-drag across frame strip to scrub
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QSpinBox, QCheckBox, QSlider, QFrame,
    QSizePolicy, QMenu, QAction, QInputDialog, QToolButton,
    QButtonGroup, QActionGroup
)
from PyQt5.QtGui import (
    QPainter, QColor, QPixmap, QPen, QImage, QFont, QCursor,
    QLinearGradient, QBrush, QPainterPath
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QTimer, QRect, QSize, QPoint, QMimeData,
    QPropertyAnimation, QEasingCurve
)

from app.theme import (
    T as _T, FONT_FAMILY, FONT_SIZE,
    ACCENT, ACCENT_DIM, ACCENT_HOVER,
    TEXT, TEXT_MUTED, TEXT_BRIGHT, TEXT_DIM,
    BG_PANEL, BG_INPUT, BG_RAISED, BG_HEADER, BG_DARK,
    BORDER, BORDER_LIGHT, BORDER_DARK,
    RED, GREEN, YELLOW,
)


# ── Design tokens (Aseprite theme) ─────────────────────────────────────────
C_BG          = QColor(BG_PANEL)
C_STRIP_BG    = QColor(BG_INPUT)
C_CELL_BG     = QColor(BG_RAISED)
C_CELL_SEL    = QColor(ACCENT_DIM)
C_ACCENT      = QColor(ACCENT)
C_ACCENT2     = QColor(RED)
C_BORDER      = QColor(BORDER)
C_BORDER_SEL  = QColor(ACCENT)
C_TEXT        = QColor(TEXT)
C_TEXT_DIM    = QColor(TEXT_MUTED)
C_PLAYHEAD    = QColor(YELLOW)
C_LOOP_IN     = QColor(GREEN)
C_LOOP_OUT    = QColor(RED)
C_DUR_BADGE   = QColor(BG_DARK)


THUMB_SIZES = {
    "S": (52,  52,  66,  80),   # thumb_w, thumb_h, cell_w, cell_h
    "M": (72,  72,  88, 100),
    "L": (96,  96, 112, 124),
}
DEFAULT_SIZE = "M"


class FrameThumbnail(QWidget):
    """
    A single frame cell in the timeline strip.

    Signals
    -------
    clicked(int)
    right_clicked(int, QPoint)
    move_requested(int, int)   # from_idx, to_idx  (drag reorder)
    scrub_to(int)
    """

    clicked       = pyqtSignal(int)
    ctrl_clicked  = pyqtSignal(int)
    right_clicked = pyqtSignal(int, QPoint)
    move_requested = pyqtSignal(int, int)
    scrub_to      = pyqtSignal(int)

    def __init__(self, frame_idx, thumb_w=72, thumb_h=72,
                 cell_w=88, cell_h=100, parent=None):
        super().__init__(parent)
        self.frame_idx   = frame_idx
        self.thumb_w     = thumb_w
        self.thumb_h     = thumb_h
        self.is_selected = False
        self.is_secondary = False
        self.is_loop_in  = False
        self.is_loop_out = False
        self.duration    = 1        # frames multiplier (1 = normal)
        self.thumbnail   = None
        self._drag_start = None
        self._drag_active = False

        self.setFixedSize(cell_w, cell_h)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)

    # ── public ──────────────────────────────────────────────────────────────

    def set_thumbnail(self, image):
        if image and not image.isNull():
            self.thumbnail = QPixmap.fromImage(
                image.scaled(self.thumb_w, self.thumb_h,
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.thumbnail = None
        self.update()

    def resize_cells(self, thumb_w, thumb_h, cell_w, cell_h):
        self.thumb_w = thumb_w
        self.thumb_h = thumb_h
        self.setFixedSize(cell_w, cell_h)
        if self.thumbnail:
            self.set_thumbnail(None)   # force re-scale on next set_thumbnail call

    # ── paint ───────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        W, H = self.width(), self.height()

        # Background
        bg = C_CELL_SEL if self.is_selected else C_CELL_BG
        border_color = QColor(YELLOW) if self.is_secondary else (C_BORDER_SEL if self.is_selected else C_BORDER)
        border_w = 2 if (self.is_selected or self.is_secondary) else 1

        p.fillRect(1, 1, W - 2, H - 2, bg)
        p.setPen(QPen(border_color, border_w))
        p.drawRect(1, 1, W - 3, H - 3)

        # Thumbnail / placeholder
        if self.thumbnail:
            tx = (W - self.thumbnail.width()) // 2
            ty = 5
            p.setPen(QPen(C_BORDER, 1))
            p.drawRect(tx - 1, ty - 1,
                       self.thumbnail.width() + 1,
                       self.thumbnail.height() + 1)
            p.drawPixmap(tx, ty, self.thumbnail)
        else:
            p.setPen(C_TEXT)
            p.drawText(QRect(0, 0, W, H - 18), Qt.AlignCenter, ".  .  .")

        # Loop-in / loop-out badges (top corners)
        badge_size = 8
        if self.is_loop_in:
            p.setPen(Qt.NoPen)
            p.setBrush(C_LOOP_IN)
            p.drawRect(4, 4, badge_size, badge_size)
        if self.is_loop_out:
            p.setPen(Qt.NoPen)
            p.setBrush(C_LOOP_OUT)
            p.drawRect(W - badge_size - 4, 4, badge_size, badge_size)

        # Duration badge (bottom-left, only if > 1)
        if self.duration > 1:
            badge_text = f"x{self.duration}"
            p.setFont(QFont(FONT_FAMILY, 7, QFont.Bold))
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(badge_text) + 6
            bh = 13
            p.setPen(Qt.NoPen)
            p.setBrush(C_DUR_BADGE)
            p.drawRect(3, H - 16 - bh // 2, bw, bh)
            p.setPen(QColor(YELLOW))
            p.drawText(3, H - 16 - bh // 2, bw, bh, Qt.AlignCenter, badge_text)

        # Frame number label
        lbl_font = QFont(FONT_FAMILY, FONT_SIZE)
        lbl_font.setBold(self.is_selected)
        p.setFont(lbl_font)
        p.setPen(C_TEXT)
        p.drawText(QRect(0, H - 17, W, 16), Qt.AlignCenter, f"{self.frame_idx + 1}")

        # Playhead underline
        if self.is_selected:
            p.setPen(Qt.NoPen)
            p.setBrush(C_ACCENT)
            p.drawRect(6, H - 4, W - 12, 3)

        p.end()

    # ── interaction ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
            self._drag_active = False
            if event.modifiers() & Qt.ControlModifier:
                self.ctrl_clicked.emit(self.frame_idx)
            else:
                self.clicked.emit(self.frame_idx)
        elif event.button() == Qt.RightButton:
            self.right_clicked.emit(self.frame_idx, event.globalPos())

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        delta = event.pos() - self._drag_start
        if not self._drag_active and abs(delta.x()) > 10:
            self._drag_active = True
        if self._drag_active:
            # Estimate target index from horizontal movement
            cell_w = self.width() + 8          # spacing approximation
            offset  = delta.x() // cell_w
            target  = max(0, self.frame_idx + offset)
            if target != self.frame_idx:
                self.move_requested.emit(self.frame_idx, target)
                self._drag_start = event.pos()  # reset so next move is relative

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self._drag_active = False


# ──────────────────────────────────────────────────────────────────────────
class TimelinePanel(QWidget):
    """
    Animation timeline with frame thumbnails and full playback controls.

    Signals
    -------
    frame_selected(int)
    frame_added(bool)            True = copy current
    frame_inserted_before(int)
    frame_inserted_after(int)
    frame_deleted(int)
    frame_cleared(int)
    frame_moved(int, int)        from_idx, to_idx
    play_toggled(bool)
    fps_changed(int)
    onion_skin_changed(bool, int, int)   enabled, frames, opacity %
    loop_range_changed(int, int)         loop_in, loop_out  (-1 = disabled)
    playback_mode_changed(str)           "loop" | "ping_pong" | "once"
    frame_duration_changed(int, int)     frame_idx, duration_multiplier
    predict_intermediate_requested()
    """

    frame_selected       = pyqtSignal(int)
    secondary_frame_selected = pyqtSignal(int)
    frame_added          = pyqtSignal(bool)
    frame_inserted_before = pyqtSignal(int)
    frame_inserted_after  = pyqtSignal(int)
    frame_deleted        = pyqtSignal(int)
    frame_cleared        = pyqtSignal(int)
    frame_moved          = pyqtSignal(int, int)
    play_toggled         = pyqtSignal(bool)
    fps_changed          = pyqtSignal(int)
    onion_skin_changed   = pyqtSignal(bool, int, int)
    loop_range_changed   = pyqtSignal(int, int)
    playback_mode_changed = pyqtSignal(str)
    frame_duration_changed = pyqtSignal(int, int)
    predict_intermediate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMaximumHeight(230)

        self.current_frame   = 0
        self._primary_frame  = 0
        self._secondary_frame = -1
        self.is_playing      = False
        self.fps             = 12
        self._ping_direction = 1     # +1 or -1 for ping-pong
        self._loop_in        = -1   # -1 = disabled
        self._loop_out       = -1
        self._playback_mode  = "loop"   # "loop" | "ping_pong" | "once"
        self._thumb_size     = DEFAULT_SIZE
        self._frame_durations = {}      # frame_idx → duration multiplier
        self._dur_tick       = 0        # tick counter for per-frame duration

        self._apply_style()
        self._build_ui()

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._on_play_tick)

        self.setFocusPolicy(Qt.StrongFocus)

    # ── stylesheet ──────────────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(f"""
            TimelinePanel, QWidget {{
                background: {BG_PANEL};
                color: {TEXT};
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
            }}

            /* ── Buttons ── */
            QPushButton {{
                background: {BG_RAISED};
                border: 1px solid {BORDER};
                color: {TEXT};
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
                padding: 2px 7px;
                min-height: 22px;
            }}
            QPushButton:hover  {{
                background: {BG_HEADER};
                border-color: {BORDER_LIGHT};
                color: {TEXT_BRIGHT};
            }}
            QPushButton:pressed {{
                background: {BG_INPUT};
            }}
            QPushButton:checked {{
                background: {ACCENT_DIM};
                border-color: {ACCENT};
                color: {ACCENT};
                font-weight: bold;
            }}
            QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER_DARK}; }}

            /* ── Labels ── */
            QLabel {{ background: transparent; color: {TEXT_BRIGHT}; }}

            /* ── SpinBox ── */
            QSpinBox {{
                background: {BG_INPUT};
                border: 1px solid {BORDER};
                color: {TEXT};
                padding: 1px 3px;
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
            }}
            QSpinBox:hover {{ border-color: {BORDER_LIGHT}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 14px;
                background: {BG_RAISED};
                border: none;
                border-left: 1px solid {BORDER};
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {BG_HEADER};
            }}

            /* ── Sliders ── */
            QSlider::groove:horizontal {{
                height: 5px;
                background: {BG_INPUT};
                border: 1px solid {BORDER};
            }}
            QSlider::handle:horizontal {{
                width: 11px; height: 11px;
                margin: -3px 0;
                background: {TEXT};
                border: 1px solid {BORDER_LIGHT};
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT};
            }}

            /* ── CheckBox ── */
            QCheckBox {{
                spacing: 5px;
                color: {TEXT};
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
            }}
            QCheckBox:hover {{ color: {TEXT}; }}
            QCheckBox::indicator {{
                width: 13px; height: 13px;
                border: 1px solid {BORDER};
                background: {BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT_DIM};
                border-color: {ACCENT};
            }}
            QCheckBox::indicator:hover {{ border-color: {BORDER_LIGHT}; }}

            /* ── ToolButton ── */
            QToolButton {{
                background: {BG_RAISED};
                border: 1px solid {BORDER};
                color: {TEXT};
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
                padding: 2px 5px;
                min-width: 26px;
                min-height: 22px;
            }}
            QToolButton:hover {{
                background: {BG_HEADER};
                border-color: {BORDER_LIGHT};
                color: {TEXT};
            }}
            QToolButton:pressed {{ background: {BG_INPUT}; }}
            QToolButton:checked {{
                background: {ACCENT_DIM};
                border-color: {ACCENT};
                color: {ACCENT};
            }}

            /* ── Scrollbar ── */
            QScrollBar:horizontal {{
                height: 7px;
                background: {BG_PANEL};
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {BORDER};
                min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {ACCENT}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """)

    # ── UI build ────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)

        root.addLayout(self._build_top_bar())
        root.addLayout(self._build_onion_bar())
        root.addWidget(self._build_strip())
        root.addLayout(self._build_status_bar())

    def _build_top_bar(self):
        row = QHBoxLayout()
        row.setSpacing(4)

        # ── Transport ──
        def tbtn(text, tip, w=28):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(w, 26)
            return b

        self.first_btn  = tbtn("|<", "First Frame (Home)")
        self.prev_btn   = tbtn("<", "Prev Frame")
        self.play_btn   = tbtn(">", "Play / Pause (Space)", 34)
        self.play_btn.setCheckable(True)
        self.next_btn   = tbtn(">>", "Next Frame")
        self.last_btn   = tbtn(">|", "Last Frame (End)")
        self.stop_btn   = tbtn("[]", "Stop & Rewind")

        self.first_btn.clicked.connect(lambda: self._jump(0))
        self.prev_btn.clicked.connect(self._prev_frame)
        self.play_btn.clicked.connect(self._toggle_play)
        self.next_btn.clicked.connect(self._next_frame)
        self.last_btn.clicked.connect(self._go_last)
        self.stop_btn.clicked.connect(self._stop)

        for b in [self.first_btn, self.prev_btn, self.play_btn,
                  self.next_btn, self.last_btn, self.stop_btn]:
            row.addWidget(b)

        row.addSpacing(8)

        # Frame counter
        self.frame_label = QLabel("1 / 1")
        self.frame_label.setFixedWidth(60)
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.frame_label.setStyleSheet(
            f"font-family: '{FONT_FAMILY}', monospace;"
            f"font-size: {FONT_SIZE}pt; font-weight: bold; color: {TEXT_BRIGHT};"
            f"background: {BG_INPUT}; border: 1px solid {BORDER};"
            f"padding: 0 4px;"
        )
        row.addWidget(self.frame_label)

        row.addSpacing(8)

        # ── FPS ──
        row.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(12)
        self.fps_spin.setFixedWidth(52)
        self.fps_spin.setToolTip("Playback frames per second")
        self.fps_spin.valueChanged.connect(self._on_fps_changed)
        row.addWidget(self.fps_spin)

        row.addSpacing(8)

        # ── Playback mode ──
        row.addWidget(QLabel("Mode:"))
        self.mode_loop = QToolButton(); self.mode_loop.setText("Lp"); self.mode_loop.setCheckable(True); self.mode_loop.setChecked(True); self.mode_loop.setToolTip("Loop")
        self.mode_ping = QToolButton(); self.mode_ping.setText("PP"); self.mode_ping.setCheckable(True); self.mode_ping.setToolTip("Ping-Pong")
        self.mode_once = QToolButton(); self.mode_once.setText("1x"); self.mode_once.setCheckable(True); self.mode_once.setToolTip("Play Once")
        self._mode_group = QButtonGroup(self)
        for i, btn in enumerate([self.mode_loop, self.mode_ping, self.mode_once]):
            self._mode_group.addButton(btn, i)
            row.addWidget(btn)
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        row.addSpacing(8)

        # ── Loop range buttons ──
        self.loop_in_btn  = QPushButton("[ In")
        self.loop_in_btn.setToolTip("Set loop-in point at current frame")
        self.loop_in_btn.setFixedWidth(44)
        self.loop_in_btn.clicked.connect(self._set_loop_in)
        row.addWidget(self.loop_in_btn)

        self.loop_out_btn = QPushButton("Out ]")
        self.loop_out_btn.setToolTip("Set loop-out point at current frame")
        self.loop_out_btn.setFixedWidth(44)
        self.loop_out_btn.clicked.connect(self._set_loop_out)
        row.addWidget(self.loop_out_btn)

        self.loop_clear_btn = QPushButton("X Range")
        self.loop_clear_btn.setToolTip("Clear loop range")
        self.loop_clear_btn.setFixedWidth(58)
        self.loop_clear_btn.clicked.connect(self._clear_loop_range)
        row.addWidget(self.loop_clear_btn)

        row.addStretch()

        # ── Frame actions ──
        self.new_btn = QPushButton("+ New")
        self.new_btn.setToolTip("Add blank frame  (Ctrl+N)")
        self.new_btn.clicked.connect(lambda: self.frame_added.emit(False))
        row.addWidget(self.new_btn)

        self.dup_btn = QPushButton("= Dup")
        self.dup_btn.setToolTip("Duplicate current frame  (Ctrl+D)")
        self.dup_btn.clicked.connect(lambda: self.frame_added.emit(True))
        row.addWidget(self.dup_btn)

        self.del_btn = QPushButton("- Del")
        self.del_btn.setToolTip("Delete current frame  (Delete)")
        self.del_btn.clicked.connect(lambda: self.frame_deleted.emit(self.current_frame))
        row.addWidget(self.del_btn)

        row.addSpacing(8)

        # ── Thumbnail size ──
        row.addWidget(QLabel("Size:"))
        self._size_group = QButtonGroup(self)
        for key in ["S", "M", "L"]:
            btn = QToolButton()
            btn.setText(key)
            btn.setCheckable(True)
            btn.setChecked(key == DEFAULT_SIZE)
            btn.setFixedSize(24, 22)
            btn.clicked.connect(lambda _, k=key: self._set_thumb_size(k))
            self._size_group.addButton(btn)
            row.addWidget(btn)

        return row

    def _build_onion_bar(self):
        row = QHBoxLayout()
        row.setSpacing(6)

        self.onion_cb = QCheckBox("Onion Skin")
        self.onion_cb.toggled.connect(self._on_onion_changed)
        row.addWidget(self.onion_cb)

        row.addWidget(QLabel("Frames:"))
        self.onion_frames_spin = QSpinBox()
        self.onion_frames_spin.setRange(1, 8)
        self.onion_frames_spin.setValue(2)
        self.onion_frames_spin.setFixedWidth(44)
        self.onion_frames_spin.setToolTip("How many onion frames to show each side")
        self.onion_frames_spin.valueChanged.connect(self._on_onion_changed)
        row.addWidget(self.onion_frames_spin)

        row.addWidget(QLabel("Opacity:"))
        self.onion_opacity_slider = QSlider(Qt.Horizontal)
        self.onion_opacity_slider.setRange(5, 100)
        self.onion_opacity_slider.setValue(50)
        self.onion_opacity_slider.setFixedWidth(90)
        self.onion_opacity_slider.setToolTip("Onion skin opacity %")
        self.onion_opacity_slider.valueChanged.connect(self._on_onion_changed)
        row.addWidget(self.onion_opacity_slider)
        self.onion_opacity_label = QLabel("50%")
        self.onion_opacity_label.setFixedWidth(30)
        row.addWidget(self.onion_opacity_label)

        row.addStretch()
        return row

    def _build_strip(self):
        self.scroll = QScrollArea()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(110)
        self.scroll.setMaximumHeight(130)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG_INPUT}; border: 1px solid {BORDER_DARK}; }}"
        )

        self.frame_strip = QWidget()
        self.frame_strip.setStyleSheet("background: transparent;")
        self.strip_layout = QHBoxLayout(self.frame_strip)
        self.strip_layout.setContentsMargins(8, 4, 8, 4)
        self.strip_layout.setSpacing(6)
        self.strip_layout.addStretch()
        self.scroll.setWidget(self.frame_strip)

        self.frame_widgets: list[FrameThumbnail] = []
        return self.scroll

    def _build_status_bar(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status_label = QLabel("0 frames  .  0.0 s total")
        self.status_label.setStyleSheet(
            f"color: {TEXT}; font-family: '{FONT_FAMILY}', monospace; font-size: {FONT_SIZE}pt;"
        )
        row.addWidget(self.status_label)
        row.addStretch()
        self.live_fps_label = QLabel("")
        self.live_fps_label.setStyleSheet(
            f"color: {ACCENT}; font-family: '{FONT_FAMILY}', monospace; "
            f"font-size: {FONT_SIZE}pt; font-weight: bold;"
        )
        row.addWidget(self.live_fps_label)
        return row

    # ── Public API ──────────────────────────────────────────────────────────

    def refresh_frames(self, frame_count, current_frame, thumbnails=None):
        """Rebuild the frame strip. Call whenever frame list changes."""
        self.current_frame = current_frame
        self._primary_frame = current_frame
        if not (0 <= self._secondary_frame < frame_count):
            self._secondary_frame = -1

        # Clear strip (keep stretch at end)
        while self.strip_layout.count() > 0:
            item = self.strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.frame_widgets.clear()

        tw, th, cw, ch = THUMB_SIZES[self._thumb_size]

        for i in range(frame_count):
            cell = FrameThumbnail(i, tw, th, cw, ch)
            cell.is_selected = (i == current_frame)
            cell.is_secondary = (i == self._secondary_frame)
            cell.is_loop_in  = (i == self._loop_in)
            cell.is_loop_out = (i == self._loop_out)
            cell.duration    = self._frame_durations.get(i, 1)
            if thumbnails and i < len(thumbnails) and thumbnails[i] is not None:
                cell.set_thumbnail(thumbnails[i])
            cell.clicked.connect(self._on_frame_clicked)
            cell.ctrl_clicked.connect(self._on_frame_ctrl_clicked)
            cell.right_clicked.connect(self._on_frame_right_clicked)
            cell.move_requested.connect(self._on_move_requested)
            self.strip_layout.addWidget(cell)
            self.frame_widgets.append(cell)
            if self._should_show_inline_tween_after(i):
                self.strip_layout.addWidget(self._make_inline_tween_button(ch))

        self.strip_layout.addStretch()
        self._update_frame_label(current_frame, frame_count)
        self._update_status()
        self._update_tween_status()
        self._scroll_to(current_frame, immediate=True)

    def update_thumbnail(self, frame_idx, image):
        """Update a single frame's thumbnail without full rebuild."""
        if 0 <= frame_idx < len(self.frame_widgets):
            self.frame_widgets[frame_idx].set_thumbnail(image)

    def set_fps(self, fps):
        self.fps_spin.setValue(fps)

    # ── Internal frame navigation ────────────────────────────────────────────

    def _jump(self, idx):
        if not self.frame_widgets:
            return
        idx = max(0, min(idx, len(self.frame_widgets) - 1))
        self._on_frame_clicked(idx)

    def _prev_frame(self):
        lo = self._loop_in  if self._loop_in  >= 0 else 0
        hi = self._loop_out if self._loop_out >= 0 else len(self.frame_widgets) - 1
        nxt = self.current_frame - 1
        if nxt < lo:
            nxt = hi
        self._jump(nxt)

    def _next_frame(self):
        lo = self._loop_in  if self._loop_in  >= 0 else 0
        hi = self._loop_out if self._loop_out >= 0 else len(self.frame_widgets) - 1
        nxt = self.current_frame + 1
        if nxt > hi:
            nxt = lo
        self._jump(nxt)

    def _go_last(self):
        self._jump(len(self.frame_widgets) - 1)

    def _on_frame_clicked(self, idx):
        if not (0 <= idx < len(self.frame_widgets)):
            return
        self.current_frame = idx
        self._primary_frame = idx
        self._secondary_frame = -1
        self._update_frame_label(idx, len(self.frame_widgets))
        for w in self.frame_widgets:
            w.is_selected = (w.frame_idx == idx)
            w.is_secondary = False
            w.update()
        self.frame_selected.emit(idx)
        self._rebuild_strip_preserving_frames()
        self._update_tween_status()
        self._scroll_to(idx)

    def _on_frame_ctrl_clicked(self, idx):
        if not (0 <= idx < len(self.frame_widgets)):
            return
        if idx == self._primary_frame:
            self._secondary_frame = -1
        else:
            self._secondary_frame = idx
            self.secondary_frame_selected.emit(idx)
        for w in self.frame_widgets:
            w.is_selected = (w.frame_idx == self._primary_frame)
            w.is_secondary = (w.frame_idx == self._secondary_frame)
            w.update()
        self._rebuild_strip_preserving_frames()
        self._update_tween_status()

    def _should_show_inline_tween_after(self, idx):
        if self._secondary_frame == -1:
            return False
        a, b = sorted((self._primary_frame, self._secondary_frame))
        return b - a == 1 and idx == a

    def _make_inline_tween_button(self, height):
        btn = QPushButton("⟳ Tween")
        btn.setFixedSize(28, height)
        btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_DIM}; color: {TEXT_BRIGHT}; "
            f"border: 1px solid {ACCENT}; padding: 0; }}"
        )
        btn.clicked.connect(lambda _=False: self.predict_intermediate_requested.emit())
        return btn

    def _rebuild_strip_preserving_frames(self):
        thumbnails = []
        for w in self.frame_widgets:
            thumbnails.append(w.thumbnail.toImage() if w.thumbnail is not None else None)
        self.refresh_frames(len(self.frame_widgets), self._primary_frame, thumbnails)

    def _update_tween_status(self):
        if self._secondary_frame != -1 and abs(self._primary_frame - self._secondary_frame) > 1:
            self.status_label.setStyleSheet(
                f"color: {YELLOW}; font-family: '{FONT_FAMILY}', monospace; font-size: {FONT_SIZE}pt;"
            )
            self.status_label.setText("Select two adjacent frames to use AI Tween")
        else:
            self.status_label.setStyleSheet(
                f"color: {TEXT}; font-family: '{FONT_FAMILY}', monospace; font-size: {FONT_SIZE}pt;"
            )
            self._update_status()

    def selected_frame_pair(self):
        if self._secondary_frame == -1:
            return None
        return tuple(sorted((self._primary_frame, self._secondary_frame)))

    def clear_secondary_selection(self):
        self._secondary_frame = -1
        for w in self.frame_widgets:
            w.is_secondary = False
            w.update()
        self._rebuild_strip_preserving_frames()

    def _scroll_to(self, idx, immediate=False):
        if idx < len(self.frame_widgets):
            def do_scroll():
                if idx < len(self.frame_widgets):
                    self.scroll.ensureWidgetVisible(self.frame_widgets[idx])
            if immediate:
                QTimer.singleShot(60, do_scroll)
            else:
                do_scroll()

    # ── Playback ────────────────────────────────────────────────────────────

    def _toggle_play(self, checked):
        self.is_playing = checked
        if checked:
            self.play_btn.setText("||")
            self._ping_direction = 1
            self._dur_tick = 0
            interval = max(16, int(1000 / self.fps))
            self.play_timer.start(interval)
            self.live_fps_label.setText(f"> {self.fps} fps")
        else:
            self.play_btn.setText(">")
            self.play_timer.stop()
            self.live_fps_label.setText("")
        self.play_toggled.emit(checked)

    def _stop(self):
        self.is_playing = False
        self.play_btn.setChecked(False)
        self.play_btn.setText(">")
        self.play_timer.stop()
        self.live_fps_label.setText("")
        self._jump(self._loop_in if self._loop_in >= 0 else 0)
        self.play_toggled.emit(False)

    def _on_play_tick(self):
        total = len(self.frame_widgets)
        if total <= 1:
            return

        lo = self._loop_in  if self._loop_in  >= 0 else 0
        hi = self._loop_out if self._loop_out >= 0 else total - 1
        lo, hi = min(lo, hi), max(lo, hi)

        # Handle per-frame duration
        dur = self._frame_durations.get(self.current_frame, 1)
        self._dur_tick += 1
        if self._dur_tick < dur:
            return
        self._dur_tick = 0

        if self._playback_mode == "ping_pong":
            nxt = self.current_frame + self._ping_direction
            if nxt > hi:
                self._ping_direction = -1
                nxt = hi - 1
            elif nxt < lo:
                self._ping_direction = 1
                nxt = lo + 1
        elif self._playback_mode == "once":
            nxt = self.current_frame + 1
            if nxt > hi:
                self._stop()
                return
        else:   # loop
            nxt = self.current_frame + 1
            if nxt > hi:
                nxt = lo

        self._on_frame_clicked(max(lo, min(nxt, hi)))

    # ── Context menu ────────────────────────────────────────────────────────

    def _on_frame_right_clicked(self, idx, global_pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_HEADER};
                border: 1px solid {BORDER};
                color: {TEXT};
                font-family: '{FONT_FAMILY}', monospace;
                font-size: {FONT_SIZE}pt;
                padding: 3px 0;
            }}
            QMenu::item {{ padding: 4px 18px; }}
            QMenu::item:selected {{ background: {ACCENT_DIM}; color: {TEXT_BRIGHT}; }}
            QMenu::item:disabled {{ color: {TEXT_DIM}; }}
            QMenu::separator {{ height: 1px; background: {BORDER}; margin: 3px 0; }}
        """)

        menu.addAction(f"Frame {idx + 1}").setEnabled(False)
        menu.addSeparator()

        a_ins_before = menu.addAction("Insert Frame Before")
        a_ins_after  = menu.addAction("Insert Frame After")
        a_dup        = menu.addAction("Duplicate Frame  Ctrl+D")
        menu.addSeparator()
        a_del        = menu.addAction("Delete Frame  Del")
        a_clear      = menu.addAction("Clear Frame Contents")
        menu.addSeparator()
        a_dur        = menu.addAction("Set Duration Multiplier...")
        a_loop_in    = menu.addAction("Set as Loop-In Point")
        a_loop_out   = menu.addAction("Set as Loop-Out Point")

        action = menu.exec_(global_pos)
        if action == a_ins_before:
            self.frame_inserted_before.emit(idx)
        elif action == a_ins_after:
            self.frame_inserted_after.emit(idx)
        elif action == a_dup:
            self.frame_added.emit(True)
        elif action == a_del:
            self.frame_deleted.emit(idx)
        elif action == a_clear:
            self.frame_cleared.emit(idx)
        elif action == a_dur:
            self._ask_frame_duration(idx)
        elif action == a_loop_in:
            self._loop_in = idx
            self._refresh_loop_markers()
            self.loop_range_changed.emit(self._loop_in, self._loop_out)
        elif action == a_loop_out:
            self._loop_out = idx
            self._refresh_loop_markers()
            self.loop_range_changed.emit(self._loop_in, self._loop_out)

    def _ask_frame_duration(self, idx):
        current = self._frame_durations.get(idx, 1)
        val, ok = QInputDialog.getInt(
            self, "Frame Duration",
            f"Duration multiplier for frame {idx + 1}\n(1 = normal, 2 = holds twice as long):",
            current, 1, 32)
        if ok:
            self._frame_durations[idx] = val
            if idx < len(self.frame_widgets):
                self.frame_widgets[idx].duration = val
                self.frame_widgets[idx].update()
            self.frame_duration_changed.emit(idx, val)
            self._update_status()

    # ── Loop range ──────────────────────────────────────────────────────────

    def _set_loop_in(self):
        self._loop_in = self.current_frame
        self._refresh_loop_markers()
        self.loop_range_changed.emit(self._loop_in, self._loop_out)

    def _set_loop_out(self):
        self._loop_out = self.current_frame
        self._refresh_loop_markers()
        self.loop_range_changed.emit(self._loop_in, self._loop_out)

    def _clear_loop_range(self):
        self._loop_in = -1
        self._loop_out = -1
        self._refresh_loop_markers()
        self.loop_range_changed.emit(-1, -1)

    def _refresh_loop_markers(self):
        for w in self.frame_widgets:
            w.is_loop_in  = (w.frame_idx == self._loop_in)
            w.is_loop_out = (w.frame_idx == self._loop_out)
            w.update()

    # ── Drag reorder ────────────────────────────────────────────────────────

    def _on_move_requested(self, from_idx, to_idx):
        total = len(self.frame_widgets)
        to_idx = max(0, min(to_idx, total - 1))
        if from_idx == to_idx:
            return
        self.frame_moved.emit(from_idx, to_idx)

    # ── Mode & settings ─────────────────────────────────────────────────────

    def _on_mode_changed(self, btn):
        modes = ["loop", "ping_pong", "once"]
        idx = self._mode_group.id(btn)
        self._playback_mode = modes[idx]
        self.playback_mode_changed.emit(self._playback_mode)

    def _on_fps_changed(self, val):
        self.fps = val
        if self.is_playing:
            self.play_timer.setInterval(max(16, int(1000 / val)))
            self.live_fps_label.setText(f"> {val} fps")
        self.fps_changed.emit(val)
        self._update_status()

    def _on_onion_changed(self, *_):
        enabled = self.onion_cb.isChecked()
        frames  = self.onion_frames_spin.value()
        opacity = self.onion_opacity_slider.value()
        self.onion_opacity_label.setText(f"{opacity}%")
        self.onion_skin_changed.emit(enabled, frames, opacity)

    def _set_thumb_size(self, key):
        self._thumb_size = key
        tw, th, cw, ch = THUMB_SIZES[key]
        for w in self.frame_widgets:
            w.resize_cells(tw, th, cw, ch)
        self.frame_strip.adjustSize()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _update_frame_label(self, current, total):
        self.frame_label.setText(f"{current + 1} / {total}")

    def _update_status(self):
        n = len(self.frame_widgets)
        total_ticks = sum(self._frame_durations.get(i, 1) for i in range(n))
        secs = total_ticks / max(1, self.fps)
        self.status_label.setText(
            f"{n} frame{'s' if n != 1 else ''}  .  {secs:.2f} s  .  {self.fps} fps"
        )

    # ── Keyboard shortcuts ───────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Space:
            self.play_btn.setChecked(not self.play_btn.isChecked())
            self._toggle_play(self.play_btn.isChecked())
        elif key == Qt.Key_Left:
            self._prev_frame()
        elif key == Qt.Key_Right:
            self._next_frame()
        elif key == Qt.Key_Home:
            self._jump(0)
        elif key == Qt.Key_End:
            self._go_last()
        elif key == Qt.Key_Delete:
            self.frame_deleted.emit(self.current_frame)
        elif mods == Qt.ControlModifier and key == Qt.Key_D:
            self.frame_added.emit(True)
        elif mods == Qt.ControlModifier and key == Qt.Key_N:
            self.frame_added.emit(False)
        else:
            super().keyPressEvent(event)
