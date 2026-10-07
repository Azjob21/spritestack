# SpriteStack Studio AI API

FastAPI server providing sprite generation, scene parsing, and animation tweening powered by ML models.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Models

Models are not included in the repository due to size. See [MODELS_SETUP.md](./MODELS_SETUP.md) for complete instructions.

Quick setup:
```bash
# Download models (first run)
python setup_models.py
```

### 3. Run the Server

```bash
python server.py
```

Server runs on: **http://localhost:8000**

API docs: **http://localhost:8000/docs** (Swagger UI)

## Project Structure

```
api/
├── server.py                          # Main FastAPI application
├── inference.py                       # NER model inference (SpriteStackParser)
├── plugins/                           # Plugin system for different tasks
│   ├── real_parse_scene.py           # Scene NER parser (real)
│   ├── fake_parse_scene.py           # Scene parser (fallback)
│   ├── real_generate_sprite.py       # Sprite generation (real)
│   ├── fake_generate_sprite.py       # Sprite generation (fallback)
│   └── real_tween_frames.py          # Animation tweening
├── models/                            # Model directories (see MODELS_SETUP.md)
│   ├── pixel-art-model/              # Stable Diffusion-based sprite model
│   └── SpriteStack_Model_Slim_v2/    # DistilBERT NER model
├── tests/                             # API test suite
│   ├── test_api.py
│   └── test_new_endpoints.py
└── requirements.txt                   # Python dependencies
```

## API Endpoints

### Health Check
```
GET /health
```
Returns plugin status and model information.

### Parse Scene (NER)
```
POST /api/parse-scene
Content-Type: application/json

{
  "prompt": "A dungeon with 2 knights on the left and a dragon on the right"
}

Response:
{
  "objects": [
    {"name": "Knight", "type": "sprite", "x": 0.15, "y": 0.5},
    {"name": "Knight", "type": "sprite", "x": 0.18, "y": 0.5},
    {"name": "Dragon", "type": "sprite", "x": 0.85, "y": 0.5}
  ],
  "scene_metadata": {"global_theme": "dungeon", "raw_text": "..."},
  "model": "SpriteStack_NER_v1"
}
```

### Generate Sprite
```
POST /api/generate-sprite
Content-Type: application/json

{
  "prompt": "A red dragon with scales and wings",
  "width": 64,
  "height": 64,
  "seed": 42
}

Response:
{
  "image": "base64_encoded_png_data",
  "seed": 42,
  "model": "pixel-art-model"
}
```

### Tween Frames (Animation)
```
POST /api/tween-frames
Content-Type: application/json

{
  "frame_start": "base64_frame_1",
  "frame_end": "base64_frame_2",
  "num_frames": 4
}

Response:
{
  "frames": ["base64_frame_0", "base64_frame_1", "base64_frame_2", "base64_frame_3"]
}
```

## Plugin System

The API uses a **plugin registry pattern** for graceful fallbacks:

1. **Auto-Detection:** Plugins are auto-detected based on model availability
2. **Real Plugins:** Use actual ML models (if available)
3. **Fake Plugins:** Return deterministic test data (fallback)
4. **Error Handling:** If a real plugin fails, automatically falls back to fake

Example: If `api/models/SpriteStack_Model_Slim_v2/` exists, the NER parser uses the real model. Otherwise, it uses the fake parser.

### Creating a Plugin

```python
# api/plugins/my_plugin.py
from typing import Any

async def run(data: dict) -> dict:
    """
    Process data and return results.
    Raise exceptions for errors — server.py handles fallback.
    """
    result = do_something(data)
    return {"result": result}
```

Register in `server.py`:
```python
PLUGIN_REGISTRY["my-task"] = "plugins.my_plugin"
```

## Testing

Run the test suite:

```bash
pytest tests/ -v
```

Run specific test:
```bash
pytest tests/test_api.py::test_parse_scene -v
```

## Environment Variables

```bash
SPRITESTACK_MODEL_PATH=/custom/path/to/models
LOG_LEVEL=INFO
```

## Troubleshooting

### Models not found

See [MODELS_SETUP.md](./MODELS_SETUP.md) for detailed setup instructions.

### Out of Memory

Models require ~8GB VRAM. For slower CPU-only inference:
```bash
export USE_CPU_ONLY=1
python server.py
```

### Import errors

```bash
pip install transformers torch pyspellchecker
```

## Dependencies

- **FastAPI** — Web framework
- **Pydantic** — Data validation
- **Transformers** — HuggingFace ML models
- **Torch** — Deep learning (CPU/CUDA)
- **Pillow** — Image processing
- **PySpellchecker** — Text preprocessing

See `requirements.txt` for complete list.

## Architecture Notes

- **Plugin Registry Pattern:** Decoupled, easily swappable task handlers
- **Graceful Fallbacks:** Real plugins fail safely → fake plugins return test data
- **Async/Await:** Full async support for long-running model inference
- **Type Safety:** Pydantic models for all endpoints

## Contributing

1. Create plugins in `api/plugins/`
2. Add tests in `api/tests/`
3. Register in `PLUGIN_REGISTRY` in `server.py`
4. Run tests to verify: `pytest tests/ -v`

## License

See root repository LICENSE file.

## Team Integration

This API integrates with the SpriteStack Studio Qt application. The Qt app sends AI requests to these endpoints and renders results in the sandbox.

For full integration guide, see: `docs/AI_INTEGRATION.md`
