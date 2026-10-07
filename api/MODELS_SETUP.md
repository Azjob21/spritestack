# Model Setup Guide

The SpriteStack API requires several large ML models that are **not included in the repository** to keep it lightweight. Follow these steps to set up the models:

## Required Models

### 1. **Pixel Art Model** (~4.1 GB)
Stable Diffusion-based model for pixel art sprite generation.

**Location:** `api/models/pixel-art-model/`

**Setup Options:**
- **Option A: Manual Download** (if you have the checkpoint)
  ```bash
  # Place your model in: api/models/pixel-art-model/
  # Expected structure:
  # api/models/pixel-art-model/
  # ├── diffusion_pytorch_model.safetensors (3.2 GB)
  # ├── text_encoder/
  # ├── tokenizer/
  # └── vae/
  ```

- **Option B: Using HuggingFace Hub** (requires account)
  ```bash
  python -m pip install huggingface-hub
  huggingface-cli download <model-id> --local-dir ./api/models/pixel-art-model/
  ```

### 2. **SpriteStack NER Model** (~253 MB)
DistilBERT-based Named Entity Recognition model for scene parsing.

**Location:** `api/models/SpriteStack_Model_Slim_v2/`

**Setup:**
```bash
# This model will be automatically downloaded from HuggingFace on first use
# Or pre-download manually:
python -c "from transformers import AutoTokenizer, AutoModelForTokenClassification; \
  model_name = 'distilbert-base-uncased'; \
  AutoTokenizer.from_pretrained(model_name); \
  AutoModelForTokenClassification.from_pretrained(model_name)"
```

### 3. **Pixel-to-Pixel Rasterization (Optional)**
Located in: `api/pixel_rife_rgba_integration_package/`

This is optional for interpolation tasks.

## Verification

After setting up models, verify the API can find them:

```bash
cd api/
python -c "from inference import SpriteStackParser; print('✓ Models loaded successfully')"
```

## Environment Variables (Optional)

Set custom model paths:
```bash
export SPRITESTACK_MODEL_PATH=/path/to/models
```

## Troubleshooting

- **ImportError: No module named 'transformers'**
  ```bash
  pip install transformers torch pyspellchecker
  ```

- **Model not found**
  Ensure the directory structure matches exactly, or re-download from source.

- **Out of Memory**
  The models require ~8GB VRAM. For CPU-only inference, models will run slowly.

## Model Credits

- **Pixel Art Model:** Based on Stable Diffusion (CompVis/Stability AI)
- **SpriteStack NER:** Fine-tuned DistilBERT (HuggingFace)

## Team Setup Script

Run this once to initialize all models:

```bash
#!/bin/bash
cd api/
python setup_models.py
```

(A `setup_models.py` script can be created if needed)
