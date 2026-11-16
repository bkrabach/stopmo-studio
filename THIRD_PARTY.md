# Third-party software, models and assets

The [MIT license](LICENSE) covers Stopmo Studio's original code and documentation. It does not relicense external applications, libraries, model weights, fonts, recordings or other assets. This source release does not bundle Blender, voice weights, sample media, custom likenesses or fonts.

This is a practical dependency/rights guide, **not a complete software bill of materials or legal clearance for a film**. Check the exact versions and all applicable license/NOTICE files before distributing dependencies, shipping an application or publishing content. Transitive dependencies and binary build options can add obligations.

## Rendering, runtime and development tools

| Component | Role | License/source to review |
|---|---|---|
| [Blender](https://www.blender.org/about/license/) | Geometry, animation and rendering | GPL; consult Blender's guidance for use, add-ons and distribution. Its license does not by itself put ordinary rendered artwork under GPL. |
| [FFmpeg](https://ffmpeg.org/legal.html) | Encoding, resampling, loudness measurement and mixing filters | LGPL/GPL depends on the actual build and enabled components. Codec/patent questions are separate from this toolkit's MIT license. |
| [Python](https://docs.python.org/3/license.html) | Host runtime | Python license and included third-party notices |
| [uv](https://github.com/astral-sh/uv) | Environment/package management | MIT or Apache-2.0; inspect the installed release |
| [Click](https://github.com/pallets/click) | CLI | BSD-3-Clause |
| [PyYAML](https://github.com/yaml/pyyaml) | Configuration | MIT |
| [NumPy](https://numpy.org/doc/stable/license.html) | Numeric work and synthesis | BSD-3-Clause, plus bundled-library notices where applicable |
| [Pillow](https://github.com/python-pillow/Pillow) | Image processing and typography | MIT-CMU and its bundled-library notices |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | Portable FFmpeg executable discovery/fallback | Wrapper BSD-2-Clause; the FFmpeg binary retains its own terms |
| [pytest](https://github.com/pytest-dev/pytest) | Tests | MIT |
| [Hatchling](https://github.com/pypa/hatch) | Package build backend | MIT |

The repository does not redistribute a preassembled runtime. If you create one, collect the exact installed licenses, required notices and source offers where applicable. Do not assume a permissively licensed Python wrapper changes a bundled executable's license.

## Optional speech and lip-sync infrastructure

| Component | Role | License/source to review |
|---|---|---|
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Local CPU TTS wrapper and ONNX distribution | MIT wrapper; review model, voice data and runtime dependencies separately |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Kokoro inference | MIT, with third-party notices |
| [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) | Mouth-cue extraction | MIT project; bundled recognition libraries have their own notices |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Local speech recognition | MIT implementation; retain upstream notices |
| [Whisper](https://github.com/openai/whisper) · [converted weights](https://huggingface.co/ggerganov/whisper.cpp) | Recognition model | Review original model license and conversion metadata; upstream Whisper releases code and weights under MIT |
| [MLX](https://github.com/ml-explore/mlx) · [mlx-audio](https://github.com/Blaizzy/mlx-audio) | Optional Apple Silicon acting environment | MIT libraries; model weights are not covered by those library licenses |
| [PyTorch](https://github.com/pytorch/pytorch) | Optional acting dependencies | BSD-style license plus third-party notices |
| [SoundFile](https://github.com/bastibe/python-soundfile) · [libsndfile](https://libsndfile.github.io/libsndfile/) | Audio I/O | SoundFile BSD-3-Clause; libsndfile has separate LGPL terms |

Phonemizers, language packages, tokenizers and model dependencies can bring additional licenses. For example, eSpeak NG uses GPL terms; inspect the actual environment rather than assuming every TTS dependency is MIT. Installing a wrapper alone is not a redistribution or output-rights audit.

## Voice models: choose deliberately

These identifiers match the integrations in `src/stopmo_voice/engines.py` or the Kokoro installer. The notes below reflect the linked upstream declarations, not a promise that every use is allowed. Model terms and aliases can change; save the exact model revision and license used with the production.

| Integration | Model and upstream sources | Decision to make before use |
|---|---|---|
| Kokoro | [Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M/raw/main/README.md); [ONNX release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1) | Model card declares Apache-2.0. Review voice/model provenance and notices, and obtain rights for any reference recordings. |
| `dramabox` | [MLX conversion card](https://huggingface.co/mlx-community/ResembleAI-Dramabox/raw/main/README.md); [original license](https://huggingface.co/ResembleAI/Dramabox/raw/main/LICENSE) | LTX-2 Community terms, not MIT/Apache. The linked license requires a paid license for entities with annual revenue **at least US$10 million**, with affiliates aggregated as defined there. Other use/distribution restrictions also apply. |
| `voxcpm` | [MLX conversion card](https://huggingface.co/mlx-community/VoxCPM2-bf16/raw/main/README.md); [original VoxCPM2](https://huggingface.co/openbmb/VoxCPM2) | Conversion card declares Apache-2.0. Check original and converted artifacts plus reference-voice rights; do not infer consent from a model license. |
| `breeze` | [MLX conversion card](https://huggingface.co/mlx-community/Breeze-TTS-2-mlx-8bit/raw/main/README.md); [original Breeze TTS 2](https://huggingface.co/BreezeBlue/Breeze-TTS-2) | Research/non-commercial terms. The conversion calls itself unofficial and unaffiliated. Do not use it for commercial production without appropriate separate rights. |
| `higgs` | Runtime ID `bosonai/higgs-audio-v3-tts-4b`; [current redirected card](https://huggingface.co/bosonai/higgs-tts-3-4b/raw/main/README.md); [license](https://huggingface.co/bosonai/higgs-tts-3-4b/raw/main/LICENSE) | Research/non-commercial license **with a limited creator-use grant**, including certain monetized creative content with prominent attribution. Hosted services, product integration and other uses outside the grant can require separate commercial permission. Read the full terms for your actual use. |

For Higgs creator content, the linked license describes a prominent acknowledgment of Boson AI's Higgs Audio in the audio or accompanying text. It also imposes consent, disclosure and use restrictions. Do not shorten this to either “commercial use is always forbidden” or “all commercial use is free.”

The optional installer requires an explicit acknowledgment for the acting environment. That flag is not a license, a waiver or authority for an agent to accept terms on someone else's behalf. Trying additional engines can download large models. Never choose a different engine as a silent licensing workaround.

## Fonts, likenesses, music and publication

- **Fonts:** none are bundled. Keep the exact font license with a production and check embedding/redistribution rights before shipping editable files.
- **Voices and likenesses:** obtain consent and rights for reference recordings, identifiable people and characters. Model access does not grant those rights.
- **Music and effects:** the built-in synthesis code is part of this toolkit. No recorded music or sound samples are included. Imported material requires its own clearance; procedural generation alone is not a guarantee of exclusive copyright or non-infringement.
- **Brands and claims:** the producer is responsible for authorized logos/names, accurate claims and any required disclosure that content is synthetic.
- **Distribution:** keep required notices with redistributed software/assets, and provide content credits when the applicable license requires them. Public code availability does not authorize public sharing of a private production.

For a rights-sensitive or commercial release, have the responsible person review the exact production manifest and upstream terms. The toolkit makes no blanket commercial-clearance claim.
