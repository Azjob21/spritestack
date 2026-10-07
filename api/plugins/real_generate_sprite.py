"""
Real plugin: /generate-sprite (SPEED OPTIMIZED)
Uses locally downloaded Lykon/dreamshaper-8-lcm (SD 1.5 LCM architecture)
Install: pip install diffusers transformers accelerate torch Pillow
"""
from __future__ import annotations
from pathlib import Path

from PIL import Image

_pipe = None  # loaded once on first call

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "pixel-art-model"
LORA_PATH = Path(__file__).resolve().parents[1] / "models" / "loras"
LORA_FILE = "PixelArtRedmond15V-PixelArt-PIXARFK.safetensors"
PIXEL_ART_PREFIX = (
    "pixel art, 16-bit sprite, pixelated, sharp pixels, "
    "no anti-aliasing, retro game asset, flat colors, "
)

PIXEL_ART_NEGATIVE = (
    "blurry, painting, photorealistic, smooth, soft edges, "
    "watercolor, oil painting, 3d render, antialiased, "
    "high resolution, detailed textures, "
)

def _get_pipe():
    global _pipe
    if _pipe is None:
        from diffusers import StableDiffusionPipeline, LCMScheduler
        import torch
        if not MODEL_PATH.is_dir():
            raise FileNotFoundError(f"Model directory does not exist: {MODEL_PATH}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = torch.float16 if device == "cuda" else torch.float32

        _pipe = StableDiffusionPipeline.from_pretrained(
            str(MODEL_PATH),
            torch_dtype=dtype,
            local_files_only=True,
            feature_extractor=None,
            safety_checker=None,
        ).to(device)

        _pipe.scheduler = LCMScheduler.from_config(_pipe.scheduler.config)

        # Load LoRA from local loras/ folder
        _pipe.load_lora_weights(
            str(LORA_PATH),
            weight_name=LORA_FILE,
        )

        # Fuse LoRA into base weights — removes per-call overhead
        _pipe.fuse_lora(lora_scale=0.9)

    return _pipe

def _pixelate(img: Image.Image, pixel_size: int = 8) -> Image.Image:
    """
    Downscale with NEAREST then upscale with NEAREST.
    Destroys smooth gradients and forces hard pixel boundaries.
    pixel_size=8  → chunky NES-style blocks
    pixel_size=4  → finer, 32-bit style pixels
    """
    w, h = img.size
    small = img.resize((w // pixel_size, h // pixel_size), Image.NEAREST)
    return small.resize((w, h), Image.NEAREST)


def _image_to_hex(img: Image.Image, width: int, height: int) -> str:
    img = img.convert("RGBA")

    # ── Step 1: pixelate at full gen resolution FIRST ──────────────────────
    # This crunches gradients into hard blocks before any resizing or palette
    # reduction happens — giving us genuine pixel art edges, not painted ones.
    img = _pixelate(img, pixel_size=8)

    # ── Step 2: resize down to the requested sprite size ───────────────────
    # Always use NEAREST here — LANCZOS would blur the hard edges we just made.
    if width <= 32:
        # For tiny sprites: step down in halves to avoid aliasing
        img = img.resize((256, 256), Image.NEAREST)
    img = img.resize((width, height), Image.NEAREST)

    # ── Step 3: palette-reduce AFTER pixelation ─────────────────────────────
    # Save alpha first — quantize drops the alpha channel
    alpha = img.split()[3]

    img_rgb = img.convert("RGB")
    # Bump to 32 colors — 16 was too aggressive and killed recognisable shapes
    quantized = img_rgb.quantize(colors=32, method=Image.Quantize.MAXCOVERAGE, dither=0)

    img = quantized.convert("RGBA")
    img.putalpha(alpha)

    pixels = list(img.getdata())
    return "".join(f"{r:02X}{g:02X}{b:02X}{a:02X}" for r, g, b, a in pixels)


async def run(data: dict) -> dict:
    import torch

    prompt: str = (data.get("prompt") or "sprite").strip()
    width:  int = max(1, int(data.get("width")  or 16))
    height: int = max(1, int(data.get("height") or 16))

    GEN_SIZE = 512  # SD 1.5 sweet spot — don't change this

    full_prompt = PIXEL_ART_PREFIX + f"8-bit pixel-art of {prompt}, retro game sprite, solid background, NES style"
    full_negative = PIXEL_ART_NEGATIVE + "smooth gradients, shadow shading"

    pipe = _get_pipe()
    result = pipe(
        full_prompt,
        negative_prompt=full_negative,
        width=GEN_SIZE,
        height=GEN_SIZE,
        num_inference_steps=8,
        guidance_scale=1.8,   # LCM sweet spot — above 2.5 causes mush
        generator=torch.manual_seed(42),
    )
    image = result.images[0]

    hex_str = _image_to_hex(image, width, height)
    return {
        "hex":    hex_str,
        "width":  width,
        "height": height,
        "prompt": prompt,
        "model":  "DreamShaper-8-LCM-Local",
    }