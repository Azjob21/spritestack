#!/usr/bin/env python3
"""
SpriteStack Studio - A sprite stacking and pixel art editor for Windows.
Entry point for the application.
"""

import sys
import os

# Ensure app directory is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt5.QtCore import Qt

from app.main_window import MainWindow, DARK_STYLESHEET


def create_app_icon():
    """Generate a simple app icon programmatically."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Draw stacked layers icon
    colors = [
        QColor(65, 105, 225),   # Royal blue
        QColor(50, 205, 50),    # Lime green
        QColor(255, 165, 0),    # Orange
        QColor(220, 20, 60),    # Crimson
    ]

    for i, color in enumerate(colors):
        y = 44 - i * 12
        painter.setBrush(color)
        painter.setPen(QColor(0, 0, 0, 100))
        painter.drawRoundedRect(8, y, 48, 16, 3, 3)

    painter.end()
    return QIcon(pixmap)


def main():
    # Default to a more readable UI scale; users can override via env vars.
    if "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = os.environ.get("SPRITESTACK_UI_SCALE", "1.25")

    # High DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("SpriteStack Studio")
    app.setOrganizationName("SpriteStackStudio")
    app.setApplicationVersion("1.0.0")

    # Set dark theme
    app.setStyleSheet(DARK_STYLESHEET)

    # Set app icon
    app.setWindowIcon(create_app_icon())

    # Create and show main window
    window = MainWindow()
    window.setWindowIcon(create_app_icon())
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
