"""Contact sheet: tools/sheet.py out.png cols img1 img2 ...  (labels = file stems)"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

out, cols, files = sys.argv[1], int(sys.argv[2]), [Path(f) for f in sys.argv[3:]]
imgs = [Image.open(f).convert("RGB") for f in files]
w, h = imgs[0].size
rows = (len(imgs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * h), "black")
draw = ImageDraw.Draw(sheet)
for i, (im, f) in enumerate(zip(imgs, files)):
    x, y = (i % cols) * w, (i // cols) * h
    sheet.paste(im.resize((w, h)), (x, y))
    draw.rectangle((x, y, x + 12 + 9 * len(f.stem), y + 22), fill="black")
    draw.text((x + 6, y + 4), f.stem, fill="white")
sheet.save(out)
print(out, sheet.size)
