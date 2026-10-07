from __future__ import annotations

import json
import os
import tempfile

from PyQt5.QtCore import QByteArray, QFile, QIODevice, QTimer, QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkRequest,
)
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QShortcut,
    QToolButton,
    QWidget,
    QLabel,
    QSpinBox,
)

from app.theme import T as _T

try:
    from PyQt5.QtMultimedia import QAudioEncoderSettings, QAudioRecorder, QMediaRecorder
except Exception:
    QAudioRecorder = None
    QAudioEncoderSettings = None
    QMediaRecorder = None


class SceneUIPanel(QWidget):
    """
    Scene parser request row.
    """

    scene_parsed = pyqtSignal(dict, str)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._api_base = "http://127.0.0.1:8000"
        self._network = QNetworkAccessManager(self)

        self._record_path: str | None = None
        self._awaiting_transcribe = False
        self._is_recording = False
        self._recorder = self._build_audio_recorder()
        self.get_left_context_callback = None
        self._status_state = "idle"

        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            f"QWidget {{ background: {_T['bg_panel']}; color: {_T['text']}; }}"
            f"QLineEdit {{ background: {_T['bg_input']}; border: 1px solid {_T['border']}; padding: 4px; }}"
            f"QPushButton, QToolButton {{ background: {_T['bg_raised']}; border: 1px solid {_T['border']}; padding: 4px 8px; }}"
            f"QPushButton:hover, QToolButton:hover {{ border-color: {_T['border_light']}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(6)

        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Describe a scene, e.g. 'tree on left, rock on right'")
        self.prompt_edit.returnPressed.connect(self._request_scene_parse)
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.prompt_edit)
        shortcut.activated.connect(self._request_scene_parse)
        row.addWidget(self.prompt_edit, 1)

        self.mic_btn = QToolButton()
        self.mic_btn.setToolTip("Record voice prompt (click to start/stop)")
        self.mic_btn.setIcon(self._mic_icon())
        self.mic_btn.setText("🎙 Record")
        self.mic_btn.clicked.connect(self._toggle_recording)
        self.mic_btn.setEnabled(self._recorder is not None)
        row.addWidget(self.mic_btn)

        self.screen_label = QLabel("Target Screen:")
        self.screen_label.setStyleSheet(f"color: {_T['text']};")
        self.target_screen_spin = QSpinBox()
        self.target_screen_spin.setRange(1, 5)
        self.target_screen_spin.setValue(1)
        self.target_screen_spin.setToolTip("Which 16x16 screen chunk to generate into")
        row.addWidget(self.screen_label)
        row.addWidget(self.target_screen_spin)

        self.generate_btn = QPushButton("Generate Scene")
        self.generate_btn.clicked.connect(self._request_scene_parse)
        row.addWidget(self.generate_btn)

        self.activity_label = QLabel()
        self.activity_label.setObjectName("sceneActivityLabel")
        self.activity_label.setMinimumWidth(180)
        self.activity_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(self.activity_label)
        self._set_status("ready" if self._recorder is not None else "error",
                         "Ready to record" if self._recorder is not None else "Mic unavailable")

    def _mic_icon(self) -> QIcon:
        pix = QPixmap(20, 20)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(QColor(_T["text_bright"]), 2))
        p.drawRect(7, 3, 6, 10)
        p.drawLine(10, 13, 10, 16)
        p.drawLine(6, 16, 14, 16)
        p.drawArc(4, 8, 12, 10, 0, -180 * 16)
        p.end()
        return QIcon(pix)

    def _build_audio_recorder(self):
        if QAudioRecorder is None:
            return None
        recorder = QAudioRecorder(self)
        recorder.stateChanged.connect(self._on_recorder_state_changed)

        def _to_str(value) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            return str(value)

        def _supported_values(method_name: str) -> set[str]:
            method = getattr(recorder, method_name, None)
            if method is None:
                return set()
            try:
                return {_to_str(item) for item in method()}
            except Exception:
                return set()

        supported_containers = _supported_values("supportedContainers")
        supported_codecs = _supported_values("supportedAudioCodecs")
        supported_sample_rates = []
        sample_rate_method = getattr(recorder, "supportedAudioSampleRates", None)
        if sample_rate_method is not None:
            try:
                supported_sample_rates = [int(rate) for rate in sample_rate_method()]
            except Exception:
                supported_sample_rates = []

        settings = QAudioEncoderSettings()

        preferred_container = None
        for candidate in ("audio/x-wav", "audio/wav"):
            if not supported_containers or candidate in supported_containers:
                preferred_container = candidate
                break

        preferred_codec = None
        for candidate in ("audio/x-raw", "audio/pcm", "audio/PCM", "audio/pcma", "audio/pcmu"):
            if not supported_codecs or candidate in supported_codecs:
                preferred_codec = candidate
                break

        if preferred_container:
            recorder.setContainerFormat(preferred_container)
        if preferred_codec:
            settings.setCodec(preferred_codec)
        if supported_sample_rates:
            sample_rate = 16000 if 16000 in supported_sample_rates else supported_sample_rates[0]
            settings.setSampleRate(sample_rate)
        else:
            settings.setSampleRate(16000)
        settings.setChannelCount(1)

        try:
            recorder.setEncodingSettings(settings)
        except Exception:
            return None
        return recorder

    def _set_status(self, state: str, message: str | None = None):
        self._status_state = state
        palette = {
            "idle": (_T["text"], "Idle"),
            "ready": (_T["text_bright"], "Ready to record"),
            "recording": ("#f5c542", "Recording…"),
            "transcribing": ("#6bc4ff", "Transcribing…"),
            "parsing": ("#b48cff", "Parsing scene…"),
            "error": ("#ff7a7a", "Unavailable"),
        }
        color, fallback = palette.get(state, ( _T["text"], "Idle"))
        text = message or fallback
        if hasattr(self, "activity_label"):
            self.activity_label.setText(text)
            self.activity_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _request_scene_parse(self):
        prompt = self.prompt_edit.text().strip()
        if not prompt:
            self.status_message.emit("Scene prompt is empty.")
            return
        self.generate_btn.setEnabled(False)

        # Get left context if callback is set
        left_context = None
        if self.get_left_context_callback:
            left_context = self.get_left_context_callback()

        req = QNetworkRequest(QUrl(f"{self._api_base}/parse-scene"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        payload = {"prompt": prompt}
        if left_context is not None:
            payload["left_context"] = left_context

        body = QByteArray(json.dumps(payload).encode("utf-8"))
        reply = self._network.post(req, body)
        reply.finished.connect(lambda r=reply, p=prompt: self._on_parse_finished(r, p))
        self._set_status("parsing")
        self.status_message.emit("Parsing scene with AI — switch to Sandbox to see results…")

    def _on_parse_finished(self, reply, prompt: str):
        self.generate_btn.setEnabled(True)
        try:
            if reply.error():
                self._set_status("error", "Parse failed")
                self.status_message.emit(f"Scene parse failed: {reply.errorString()}")
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(payload, dict):
                self._set_status("error", "Parse failed")
                self.status_message.emit("Scene parse returned invalid JSON.")
                return
            self.scene_parsed.emit(payload, prompt)
            objects = payload.get("objects", []) if isinstance(payload, dict) else []
            if objects:
                self._set_status("ready", "Scene parsed")
                self.status_message.emit(f"✓ {len(objects)} object(s) placed — switch to Sandbox")
            else:
                self._set_status("ready", "Scene parsed")
                self.status_message.emit("Scene parsed — no objects recognised.")
        except Exception as exc:
            self._set_status("error", "Parse failed")
            self.status_message.emit(f"Scene parse decode error: {exc}")
        finally:
            reply.deleteLater()

    def _toggle_recording(self):
        if self._recorder is None:
            self._set_status("error", "Mic unavailable")
            self.status_message.emit("Voice input unavailable: Qt multimedia backend missing.")
            return
        if not self._is_recording:
            fd, path = tempfile.mkstemp(prefix="spritestack_voice_", suffix=".wav")
            os.close(fd)
            self._record_path = path
            self._awaiting_transcribe = False
            self._recorder.setOutputLocation(QUrl.fromLocalFile(path))
            self._recorder.record()
            self._is_recording = True
            self.mic_btn.setText("■ Stop")
            self._set_status("recording")
            self.status_message.emit("Recording... click again to stop.")
        else:
            self._awaiting_transcribe = True
            self._recorder.stop()
            self._is_recording = False
            self.mic_btn.setText("🎙 Record")
            self._set_status("transcribing")

    def _on_recorder_state_changed(self, state):
        if QMediaRecorder is None:
            return
        if state == QMediaRecorder.StoppedState and self._awaiting_transcribe:
            self._awaiting_transcribe = False
            QTimer.singleShot(50, self._send_transcribe_request)

    def _send_transcribe_request(self):
        path = self._record_path
        if not path or not os.path.exists(path):
            self.status_message.emit("No recorded audio found.")
            return
        req = QNetworkRequest(QUrl(f"{self._api_base}/transcribe"))
        multi = QHttpMultiPart(QHttpMultiPart.FormDataType)
        file_part = QHttpPart()
        file_part.setHeader(
            QNetworkRequest.ContentDispositionHeader,
            'form-data; name="file"; filename="prompt.wav"',
        )
        file_part.setHeader(QNetworkRequest.ContentTypeHeader, "audio/wav")
        audio_file = QFile(path)
        if not audio_file.open(QIODevice.ReadOnly):
            self.status_message.emit("Could not open recorded audio file.")
            return
        audio_file.setParent(multi)
        file_part.setBodyDevice(audio_file)
        multi.append(file_part)
        reply = self._network.post(req, multi)
        multi.setParent(reply)
        reply.finished.connect(lambda r=reply, p=path: self._on_transcribe_finished(r, p))
        self._set_status("transcribing")
        self.status_message.emit("Transcribing voice input...")

    def _on_transcribe_finished(self, reply, record_path: str):
        try:
            if reply.error():
                self._set_status("error", "Transcription failed")
                self.status_message.emit(f"Transcription failed: {reply.errorString()}")
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            text = ""
            if isinstance(payload, dict):
                text = (
                    str(payload.get("text") or payload.get("transcript") or payload.get("prompt") or "")
                    .strip()
                )
            if not text:
                self._set_status("error", "No transcript")
                self.status_message.emit("Transcription returned empty text.")
                return
            self.prompt_edit.setText(text)
            self.prompt_edit.setFocus()
            self.prompt_edit.setCursorPosition(len(text))
            self._set_status("ready", "Transcript ready")
            self.status_message.emit("Transcript ready — edit it, then press Parse Scene.")
        except Exception as exc:
            self._set_status("error", "Transcription failed")
            self.status_message.emit(f"Transcription decode error: {exc}")
        finally:
            reply.deleteLater()
            try:
                if record_path and os.path.exists(record_path):
                    os.remove(record_path)
            except OSError:
                pass
            self._record_path = None
