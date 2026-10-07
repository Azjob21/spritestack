from PIL import Image, ImageDraw

# Create a 64x64 icon with transparent background
icon = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)

# Draw stacked rectangles (sprite stack)
colors = [(255, 200, 80), (120, 200, 255), (255, 120, 180), (180, 255, 120)]
for i, color in enumerate(colors):
    offset = 6 * i
    draw.rectangle([8+offset, 8+offset, 56-offset, 32+offset], fill=color, outline=(60,60,60))
    draw.line([8+offset, 32+offset, 56-offset, 32+offset], fill=(60,60,60), width=2)

# Draw a pixel brush tip
brush_color = (80, 80, 80)
draw.ellipse([40, 44, 56, 60], fill=brush_color, outline=(120,120,120))
draw.line([48, 44, 48, 60], fill=(120,120,120), width=2)

icon.save('sprites_stack.ico', format='ICO')
print('Icon generated: sprites_stack.ico')
