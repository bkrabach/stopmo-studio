"""The four speech engines that take direction. Each one copies the character's reference clip and
is told how to say the line in its own way.

    engine     takes direction as                              licence of the weights
    dramabox   a screenplay prompt (stage directions)          LTX-2 Community; separate eligibility and use conditions
    voxcpm     a free-text note                                Apache-2.0
    breeze     a free-text note + inline (sigh)/(laugh)        research / non-commercial
    higgs      emotion, pace, style and sound tokens           research / non-commercial

line       {text, seconds, direction?, stage?, emotion?, pace?, event?, style?}
           seconds    time budget for the line when acted (the host estimates it)
           direction  the note a director would give: "Low, slow and suspicious. A long pause after 'Wait'."
           stage      optional full Dramabox prompt, `{who}` is replaced:  {who} sighs, weary but fond, "Oh, hello."
           emotion    Higgs emotion (see HIGGS_EMOTIONS); happy / sad / angry / surprised also work
           pace       slow | medium | fast
           event      a sound before the words: sigh | laugh | cough | sniff
           style      whisper | shout
character  {ref_audio, ref_text, who}   who = how a screenplay introduces the speaker ("An older Englishman")

These model weights have licences separate from this toolkit's code. The table is a guide,
not permission to use or redistribute a model or its output. Read the exact model card and
current licence, including upstream and converted-weight terms, before download or use.
A revenue threshold alone does not establish free commercial-use rights. Obtain consent
and the necessary rights for reference recordings and cloned voices.
"""
from __future__ import annotations

import mlx.core as mx
import numpy as np

HIGGS_EMOTIONS = ("affection amusement anger arousal awe bitterness confusion contemplation contentment determination "
                  "disgust elation enthusiasm fear helplessness longing pride relief sadness shame surprise").split()
_PLAIN_EMOTION = {"happy": "elation", "sad": "sadness", "angry": "anger", "surprised": "surprise"}
_EVENT_WORD = {"sigh": "Haah.", "laugh": "Hehe.", "cough": "Ahem.", "sniff": "Hmf."}  # Higgs wants the sound spelled out
_EVENT_STAGE = {"sigh": "sighs deeply", "laugh": "chuckles", "cough": "clears his throat", "sniff": "sniffs"}
_STYLE_STAGE = {"whisper": "in a hushed whisper", "shout": "shouting"}


def _ref(c: dict) -> dict:
    return {"ref_audio": c["ref_audio"], "ref_text": " ".join(c["ref_text"].split())}


def _note(line: dict) -> str:
    """The direction as one free-text instruction, with style and pace folded in."""
    parts = [line.get("direction", "").strip()]
    if line.get("style"):
        parts.append({"whisper": "Whispered.", "shout": "Shouted."}[line["style"]])
    if line.get("pace") in ("slow", "fast"):
        parts.append(f"Spoken {line['pace']}.")
    return " ".join(p for p in parts if p)


# ---- Dramabox: dialogue in quotes, stage directions outside them ------------------------------------
def _dramabox_tokenizer_fix() -> None:
    """mlx-audio 0.6.5 with transformers 5 unwraps Dramabox's prompt tokenizer one level too far (to the
    raw `tokenizers.Tokenizer`, which has no pad_token). Hand it a wrapper so it stops at the right one."""
    from mlx_audio.tts.models.dramabox import gemma

    if getattr(gemma, "_stopmo_fix", False):
        return
    original = gemma._tokenize

    class Keep:
        def __init__(self, tokenizer):
            self._tokenizer = tokenizer

    gemma._tokenize = lambda tok, text, n: original(Keep(tok) if hasattr(tok, "pad_token") else tok, text, n)
    gemma._stopmo_fix = True


def stage_prompt(line: dict, who: str) -> str:
    """The Dramabox prompt: the line's own `stage`, or one built from direction, event and style."""
    if line.get("stage"):
        return line["stage"].format(who=who)
    note = line.get("direction", "").strip().rstrip(".")
    note = note[0].lower() + note[1:] if note else "naturally"
    lead = f"{who} {_EVENT_STAGE[line['event']]}, then speaks" if line.get("event") else f"{who} speaks"
    if line.get("style"):
        lead += " " + _STYLE_STAGE[line["style"]]
    return f'{lead}, {note}, "{line["text"]}"'


def dramabox(model, line: dict, c: dict, seed: int):
    _dramabox_tokenizer_fix()
    # the model fills the time it is given; with too much it starts reading the stage directions aloud
    return model.generate(text=stage_prompt(line, c.get("who", "A man")), ref_audio=c["ref_audio"],
                          cfg_scale=2.5, stg_scale=1.5, seed=seed, gen_duration=float(line["seconds"]))


# ---- VoxCPM2 and Breeze: reference voice + the note -----------------------------------------------
def voxcpm(model, line: dict, c: dict, seed: int):
    return model.generate(text=line["text"], ref_audio=c["ref_audio"], instruct=_note(line) or None, cfg_value=2.0)


def breeze(model, line: dict, c: dict, seed: int):
    event = {"sigh": "(sigh) ", "laugh": "(laugh) ", "cough": "(clears throat) ", "sniff": ""}.get(line.get("event"), "")
    return model.generate(text=event + line["text"], instruct=_note(line) or None, cfg_scale=4, voice="S0", seed=seed, **_ref(c))


# ---- Higgs Audio v3: reference voice + control tokens ----------------------------------------------
def higgs_prompt(line: dict) -> str:
    emotion = _PLAIN_EMOTION.get(line.get("emotion"), line.get("emotion"))
    if emotion and emotion not in HIGGS_EMOTIONS:
        raise ValueError(f"unknown emotion {emotion!r}; use one of {', '.join(HIGGS_EMOTIONS)}")
    tokens = (f"<|emotion:{emotion}|>" if emotion else "") + "<|prosody:expressive_high|>"
    tokens += {"slow": "<|prosody:speed_slow|>", "fast": "<|prosody:speed_fast|>"}.get(line.get("pace"), "")
    tokens += {"whisper": "<|style:whispering|>", "shout": "<|style:shouting|>"}.get(line.get("style"), "")
    if line.get("event"):
        sfx = "laughter" if line["event"] == "laugh" else line["event"]
        tokens += f"<|sfx:{sfx}|>{_EVENT_WORD[line['event']]} "
    return tokens + line["text"]


def higgs(model, line: dict, c: dict, seed: int):
    return model.generate(text=higgs_prompt(line), seed=seed, temperature=1.0, **_ref(c))


ENGINES = {
    # name: (model id, function, extra arguments for load_model)
    "dramabox": ("mlx-community/ResembleAI-Dramabox", dramabox, {"lazy": True, "strict": True}),
    "voxcpm": ("mlx-community/VoxCPM2-bf16", voxcpm, {}),
    "breeze": ("mlx-community/Breeze-TTS-2-mlx-8bit", breeze, {}),
    "higgs": ("bosonai/higgs-audio-v3-tts-4b", higgs, {}),
}


def speak(name: str, model, line: dict, character: dict, seed: int) -> tuple[np.ndarray, int]:
    """One take -> (mono float32 audio, sample rate)."""
    mx.random.seed(seed)
    results = list(ENGINES[name][1](model, line, character, seed))
    parts = []
    for result in results:
        a = np.asarray(result.audio, dtype=np.float32)  # MLX is lazy: the audio is computed here
        parts.append(a if a.ndim == 1 else a.mean(axis=1) if a.shape[-1] <= 2 else a.mean(axis=0))
    return np.concatenate(parts), int(results[0].sample_rate)
