# Installation and first run

**Start with the base renderer and a two-second, no-dialogue smoke project.** Install voice models only after that path works.

This is a source-checkout workflow. Runtime code resolves sibling `styles/`, `tools/`, optional `models/` and `vendor/` directories. A standalone wheel is not a supported deployment artifact for v0.1.

## Requirements and platform scope

| Component | Requirement |
|---|---|
| Git and a shell | Clone the repository and run its Bash wrapper/tools |
| uv | Manage the local environment and Python downloads |
| Host Python | 3.11+ declared; use 3.13 for the base environment in this guide |
| Blender | 5.0+ required by preflight; 5.3 on macOS is the development baseline |
| FFmpeg | H.264 (`libx264`), AAC and PCM encoders; `imageio-ffmpeg` is a core dependency providing a fallback binary |
| Storage/compute | Space for a virtual environment and rendered PNG sequences; measure a smoke shot before estimating a film |

The renderer attempts Metal acceleration and has a CPU fallback. No CUDA/OptiX configuration or Windows end-to-end support is promised. Linux base rendering may work with a suitable Blender and Bash environment, but needs its own validation. The automated voice installer is macOS-only; acting models use MLX and require Apple Silicon.

A version check is not a GPU compatibility test. Dependencies are not fully transitively locked; record the versions that actually worked for a production.

## 1. Install missing prerequisites

An agent should inspect what is already installed and perform authorized, user-scoped setup. Do not install a second package manager merely because this guide names one.

- Install Git through the existing OS/package-manager route.
- Install uv using its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/). Inspect a downloaded installer before executing it; do not blindly pipe remote scripts into a shell.
- Install Blender from [the official downloads](https://www.blender.org/download/) or the user's trusted package manager. Make its actual executable available as `blender` on `PATH`, or set `BLENDER` to that executable—not to an application bundle or a shell command.
- Check for enough free storage before model downloads or a long render. No single storage estimate covers arbitrary film lengths and custom models.

If Homebrew is **already installed and its use is authorized**, a macOS setup route is:

```sh
brew install git uv
brew install --cask blender
```

Do not run those commands when the components are already managed by another installation method. Package installation can trigger OS prompts; the user must handle administrator credentials, security approval and terms that the agent is not authorized to accept.

For a self-contained Blender extraction within the checkout, the environment override has this form (replace it with the real local executable):

```sh
export BLENDER="./vendor/blender/blender"
```

Keep that setting in the current process environment or the user's approved configuration. Do not write personal executable paths into committed source. The wrapper accepts one executable path, not extra command arguments.

## 2. Install the editable source

From the cloned repository root:

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/stopmo --help
.venv/bin/stopmo doctor
.venv/bin/python -m pytest
```

`uv` may download the requested Python if it is not already installed. `imageio-ffmpeg` is included with the base dependencies; a separate system FFmpeg is not mandatory when its supplied binary works. For an approved alternative, `STOPMO_FFMPEG` names the executable.

`stopmo doctor --json` produces a machine-readable report. It checks source resources, Python, Blender version, FFmpeg encoders and optional tool presence. Missing optional voice tools do not block a no-dialogue build. The command does not install packages, download weights, run synthesis or render a scene. Passing it is readiness evidence, not a finished smoke test.

## 3. Create and render an original starter

```sh
.venv/bin/stopmo init shows/first-film
.venv/bin/stopmo info shows/first-film
.venv/bin/stopmo build shows/first-film hello --quality draft --jobs 1 --save-blend
.venv/bin/stopmo report out/first-film/hello/draft/summary.json
```

`init` creates new generic `show.yaml`, `characters/hero.yaml` and `episodes/hello.yaml` files. It refuses an existing target, including an empty directory; choose a new name rather than deleting unrelated work. The starter is designed for two seconds, with a toy hop, synthesized music and an effect, but **no dialogue or model download**. It is generated from code, not copied from an earlier production.

The result should be `out/first-film/hello/draft/hello.mp4`, with per-shot frames, logs and an optional `shot.blend`. Inspect and play the file; confirm the hop, contact, complete frame and audible sound. Read its measured duration rather than reporting two seconds only because the starter intends that length.

The starter writes a project-local `.gitignore` excluding everything in that project. This protects accidental sharing, not confidentiality. Remove or narrow it only after explicitly deciding what project material should be published.

## 4. Add only the speech tools you need

First inspect the installer and its help:

```sh
bash tools/install_voice_tools.sh --help
```

No flags displays help and installs nothing. Components are selected explicitly; the script never silently opts into all models.

| Option | Purpose | Approximate download/storage planning |
|---|---|---|
| `--kokoro` | CPU text-to-speech via ONNX | About 337 MB of model/voice files, plus Python dependencies |
| `--rhubarb` | Phonetic mouth cues | About 83 MB archive / 200 MB extracted; current macOS binary is Intel |
| `--whisper` | Local word recognition/checking | About 574 MB model; allow roughly 2 GB for source, build and model |
| `--acting` | Separate Python 3.12 / MLX environment | Several GB for packages; first use of models can add many GB each, tens of GB across engines |

Estimates are not quotas or promises. Read the selected upstream terms and current download sizes before proceeding. Downloads are separate from running a model successfully.

For authorized basic speech and lip-sync on macOS:

```sh
bash tools/install_voice_tools.sh --kokoro --rhubarb
.venv/bin/stopmo doctor
```

Rhubarb's Intel binary may need Rosetta on Apple Silicon. The user must approve that compatibility layer and any OS security prompt; do not disable quarantine or other protections. Without Rhubarb, an energy-based mouth-motion fallback is available, but it is not accurate phonetic alignment.

For Whisper, the installer requires `curl`, `tar`, CMake and a C/C++ compiler. On macOS, Xcode Command Line Tools provide the compiler; use the system installation flow if absent. With an existing authorized Homebrew setup, `brew install cmake` supplies CMake. Then:

```sh
bash tools/install_voice_tools.sh --whisper
.venv/bin/stopmo doctor
```

The installer builds a CPU-only `whisper.cpp` CLI. Recognition is optional and this integration currently requests English. Missing ASR must be reported as a skipped check, not as proof that speech is correct.

For acting voices, first agree on **the exact engine, voice rights, model terms and storage budget** with the producer. Only after that decision:

```sh
bash tools/install_voice_tools.sh --acting --accept-model-licenses
```

The acknowledgment flag is not a license grant or blanket publishing clearance. The installer prepares packages but does not fetch acting weights; first use can do that. Do not audition every engine by default. Dramabox, VoxCPM2, Breeze and Higgs have different terms; review [THIRD_PARTY.md](../THIRD_PARTY.md), including original and converted model cards.

### Manual tools outside the macOS installer

There is no automated cross-platform voice setup promise. An agent can integrate supported upstream tools without changing the project layout:

- Install the Kokoro wrapper using `uv pip install --python .venv/bin/python -e '.[voice]'`, then obtain the approved ONNX model and voice data from the upstream release named in the installer. The runtime expects `vendor/kokoro/kokoro-v1.0.onnx` and `vendor/kokoro/voices-v1.0.bin`. The Python extra alone does not fetch those files.
- Install a compatible Rhubarb binary and set `STOPMO_RHUBARB` to it, or place `rhubarb` on `PATH`.
- Build/install `whisper.cpp`, obtain an approved model, and set `STOPMO_WHISPER` and `STOPMO_WHISPER_MODEL` to the executable and model. A model without a runnable CLI is insufficient.
- Do not try the MLX acting environment on unsupported hardware; use an approved supported voice or a silent production rather than substituting a service.

After installation, run an actual short audition with `stopmo voices` and review it. Preflight intentionally does not perform inference.

## Troubleshooting boundaries

| Symptom | Next useful check |
|---|---|
| Blender not found | `BLENDER` / `PATH`, executable rather than bundle, required version |
| Missing styles or scripts | Complete source checkout, editable install, unchanged directory layout |
| FFmpeg launches but encode fails | Required encoders, `STOPMO_FFMPEG`, current base dependencies |
| Speech setup passes but synthesis fails | Exact model files/packages, chosen engine, upstream compatibility and local error log |
| Word checks unavailable | Whisper CLI plus model; otherwise disclose the skipped check |
| A render fails or looks inconsistent | Shot log, available memory, one render job, fresh-render check |

Do not install everything as a troubleshooting strategy. Diagnose the failing layer, retain logs locally, and share only a sanitized minimal reproduction. See [Security and privacy](security.md).
