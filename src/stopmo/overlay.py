"""Lettering laid over finished frames, the way a title is added in an edit.

A shot's `overlay:` list holds one entry per line of text:

    {text, font, at: [x, y] | center: [x, y], width, color?, weight?, opacity?,
     fade_in?: [t0, t1], fade_out?: [t0, t1], pop?: [t0, t1], plate?: {color, pad?, radius?, opacity?}}

`at` is the top-left corner of the ink (`center` its middle instead) and `width` its width, all as
fractions of the frame, so a line can be placed by measuring another picture. `pop` makes the line
spring in between its two times (it grows from nothing, overshoots, settles; nothing shows before).
`plate` puts a rounded label behind the ink (pad and radius as shares of the ink's height).
`size` (the font size as a fraction of the frame's height) can be given instead of `width`, so that
several lines share one letter size. `line: N` makes an entry's times count from the start of the
shot's Nth spoken line (0 = the first) instead of from the start of the shot. `font` is a .ttf/.otf path (relative paths are looked
up in assets/fonts); `weight` picks a weight on a variable font. Times are seconds from the start of
the shot: the line fades in between fade_in's two times (quick, then settling) and out between
fade_out's (slow, then quick); without them it is there throughout.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def opacity(item: dict, seconds: float) -> float:
    """How visible a line is at a time, 0..1."""
    value = float(item.get("opacity", 1.0))
    if "fade_in" in item:
        a, b = item["fade_in"]
        t = min(1.0, max(0.0, (seconds - a) / max(b - a, 1e-6)))
        value *= 1 - (1 - t) ** 2
    if "fade_out" in item:
        a, b = item["fade_out"]
        t = min(1.0, max(0.0, (seconds - a) / max(b - a, 1e-6)))
        value *= 1 - t ** 2
    return value


def pop_scale(item: dict, seconds: float) -> float:
    """Size of a line that springs in: 0 before, an overshoot on the way, 1 after."""
    if "pop" not in item:
        return 1.0
    a, b = item["pop"]
    if seconds < a:
        return 0.0
    t = min(1.0, (seconds - a) / max(b - a, 1e-6))
    s = 1.70158 * 1.4
    return 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2


def resolve(items: list[dict], timing: dict) -> list[dict]:
    """Entries with `line: N` get their times shifted to that spoken line's start (from the shot's timing)."""
    out = []
    for item in items:
        item = dict(item)
        if "line" in item:
            start = (timing["audio"][int(item.pop("line"))]["frame"] - 1) / timing["fps"]
            for key in ("fade_in", "fade_out", "pop"):
                if key in item:
                    item[key] = [start + v for v in item[key]]
        out.append(item)
    return out


def _stamp(item: dict, frame_width: int, frame_height: int = 0):
    """The line's ink as an alpha image, sized for a frame of that size."""
    from PIL import Image, ImageDraw, ImageFont

    path = Path(item["font"])
    if not path.is_absolute():
        path = ROOT / "assets" / "fonts" / path
    big = 300
    font = ImageFont.truetype(str(path), big)
    if "weight" in item:
        axes = font.get_variation_axes()
        values = [axis["default"] for axis in axes]
        for i, axis in enumerate(axes):
            name = axis["name"] if isinstance(axis["name"], str) else axis["name"].decode()
            if name.lower().startswith("weight"):
                values[i] = float(item["weight"])
        font.set_variation_by_axes(values)
    text = str(item["text"])
    canvas = Image.new("L", (big * (len(text) + 2), big * 3), 0)
    ImageDraw.Draw(canvas).text((big, big), text, font=font, fill=255)
    ink = canvas.crop(canvas.getbbox())
    if "size" in item:   # font size as a share of the frame height
        k = float(item["size"]) * frame_height / big
        return ink.resize((max(1, round(ink.width * k)), max(1, round(ink.height * k))), Image.LANCZOS)
    width = max(1, round(float(item["width"]) * frame_width))
    return ink.resize((width, max(1, round(ink.height * width / ink.width))), Image.LANCZOS)


def apply(frames_dir: Path, out_dir: Path, items: list[dict], fps: float) -> Path:
    """Copy frames_dir's f_NNNNN.png into out_dir with the lines drawn on. Returns out_dir."""
    from PIL import Image, ImageColor, ImageDraw

    frames_dir, out_dir = Path(frames_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    stamps: dict[tuple, object] = {}
    for frame in sorted(frames_dir.glob("f_*.png")):
        seconds = (int(frame.stem.split("_")[1]) - 1) / fps
        shown = [(item, opacity(item, seconds), pop_scale(item, seconds)) for item in items]
        shown = [(item, value, scale) for item, value, scale in shown if value > 0.003 and scale > 0.02]
        target = out_dir / frame.name
        if not shown:  # untouched: no need to decode and re-encode it
            try:
                os.link(frame, target)
            except OSError:
                shutil.copyfile(frame, target)
            continue
        picture = Image.open(frame).convert("RGB")
        for item, value, scale in shown:
            key = (id(item), picture.width)
            if key not in stamps:
                stamps[key] = _stamp(item, picture.width, picture.height)
            ink = stamps[key]
            if "center" in item:
                cx, cy = item["center"][0] * picture.width, item["center"][1] * picture.height
            else:
                cx, cy = item["at"][0] * picture.width + ink.width / 2, item["at"][1] * picture.height + ink.height / 2
            if scale != 1.0:
                ink = ink.resize((max(1, round(ink.width * scale)), max(1, round(ink.height * scale))), Image.LANCZOS)
            x, y = round(cx - ink.width / 2), round(cy - ink.height / 2)
            plate = item.get("plate")
            if plate:
                pad, radius = plate.get("pad", 0.55) * ink.height, plate.get("radius", 0.9) * ink.height
                box = (round(x - pad * 1.5), round(y - pad), round(x + ink.width + pad * 1.5), round(y + ink.height + pad))
                layer = Image.new("L", picture.size, 0)
                ImageDraw.Draw(layer).rounded_rectangle(box, radius=min(radius, (box[3] - box[1]) / 2), fill=round(255 * value * plate.get("opacity", 1.0)))
                picture.paste(Image.new("RGB", picture.size, ImageColor.getrgb(plate.get("color", "#FFFFFF"))), (0, 0), layer)
            colour = Image.new("RGB", ink.size, ImageColor.getrgb(item.get("color", "#FFFFFF")))
            picture.paste(colour, (x, y), ink.point(lambda v, k=value: int(v * k)))
        picture.save(target)
    return out_dir
