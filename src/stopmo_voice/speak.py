"""Speak a batch of lines with one engine:  python -m stopmo_voice.speak jobs.json

jobs.json: {"engine": name, "jobs": [{"out": wav path, "line": {...}, "character": {...}, "seed": int}]}
Writes each wav at the engine's own sample rate (mono, 16-bit) and prints one JSON line per job. The
model is loaded once for the whole batch. Line and character fields are described in engines.py.
Model downloads and use are subject to their own licences, not this toolkit's code licence.
Review the selected model's current terms and obtain rights to reference audio before running.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "vendor" / "acting" / "hf"))


def main(path: str) -> int:
    import soundfile as sf
    from mlx_audio.tts.utils import load_model

    from stopmo_voice.engines import ENGINES, speak

    batch = json.loads(Path(path).read_text())
    name = batch["engine"]
    if name not in ENGINES:
        print(f"unknown engine {name!r}; have {', '.join(ENGINES)}", file=sys.stderr)
        return 2
    todo = [job for job in batch["jobs"] if not Path(job["out"]).is_file()]  # an interrupted batch resumes here
    for job in batch["jobs"]:
        if job not in todo:
            print(json.dumps({"out": job["out"], "seconds": round(sf.info(job["out"]).duration, 2), "generate_seconds": 0.0}), flush=True)
    if not todo:
        return 0
    started = time.time()
    model = load_model(ENGINES[name][0], **ENGINES[name][2])
    print(json.dumps({"loaded": name, "seconds": round(time.time() - started, 1)}), flush=True)
    for job in todo:
        started = time.time()
        audio, rate = speak(name, model, job["line"], job["character"], int(job.get("seed", 1)))
        Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
        part = job["out"] + ".part"  # written whole, then renamed: a killed run never leaves half a take
        sf.write(part, audio, rate, subtype="PCM_16", format="WAV")
        os.replace(part, job["out"])
        print(json.dumps({"out": job["out"], "seconds": round(len(audio) / rate, 2),
                          "generate_seconds": round(time.time() - started, 2)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
