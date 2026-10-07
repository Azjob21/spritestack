# SpriteStack Studio

A professional sprite stacking and pixel art editor for Windows, featuring **offline AI-assisted tools** powered by a local FastAPI backend.

---

## ✨ Features

### Pixel Art Editor
- Drawing tools (Pencil, Eraser, Fill, Eyedropper, Line, Rectangle, Circle)
- Adjustable brush sizes (1–64px) with symmetry drawing (Mirror X/Y)
- Full layer system — add, remove, duplicate, merge, reorder with opacity & visibility
- Frame-by-frame animation timeline with playback and FPS control
- HSV color picker, hex/RGB input, and preset palettes (DB32, PICO-8, Endesga 32)
- 100-level undo/redo stack

### Sprite Stacking (3D)
- Real-time 3D preview with rotation and tilt
- Primitive stack generation (Cube, Pyramid, Prism, Cylinder)
- Multiple render modes — Stack, Voxel, Billboard
- Auto-rotation, adjustable layer spacing, shadows & outlines
- Import layer strips and texture PNGs for mapping across stack layers

### Export
- PNG, sprite sheets (horizontal / grid), animated GIF, APNG
- 3D rotation sheet & GIF, layer strip for game engines
- OBJ/MTL + atlas export for Blender / Unity

### Project System
- `.sss` project files (ZIP-based: JSON metadata + PNG layers)
- Preserves all layers, frames, visibility, opacity, and settings

---

## 🤖 AI Features (Offline, Local)

All AI capabilities run **entirely offline** via a local **FastAPI** server (`api/server.py`) on `http://127.0.0.1:8000`. No cloud services, no API keys — everything is processed on your machine.

### AI Scene Construction — `/parse-scene`
Natural-language scene layout via text or voice. Describe your scene (e.g. *"tree on left, rock on right"*) and the AI parses it into normalized object placements with position, scale, rotation, and type. The app renders the scene layout automatically.

### Voice Prompt Input — `/transcribe`
Record a voice prompt via the built-in microphone capture. The audio is transcribed locally using **Whisper** and the resulting text is automatically fed into the scene construction pipeline.

### AI Sprite Generation — `/generate-sprite`
Prompt-to-pixel-art generation. Describe a sprite (e.g. *"small slime enemy"*) and the AI generates a pixel art image that is inserted as a new canvas layer. Uses a fine-tuned **Stable Diffusion** model (pixel art LoRA checkpoint).

### Keyframe Prediction — `/tween-frames`
Intermediate frame generation between two keyframes. The AI predicts in-between animation frames with a confidence score. If confidence is below the threshold (0.65), the system falls back to linear interpolation — ensuring animation quality is always maintained.

### AI Chat Panel
Context-aware assistant for sprite and scene editing guidance, accessible from a dedicated side panel.

> **How it works under the hood**: The app's `app/` source code handles all UI rendering and AI response decoding. The `api/plugins/` directory contains both `fake_*` fallback handlers (for testing without models) and `real_*` handlers that invoke actual model inference. The `api/server.py` orchestrates routing and model loading.

---

## 🧠 AI Models — Separate Repositories

**The AI model weights, training pipelines, and model-specific configurations are NOT included in this repository.** They are maintained in dedicated repos:

| Component | Description | Repository |
|-----------|-------------|------------|
| **Pixel Art Diffusion** | Stable Diffusion checkpoint + LoRA for pixel art generation | *Separate repo (TBD)* |
| **NLP Scene Parser** | Text-to-scene placement model | *Separate repo (TBD)* |
| **Whisper (Speech-to-Text)** | Local Whisper model for voice transcription | *Separate repo (TBD)* |
| **Sprite Tweener** | Frame interpolation model for keyframe prediction | *Separate repo (TBD)* |

To set up the AI backend with real models, clone the relevant model repos and place the weights under `api/models/`. See the model repos' README files for setup instructions.

> **Without the models**, SpriteStack Studio still runs fully — the API server uses `fake_*` plugin handlers that return procedurally generated placeholder responses, so you can develop and test the UI pipeline end-to-end.

---

## 🚀 Getting Started

### Requirements
- Python 3.8+
- Windows 10/11

### Installation

```bash
# Install app dependencies
pip install -r requirements.txt

# Run the editor
python main.py
```

### Running the AI Backend (Optional)

```bash
cd api
pip install -r requirements.txt
python server.py
```

The server starts on `http://127.0.0.1:8000`. The app auto-connects when the server is available.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `B` | Pencil |
| `E` | Eraser |
| `G` | Fill Bucket |
| `I` | Eyedropper |
| `L` | Line |
| `R` | Rectangle |
| `C` | Circle |
| `S` | Select |
| `Ctrl+Z/Y` | Undo / Redo |
| `Ctrl+N/O/S` | New / Open / Save |
| `Ctrl+E` | Export |
| `Ctrl+Shift+N` | New Layer |
| `F5/F6/F7` | Add / Duplicate / Delete Frame |
| `Space` | Play/Pause Animation |
| `Ctrl+G` | Toggle Grid |
| `Scroll` | Zoom |
| `Middle Drag` | Pan |

---

## 📁 Project Structure

```
spritestack/
├── main.py              # App entry point
├── requirements.txt     # App dependencies
├── build.py             # PyInstaller build + shortcut tool
├── sprites_stack.ico    # App icon
├── app/                 # All application source code
│   ├── main_window.py   # Main window, menus, AI response handling
│   ├── canvas.py        # Pixel art canvas widget
│   ├── tools.py         # Drawing tools
│   ├── layers.py        # Layer management
│   ├── timeline.py      # Animation timeline
│   ├── palette.py       # Color palette & picker
│   ├── preview3d.py     # 3D sprite stack preview (OpenGL)
│   ├── stack3d.py       # Stack rendering logic
│   ├── export.py        # All export formats
│   ├── project.py       # .sss project save/load
│   ├── theme.py         # UI theme & dark stylesheet
│   ├── scene_model.py   # AI scene layout model & normalization
│   ├── scene_ui.py      # AI scene panel UI
│   ├── sandbox_stage.py # Scene sandbox / stage renderer
│   ├── ai_chat_panel.py # AI chat assistant panel
│   ├── ai_gen_panel.py  # AI sprite generation panel
│   └── ai_prompt_guide.txt / ai_tag_presets.json
└── api/                 # Local FastAPI AI backend
    ├── server.py        # API server (routes, model loading)
    ├── inference.py      # Inference utilities
    ├── convert.py        # Model conversion helpers
    ├── requirements.txt  # API-specific dependencies
    ├── plugins/          # Endpoint handlers
    │   ├── fake_*.py     # Placeholder handlers (no models needed)
    │   └── real_*.py     # Real model inference handlers
    └── models/           # ⚠️ NOT tracked — see separate repos
```

---

## 📄 License

MIT License
