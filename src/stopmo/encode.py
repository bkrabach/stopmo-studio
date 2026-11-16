"""Frames -> graded video, and muxing with sound. Thin wrappers over ffmpeg."""
from __future__ import annotations

from pathlib import Path

from .audio import _ffmpeg, _run

DEFAULT_GRADE = {"grain": 0.016, "vignette": 0.35, "saturation": 1.08, "contrast": 1.04}


def grade_filter(grade: dict | None) -> str:
    """ffmpeg filter chain for the 'shot on a real camera' finish: grade, vignette, grain."""
    g = {**DEFAULT_GRADE, **(grade or {})}
    parts = [f"eq=saturation={g['saturation']:.3f}:contrast={g['contrast']:.3f}"]
    if g["vignette"] > 0:
        parts.append(f"vignette=angle={0.2 + 0.6 * g['vignette']:.3f}")
    if g["grain"] > 0:
        # temporal noise = fresh grain on every exposure
        parts.append(f"noise=alls={int(round(g['grain'] * 255))}:allf=t")
    return ",".join(parts)


def frames_to_video(frames_dir: Path, out: Path, *, fps: float, first: int = 1, out_fps: int = 24,
                    grade: dict | None = None, crf: int = 22, size: tuple[int, int] | None = None) -> Path:
    """Encode f_00001.png... shot at `fps` exposures/second into H.264 at `out_fps`.

    Each exposure is simply shown for out_fps/fps frames - that held frame is the stop-motion look.
    """
    filters = [grade_filter(grade)]
    if size:
        filters.append(f"scale={size[0]}:{size[1]}:flags=lanczos")
    filters.append(f"fps={out_fps}")
    _run([_ffmpeg(), "-v", "error", "-y", "-framerate", str(fps), "-start_number", str(first),
          "-i", str(Path(frames_dir) / "f_%05d.png"), "-vf", ",".join(filters),
          "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)], timeout=3600)
    return out


def concat(videos: list[Path], out: Path) -> Path:
    listing = out.with_suffix(".txt")
    paths = [str(Path(v).resolve()) for v in videos]
    if not paths or any("\n" in path or "\r" in path for path in paths):
        raise ValueError("concat needs video paths without newline characters")
    # ffconcat quotes are not Python or shell quoting. End the quoted segment,
    # backslash-escape the apostrophe, then reopen; backslashes inside quotes are literal.
    listing.write_text("".join("file '" + path.replace("'", "'\\''") + "'\n" for path in paths))
    try:
        _run([_ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
             timeout=3600)
    finally:
        listing.unlink(missing_ok=True)
    return out


def mux(video: Path, audio: Path, out: Path) -> Path:
    _run([_ffmpeg(), "-v", "error", "-y", "-i", str(video), "-i", str(audio), "-c:v", "copy",
          "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], timeout=3600)
    return out


def probe_duration(video: Path) -> float:
    """Duration in seconds, parsed from ffmpeg's stream report (no ffprobe needed)."""
    import re
    import subprocess

    result = subprocess.run([_ffmpeg(), "-i", str(video)], capture_output=True, text=True)
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not match:
        raise RuntimeError(f"could not read duration of {video}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)
