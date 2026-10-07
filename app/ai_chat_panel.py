from __future__ import annotations

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app.theme import T as _T


class _ChatInput(QPlainTextEdit):
    submit_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not (event.modifiers() & Qt.ShiftModifier):
                event.accept()
                self.submit_requested.emit()
                return
        super().keyPressEvent(event)


class _ChatMessageDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._padding = 8
        self._outer_margin = 6

    def _bubble_metrics(self, option, text: str, is_user: bool) -> tuple[QRect, QRect]:
        area = option.rect.adjusted(self._outer_margin, 4, -self._outer_margin, -4)
        max_width = max(80, int(area.width() * 0.78))
        text_rect = option.fontMetrics.boundingRect(
            QRect(0, 0, max_width, 10000),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )
        bubble = QRect(0, 0, text_rect.width() + self._padding * 2, text_rect.height() + self._padding * 2)
        if is_user:
            bubble.moveTopRight(area.topRight())
        else:
            bubble.moveTopLeft(area.topLeft())
        draw_text = bubble.adjusted(self._padding, self._padding, -self._padding, -self._padding)
        return bubble, draw_text

    def paint(self, painter: QPainter, option, index):
        payload = index.data(Qt.UserRole) or {}
        role = str(payload.get("role") or "ai").lower()
        text = str(payload.get("text") or "")
        is_user = role == "user"

        bubble_rect, text_rect = self._bubble_metrics(option, text, is_user)

        bubble_bg = QColor(_T["accent_dim"] if is_user else _T["bg_panel"])
        text_color = QColor(_T["text_bright"] if is_user else _T["text_bright"])
        border_color = QColor(_T["border"])

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(bubble_rect, bubble_bg)
        if not is_user:
            painter.fillRect(QRect(bubble_rect.left(), bubble_rect.top(), 1, bubble_rect.height()), border_color)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        payload = index.data(Qt.UserRole) or {}
        text = str(payload.get("text") or "")
        list_widget = self.parent()
        width = list_widget.viewport().width() if list_widget is not None else 260
        max_width = max(80, int(width * 0.78))
        text_rect = option.fontMetrics.boundingRect(
            QRect(0, 0, max_width, 10000),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )
        return QSize(width, text_rect.height() + self._padding * 2 + 12)


class AIChatPanel(QWidget):
    send_requested = pyqtSignal(str, dict)

    _DEFAULT_SUGGESTIONS = [
        "How do I write a good prompt?",
        "What does strength control?",
        "Explain blend vs replace",
        "Suggest style tags for this sprite",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._context = {
            "canvas_width": 0,
            "canvas_height": 0,
            "active_layer_name": "",
            "has_selection": False,
            "selection_rect": None,
            "layer_count": 0,
            "current_mode": "full",
        }
        self._current_mode = "full"
        self._suggestion_buttons: list[QPushButton] = []

        self._build_ui()
        self.set_suggestions(list(self._DEFAULT_SUGGESTIONS))

    def _build_ui(self):
        self.setStyleSheet(
            f"QWidget {{ background: {_T['bg_panel']}; color: {_T['text']}; "
            f"font-family: '{_T['font']}'; font-size: {_T['font_size']}pt; }}"
            f"QListWidget {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; color: {_T['text_bright']}; }}"
            f"QPlainTextEdit {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; }}"
            f"QPushButton {{ background: {_T['bg_raised']}; border: 1px solid {_T['border']}; color: {_T['text_bright']}; padding: 3px 8px; }}"
            f"QPushButton:hover {{ border-color: {_T['border_light']}; color: {_T['text_bright']}; }}"
            f"QPushButton:disabled {{ background: {_T['bg_panel']}; color: {_T['text_dim']}; border-color: {_T['border_dark']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("AI Assistant")
        title.setStyleSheet(f"QLabel {{ color: {_T['text_bright']}; font-weight: bold; }}")
        header.addWidget(title)
        header.addStretch(1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFlat(True)
        self.clear_btn.clicked.connect(self._clear_messages)
        header.addWidget(self.clear_btn)
        root.addLayout(header)

        self.message_list = QListWidget()
        self.message_list.setWordWrap(True)
        self.message_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_list.setItemDelegate(_ChatMessageDelegate(self.message_list))
        root.addWidget(self.message_list, 1)

        self.suggestions_frame = QFrame()
        self.suggestions_frame.setStyleSheet(f"QFrame {{ border-top: 1px solid {_T['border']}; }}")
        s_lay = QVBoxLayout(self.suggestions_frame)
        s_lay.setContentsMargins(0, 6, 0, 0)
        s_lay.setSpacing(6)
        self.suggestions_label = QLabel("Suggestions:")
        self.suggestions_label.setStyleSheet(
            f"QLabel {{ color: {_T['text_bright']}; font-size: {int(_T['font_size']) + 1}pt; }}"
        )
        s_lay.addWidget(self.suggestions_label)
        self.suggestions_row = QHBoxLayout()
        self.suggestions_row.setSpacing(4)
        s_lay.addLayout(self.suggestions_row)
        root.addWidget(self.suggestions_frame)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self.input_edit = _ChatInput()
        self.input_edit.setPlaceholderText("Ask for prompt tips or mode guidance…")
        line_height = self.input_edit.fontMetrics().lineSpacing()
        self.input_edit.setFixedHeight(line_height * 2 + 16)
        self.input_edit.submit_requested.connect(self._send_from_input)
        input_row.addWidget(self.input_edit, 1)

        self.send_btn = QPushButton("↑")
        self.send_btn.setFixedWidth(34)
        self.send_btn.clicked.connect(self._send_from_input)
        input_row.addWidget(self.send_btn)
        root.addLayout(input_row)

    def _clear_messages(self):
        self.message_list.clear()
        self.set_suggestions(list(self._DEFAULT_SUGGESTIONS))

    def _send_from_input(self):
        self._send(self.input_edit.toPlainText())

    def _send(self, text: str):
        clean = (text or "").strip()
        if not clean:
            return
        self.add_message("user", clean)
        self.send_requested.emit(clean, dict(self._context))
        self.input_edit.clear()
        self.set_generating(True)

    def add_message(self, role: str, text: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, {"role": role, "text": text})
        item.setFlags(Qt.ItemIsEnabled)
        self.message_list.addItem(item)
        self.message_list.scrollToBottom()

    def set_generating(self, is_generating: bool) -> None:
        self.send_btn.setEnabled(not is_generating)
        self.input_edit.setEnabled(not is_generating)

    def set_suggestions(self, suggestions: list[str]) -> None:
        while self.suggestions_row.count():
            item = self.suggestions_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._suggestion_buttons.clear()

        for text in suggestions:
            label = str(text).strip()
            if not label:
                continue
            button = QPushButton(label)
            button.setFlat(True)
            button.clicked.connect(lambda _=False, t=label: self._send(t))
            self.suggestions_row.addWidget(button)
            self._suggestion_buttons.append(button)
        self.suggestions_row.addStretch(1)

    def set_current_mode(self, mode: str):
        self._current_mode = str(mode or "full")
        self._context["current_mode"] = self._current_mode

    def update_context(self, canvas) -> None:
        width = int(getattr(canvas, "canvas_width", 0) or 0)
        height = int(getattr(canvas, "canvas_height", 0) or 0)
        active_idx = int(getattr(canvas, "active_layer", 0) or 0)
        layer_names = getattr(canvas, "layer_names", []) or []
        active_name = str(layer_names[active_idx]) if 0 <= active_idx < len(layer_names) else f"Layer {active_idx + 1}"
        rect = getattr(canvas, "selection_rect", None)
        rect_payload = None
        if rect is not None:
            rect_payload = {
                "x": int(rect.x()),
                "y": int(rect.y()),
                "w": int(rect.width()),
                "h": int(rect.height()),
            }
        self._context = {
            "canvas_width": width,
            "canvas_height": height,
            "active_layer_name": active_name,
            "has_selection": rect is not None,
            "selection_rect": rect_payload,
            "layer_count": len(getattr(canvas, "layers", []) or []),
            "current_mode": self._current_mode,
        }
