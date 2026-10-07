"""
Aseprite-style dark theme for SpriteStack Studio.

All design tokens, color constants, icon helpers, and the global QSS stylesheet
live here so every panel imports from one place.

Style rules:
  - No anti-aliasing, no rounded corners, hard 1px borders everywhere
  - Pixel-art-friendly monospace font (Courier New 9pt)
  - Flat 16x16 pixel icons, no shadows/gradients/material effects
"""

from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygon
from PyQt5.QtCore import Qt, QPoint, QSize

# ---------------------------------------------------------------------------
# Aseprite Design Tokens
# ---------------------------------------------------------------------------

# Backgrounds
BG_DARK       = "#1e1e2e"   # Main window / app background
BG_PANEL      = "#1f1f2e"   # Panel interiors
BG_HEADER     = "#252535"   # Toolbar, panel headers, dock titles
BG_INPUT      = "#171726"   # Input fields, list backgrounds
BG_RAISED     = "#2a2a3c"   # Raised elements (buttons idle)

# Borders
BORDER        = "#3a3a4a"   # Primary border / divider
BORDER_LIGHT  = "#44445a"   # Lighter border for hover
BORDER_DARK   = "#2e2e3e"   # Subtle inner borders

# Accent / selection
ACCENT        = "#5c7cfa"   # Active / selected highlight (Aseprite blue)
ACCENT_HOVER  = "#6d8cff"   # Lighter accent on hover
ACCENT_DIM    = "#3a4a80"   # Muted accent for subtle indicators

# Text
TEXT          = "#c8c8d4"   # Primary text
TEXT_MUTED    = "#7a7a8a"   # Labels, secondary text
TEXT_BRIGHT   = "#e8e8f0"   # Highlighted / active text
TEXT_DIM      = "#555566"   # Disabled / very muted
TEXT_ON_DARK  = "#dcdce8"   # minimum-contrast body text on any dark bg

# Semantic colors
RED           = "#e05050"
GREEN         = "#50c878"
YELLOW        = "#d4aa40"
CYAN          = "#50b8d8"

# Checker (canvas transparency)
CHECKER_1     = "#2a2a3a"
CHECKER_2     = "#222232"

# Typography
FONT_FAMILY   = "Courier New"
FONT_SIZE     = 9   # pt
ICON_SIZE     = 16

# Convenience dict for use in f-strings
T = {
    "bg":           BG_DARK,
    "bg_panel":     BG_PANEL,
    "bg_header":    BG_HEADER,
    "bg_input":     BG_INPUT,
    "bg_raised":    BG_RAISED,
    "border":       BORDER,
    "border_light": BORDER_LIGHT,
    "border_dark":  BORDER_DARK,
    "accent":       ACCENT,
    "accent_hover": ACCENT_HOVER,
    "accent_dim":   ACCENT_DIM,
    "text":         TEXT,
    "text_muted":   TEXT_MUTED,
    "text_bright":  TEXT_BRIGHT,
    "text_dim":     TEXT_DIM,
    "text_on_dark": TEXT_ON_DARK,
    "red":          RED,
    "green":        GREEN,
    "yellow":       YELLOW,
    "cyan":         CYAN,
    "font":         FONT_FAMILY,
    "font_size":    str(FONT_SIZE),
}


# ---------------------------------------------------------------------------
# Icon helpers — flat 16x16 pixel icons, no AA
# ---------------------------------------------------------------------------

def make_icon(draw_func, size=ICON_SIZE, bg=Qt.transparent):
    """Render a 16x16 flat pixel icon via *draw_func(painter, size)*."""
    pix = QPixmap(size, size)
    pix.fill(bg)
    p = QPainter(pix)
    # No antialiasing — pixel-perfect
    p.setRenderHint(QPainter.Antialiasing, False)
    draw_func(p, size)
    p.end()
    return QIcon(pix)


def text_icon(glyph, fg=TEXT, size=ICON_SIZE):
    """Render a single Unicode glyph into a flat icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setPen(QColor(fg))
    f = QFont(FONT_FAMILY, max(7, size - 6))
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 0, size, size, Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pix)


# ---------------------------------------------------------------------------
# Tool icons — simple flat pixel drawings
# ---------------------------------------------------------------------------

def _pencil(p, s):
    p.setPen(QPen(QColor(TEXT), 1))
    p.drawLine(3, s-3, s-3, 3)
    p.setPen(QPen(QColor(YELLOW), 1))
    p.drawLine(3, s-3, 5, s-5)

def _eraser(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(RED))
    p.drawRect(3, 5, s-6, s-8)
    p.setBrush(QColor("#ff9090"))
    p.drawRect(3, 3, s-6, 5)

def _fill(p, s):
    p.setPen(QPen(QColor(ACCENT), 1))
    poly = QPolygon([QPoint(4, 4), QPoint(s-3, 4),
                     QPoint(s-4, s-4), QPoint(3, s-4)])
    p.drawPolygon(poly)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    p.drawRect(s-6, s-7, 4, 5)

def _eyedropper(p, s):
    p.setPen(QPen(QColor(YELLOW), 1))
    p.drawLine(4, s-4, s-4, 4)
    p.setBrush(QColor(YELLOW))
    p.drawRect(s-6, 2, 4, 4)

def _line(p, s):
    p.setPen(QPen(QColor(GREEN), 1))
    p.drawLine(3, s-3, s-3, 3)

def _rect(p, s):
    p.setPen(QPen(QColor(CYAN), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(3, 3, s-6, s-6)

def _rect_fill(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(CYAN))
    p.drawRect(3, 3, s-6, s-6)

def _circle(p, s):
    p.setPen(QPen(QColor("#d080d0"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(3, 3, s-6, s-6)

def _circle_fill(p, s):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#d080d0"))
    p.drawEllipse(3, 3, s-6, s-6)

def _select(p, s):
    p.setPen(QPen(QColor(TEXT_MUTED), 1, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(3, 3, s-6, s-6)

def _move(p, s):
    mid = s // 2
    p.setPen(QPen(QColor(ACCENT), 1))
    p.drawLine(mid, 2, mid, s-2)
    p.drawLine(2, mid, s-2, mid)
    # arrows
    p.drawLine(mid, 2, mid-2, 4)
    p.drawLine(mid, 2, mid+2, 4)
    p.drawLine(mid, s-2, mid-2, s-4)
    p.drawLine(mid, s-2, mid+2, s-4)

def _wand(p, s):
    p.setPen(QPen(QColor(YELLOW), 1))
    p.drawLine(3, s-3, s-4, 4)
    p.setPen(QPen(QColor(TEXT), 1))
    for dx, dy in [(2, 2), (s-3, 6), (6, s-5)]:
        p.drawPoint(dx, dy)

def _symmetry(p, s):
    mid = s // 2
    p.setPen(QPen(QColor("#9070d0"), 1))
    p.drawLine(mid, 2, mid, s-2)
    p.setPen(QPen(QColor(TEXT_MUTED), 1, Qt.DotLine))
    p.drawRect(3, 3, s-6, s-6)


TOOL_ICONS = {
    "pencil":      lambda: make_icon(_pencil),
    "eraser":      lambda: make_icon(_eraser),
    "fill":        lambda: make_icon(_fill),
    "eyedropper":  lambda: make_icon(_eyedropper),
    "line":        lambda: make_icon(_line),
    "rect":        lambda: make_icon(_rect),
    "rect_fill":   lambda: make_icon(_rect_fill),
    "circle":      lambda: make_icon(_circle),
    "circle_fill": lambda: make_icon(_circle_fill),
    "select":      lambda: make_icon(_select),
    "symmetry":    lambda: make_icon(_symmetry),
    "move":        lambda: make_icon(_move),
    "magic_wand":  lambda: make_icon(_wand),
}


# ---------------------------------------------------------------------------
# Global Aseprite-style QSS Stylesheet
# ---------------------------------------------------------------------------

ASEPRITE_STYLESHEET = f"""
/* ── Base ────────────────────────────────────────────── */
QMainWindow, QDialog {{
    background-color: {BG_DARK};
}}
QWidget {{
    background-color: {BG_PANEL};
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}

/* ── Menu bar ────────────────────────────────────────── */
QMenuBar {{
    background-color: {BG_HEADER};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
    padding: 1px 0;
}}
QMenuBar::item {{
    padding: 3px 8px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}

QMenu {{
    background-color: {BG_HEADER};
    color: {TEXT};
    border: 1px solid {BORDER};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QMenu::item {{
    padding: 4px 20px 4px 10px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 2px 0;
}}

/* ── Toolbar ─────────────────────────────────────────── */
QToolBar {{
    background-color: {BG_HEADER};
    border: none;
    border-bottom: 1px solid {BORDER};
    spacing: 1px;
    padding: 1px;
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 2px 1px;
}}

/* ── Tool buttons ────────────────────────────────────── */
QToolButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    padding: 2px;
    color: {TEXT_MUTED};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QToolButton:hover {{
    background-color: {BG_HEADER};
    border-color: {BORDER_LIGHT};
    color: {TEXT};
}}
QToolButton:pressed {{
    background-color: {BG_INPUT};
}}
QToolButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}

/* ── Push buttons ────────────────────────────────────── */
QPushButton {{
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    padding: 3px 8px;
    color: {TEXT};
    min-height: 18px;
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QPushButton:hover {{
    background-color: {BG_HEADER};
    border-color: {BORDER_LIGHT};
    color: {TEXT_BRIGHT};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
}}
QPushButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER_DARK};
    background-color: {BG_PANEL};
}}
QPushButton[flat="true"] {{
    color: {TEXT_ON_DARK};
}}

/* ── GroupBox ─────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    margin-top: 8px;
    padding-top: 12px;
    color: {TEXT_MUTED};
    font-weight: bold;
    font-size: {FONT_SIZE}pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 6px;
    padding: 0 4px;
    color: {TEXT_MUTED};
}}

/* ── Slider ──────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: 1px solid {BORDER};
    height: 4px;
    background: {BG_INPUT};
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
}}
QSlider::handle:horizontal {{
    background: {TEXT};
    border: 1px solid {BORDER};
    width: 8px;
    margin: -3px 0;
}}

/* ── Spin / Line edit ────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    padding: 1px 3px;
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    padding: 2px 4px;
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

/* ── ComboBox ────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    padding: 2px 6px;
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QComboBox:hover {{
    border-color: {BORDER_LIGHT};
}}
QComboBox::drop-down {{
    background-color: {BG_RAISED};
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_HEADER};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: {TEXT_BRIGHT};
}}

/* ── List / scroll area ──────────────────────────────── */
QListWidget {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    outline: none;
}}
QListWidget::item {{
    padding: 0px;
    border-bottom: 1px solid {BORDER_DARK};
}}
QListWidget::item:selected {{
    background-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}
QListWidget::item:hover:!selected {{
    background-color: {BG_RAISED};
}}

QScrollArea {{
    border: 1px solid {BORDER_DARK};
    background: {BG_INPUT};
}}

/* ── Scrollbars ──────────────────────────────────────── */
QScrollBar:horizontal, QScrollBar:vertical {{
    background-color: {BG_DARK};
    border: none;
    width: 8px;
    height: 8px;
}}
QScrollBar::handle:horizontal, QScrollBar::handle:vertical {{
    background-color: {BORDER};
    min-height: 16px;
    min-width: 16px;
}}
QScrollBar::handle:hover {{
    background-color: {ACCENT};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}

/* ── CheckBox ────────────────────────────────────────── */
QCheckBox {{
    spacing: 4px;
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QCheckBox::indicator {{
    width: 12px;
    height: 12px;
    background: {BG_INPUT};
    border: 1px solid {BORDER};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Status bar ──────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_HEADER};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
    min-height: 18px;
}}
QStatusBar::item {{
    border: none;
}}

/* ── Splitter ────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
    height: 1px;
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

/* ── Tab widget ──────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG_PANEL};
}}
QTabBar::tab {{
    background-color: {BG_HEADER};
    color: {TEXT};
    padding: 4px 10px;
    border: 1px solid {BORDER};
    border-bottom: none;
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}
QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {TEXT_BRIGHT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: {BG_RAISED};
    color: {TEXT};
}}

/* ── Dock widget ─────────────────────────────────────── */
QDockWidget {{
    border: 1px solid {BORDER};
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {BG_HEADER};
    padding: 3px 6px;
    border-bottom: 1px solid {BORDER};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
    color: {TEXT_MUTED};
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    padding: 0px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {ACCENT};
}}

/* ── Dialog buttons ──────────────────────────────────── */
QDialogButtonBox QPushButton {{
    min-width: 60px;
    padding: 4px 12px;
}}

/* ── Labels ──────────────────────────────────────────── */
QLabel {{
    color: {TEXT};
    background: transparent;
}}

/* ── Frame dividers ──────────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {BORDER};
}}

/* ── Tree widget ─────────────────────────────────────── */
QTreeWidget {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    outline: none;
}}
QTreeWidget::item {{
    padding: 2px 0;
}}
QTreeWidget::item:selected {{
    background-color: {ACCENT};
    color: {TEXT_BRIGHT};
}}
QTreeWidget::item:hover:!selected {{
    background-color: {BG_RAISED};
}}
QHeaderView::section {{
    background-color: {BG_HEADER};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    padding: 2px 4px;
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}

/* ── Progress bar ────────────────────────────────────── */
QProgressBar {{
    border: 1px solid {BORDER};
    text-align: center;
    background: {BG_INPUT};
    color: {TEXT_MUTED};
    font-size: {FONT_SIZE}pt;
}}
QProgressBar::chunk {{
    background: {ACCENT};
}}
"""
