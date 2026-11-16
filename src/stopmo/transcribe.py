"""Optional free local whisper.cpp recognition; never prompts with the expected script."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from . import audio


MODELS = ("ggml-large-v3-turbo-q5_0.bin", "ggml-small.en.bin", "ggml-base.en.bin")


def _tools() -> tuple[str | None, Path]:
    cpu = audio._VENDOR / "whisper/cpu/bin/whisper-cli"
    binary = os.environ.get("STOPMO_WHISPER") or (str(cpu) if cpu.is_file() else shutil.which("whisper-cli"))
    folder = audio._VENDOR / "whisper"
    # the biggest installed model wins: base.en mishears short lines ("Four o'clock" -> "for a clock")
    found = [folder / name for name in MODELS if (folder / name).is_file()]
    model = Path(os.environ.get("STOPMO_WHISPER_MODEL") or (found[0] if found else folder / MODELS[0]))
    return binary, model


def available() -> bool:
    """Whether the local CLI and model are installed; runtime failures raise with a remedy."""
    binary, model = _tools()
    return bool(binary and Path(binary).is_file() and os.access(binary, os.X_OK) and model.is_file())


def transcribe(wav: Path) -> dict:
    """Recognize audio on the CPU, returning unprompted text and approximate word times (seconds)."""
    binary, model = _tools()
    if not available():
        raise RuntimeError("Local transcription unavailable. On macOS, run tools/install_voice_tools.sh --whisper, "
                           "or set STOPMO_WHISPER and STOPMO_WHISPER_MODEL to a local CLI and model.")
    with tempfile.TemporaryDirectory(prefix="stopmo-whisper-") as folder:
        source, output = Path(folder) / "speech.wav", Path(folder) / "heard"
        # Whisper expects 16 kHz mono PCM, regardless of the source format.
        audio._run([audio._ffmpeg(), "-v", "error", "-y", "-i", str(wav), "-ar", "16000",
                    "-ac", "1", "-c:a", "pcm_s16le", str(source)])
        try:
            audio._run([str(binary), "--no-gpu", "--threads", "4", "--model", str(model),
                        "--language", "en", "--output-json-full", "--split-on-word", "--max-len", "1",
                        "--output-file", str(output), "--file", str(source)], timeout=300)
            result = json.loads(output.with_suffix(".json").read_text())
        except (RuntimeError, OSError, ValueError) as exc:
            raise RuntimeError(f"whisper.cpp transcription failed: {exc}. Check STOPMO_WHISPER/MODEL or rerun "
                               "tools/install_voice_tools.sh --whisper; synthesis works without transcription.") from exc
    segments = result.get("transcription", [])
    words = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text or text.startswith("[_"):
            continue
        offsets = segment.get("offsets", {})
        start, end = offsets.get("from", 0) / 1000, offsets.get("to", 0) / 1000
        # --split-on-word --max-len 1 normally yields one word per segment.
        # If a CLI release returns a phrase, its word times are approximations.
        pieces = text.split()
        for i, word in enumerate(pieces):
            words.append({"text": word, "start": start + (end - start) * i / len(pieces),
                          "end": start + (end - start) * (i + 1) / len(pieces)})
    return {"text": " ".join(segment.get("text", "").strip() for segment in segments).strip(),
            "words": words}


_SMALL = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
_CONTRACTIONS = {"can't": "can not", "cannot": "can not", "won't": "will not", "shan't": "shall not",
                 "ain't": "is not", "it's": "it is", "that's": "that is", "there's": "there is",
                 "here's": "here is", "what's": "what is", "who's": "who is", "let's": "let us"}


def _integer(n: int) -> str:
    if n < 20:
        return _SMALL[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _SMALL[n % 10] if n % 10 else "")
    for value, name in ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= value:
            return _integer(n // value) + " " + name + (" " + _integer(n % value) if n % value else "")
    return str(n)


def _tokens(text: str) -> list[str]:
    text = text.lower().translate(str.maketrans({"’": "'", "‘": "'", "–": "-", "—": "-"}))
    text = re.sub(r"\bo\s+clock\b", "oclock", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    def numeric(match: re.Match) -> str:
        value = match[0]
        if "." in value:
            whole, decimal = value.split(".")
            return _integer(int(whole)) + " point " + " ".join(_SMALL[int(n)] for n in decimal)
        return _integer(int(value))
    text = re.sub(r"\d+(?:\.\d+)?", numeric, text)
    for contraction, expanded in _CONTRACTIONS.items():
        text = re.sub(r"\b" + re.escape(contraction) + r"\b", expanded, text)
    for suffix, expansion in (("n't", " not"), ("'re", " are"), ("'ve", " have"), ("'ll", " will"),
                              ("'m", " am"), ("'d", " would")):
        text = re.sub(re.escape(suffix) + r"\b", expansion, text)
    # Apostrophes in o'clock and possessives do not alter the spoken token.
    tokens = re.findall(r"[a-z]+", text.replace("'", ""))
    # British/American number readings differ on optional 'and'.
    numbers = set(_SMALL + _TENS + ["hundred", "thousand", "million", "billion", "trillion"])
    return [word for i, word in enumerate(tokens) if not (word == "and" and i > 0 and i + 1 < len(tokens)
            and tokens[i - 1] in {"hundred", "thousand", "million"} and tokens[i + 1] in numbers)]


def compare(script: str, heard: str) -> dict:
    """Ordered word comparison, ignoring case/punctuation and equivalent numbers/contractions.

    Missing/extra tokens are normalized words. Recognition mismatches are flags for
    review, not proof that synthesis is wrong; no phonetic fuzzy matching hides names.
    """
    expected, actual = _tokens(script), _tokens(heard)
    missing, extra = [], []
    for op, a, b, c, d in SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            missing.extend(expected[a:b])
        if op in ("insert", "replace"):
            extra.extend(actual[c:d])
    return {"match": expected == actual, "missing": missing, "extra": extra}
