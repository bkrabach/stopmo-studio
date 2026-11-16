"""How steady is a run of exposures?   .venv/bin/python tools/measure_jitter.py FRAMES_DIR [first last]

Per pair of consecutive exposures:
  shift       whole-frame translation in pixels (phase correlation): camera shake
  brightness  change of mean brightness in percent: light flicker
  still_diff  mean absolute difference (0-255) over the 60% of 32-px blocks that changed least,
              after removing the shift and brightness change: shimmer on things that are not moving
Prints medians and 90th percentiles; lower is steadier.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L").resize((960, 540), Image.BILINEAR), dtype=np.float64)


def shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Sub-pixel translation of b relative to a."""
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2((a - a.mean()) * window), np.fft.fft2((b - b.mean()) * window)
    cross = fa * np.conj(fb)
    corr = np.fft.fftshift(np.fft.ifft2(cross / (np.abs(cross) + 1e-9)).real)
    y, x = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(line, i):
        if 0 < i < len(line) - 1:
            l, c, r = line[i - 1], line[i], line[i + 1]
            d = l - 2 * c + r
            return i + (0.5 * (l - r) / d if abs(d) > 1e-12 else 0.0)
        return float(i)

    return refine(corr[:, x], y) - a.shape[0] // 2, refine(corr[y, :], x) - a.shape[1] // 2


def measure(frames_dir: Path, first: int | None = None, last: int | None = None) -> dict:
    files = sorted(frames_dir.glob("f_*.png"))
    files = [f for f in files if (first is None or int(f.stem[2:]) >= first) and (last is None or int(f.stem[2:]) <= last)]
    images = [load(f) for f in files]
    shifts, bright, still = [], [], []
    for a, b in zip(images, images[1:]):
        dy, dx = shift(a, b)
        shifts.append(float(np.hypot(dy, dx)) * 2)  # measured at half size: report 1080p pixels
        bright.append(abs(b.mean() / a.mean() - 1) * 100)
        diff = np.abs(b * (a.mean() / b.mean()) - a)
        blocks = diff[:512, :960].reshape(16, 32, 30, 32).mean(axis=(1, 3)).ravel()
        still.append(float(np.sort(blocks)[: int(len(blocks) * 0.6)].mean()))
    stat = lambda v: (round(float(np.median(v)), 3), round(float(np.percentile(v, 90)), 3))  # noqa: E731
    return {"exposures": len(images), "shift_px": stat(shifts), "brightness_pct": stat(bright), "still_diff": stat(still)}


if __name__ == "__main__":
    args = sys.argv[1:]
    result = measure(Path(args[0]), *(int(a) for a in args[1:3]))
    print(f"{args[0]}: {result['exposures']} exposures | shift px (median, p90) {result['shift_px']} | "
          f"brightness % {result['brightness_pct']} | still-area diff {result['still_diff']}")
