# convert.py
from diffusers import StableDiffusionPipeline

pipe = StableDiffusionPipeline.from_single_file(
    "C:/Users/Administrateur/Desktop/spritestack/api/Public-Prompts-Pixel-Model.ckpt",
    torch_dtype="auto",
)
pipe.save_pretrained("./models/pixel-art-model")
print("Done — saved to ./models/pixel-art-model")