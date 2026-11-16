# Stopmo Studio

**Small films. Handmade character. A production pipeline an agent can actually operate.**

Stopmo Studio turns an editable script into a stop-motion-style short film: miniature sets, expressive puppets, stepped animation, local voices, procedural music and sound, and a finished MP4. You act as the producer; your coding agent handles the production work.

This is not a text-to-video service. It builds real scenes in Blender, animates them one exposure at a time, and assembles the result with Python and FFmpeg. Characters, cameras, lighting, timing and sound remain things you can inspect and change—not just another prompt to reroll.

**v0.1 is a source-only research prototype.** Expect hands-on iteration, not one-click studio quality. macOS with Blender 5.3 is the development baseline; other environments need their own smoke test.

## What you can make

- **Character-led explainers and promos:** a small cast, a clear idea, a memorable visual beat.
- **Miniature stories:** clay, felt or toy-like worlds with reusable props and sets.
- **Iterative animation experiments:** compare looks, audition voices, revise a shot, or remix without rerendering everything.

The toolkit includes procedural character builders, material/style packs, staging actions, cameras and lighting, voice/lip-sync integrations, sound synthesis, typography overlays, caching and render checks. No previous films, production scripts, reference art, custom character likenesses, audio samples, fonts or model weights are bundled.

## Start as the producer

Give your agent this repository and a brief like:

> Read AGENTS.md and get Stopmo Studio running. Make a playful 15-second film about a tiny gardener discovering an enormous seed. It is for a general audience, in a warm felt style, with no speech. Propose a simple story and show me one representative frame before the full render. Keep paid services off; measure local render time. Do not publish anything.

You decide **purpose, audience, duration, art direction, voice rights, budget and publication**. The agent should handle authorized installation, scripting, modelling, tests, rendering, checking and revisions without asking you about every technical step.

See the [agent production guide](AGENTS.md) for that working agreement and the full workflow.

## Install from a checkout

Prerequisites: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and [Blender 5.0+](https://www.blender.org/download/). Start with Python 3.13 in a dedicated environment. Put `blender` on `PATH` or set `BLENDER` to its executable; see the installation guide for configuration.

```sh
git clone https://github.com/bkrabach/stopmo-studio.git
cd stopmo-studio
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/stopmo --help
.venv/bin/stopmo doctor
.venv/bin/python -m pytest
.venv/bin/stopmo init shows/first-film
.venv/bin/stopmo build shows/first-film hello --quality draft --jobs 1
```

The original starter creates a two-second toy scene with synthesized music and sound, but no dialogue. Its MP4 is written to `out/first-film/hello/draft/hello.mp4`. `init` refuses existing targets rather than overwriting them.

Use the **editable checkout**, not a standalone wheel: runtime tools, styles and optional local assets live alongside the Python source. Voice tools are optional; a no-dialogue first film avoids model downloads and voice-license decisions.

Follow [Installation](docs/installation.md) for preflight, an original starter project, optional speech tools and a first render.

## How it makes the look

1. **Script the performance.** YAML describes a show, its cast, shots and timed actions. Speech is recorded first so animation follows the actual take.
2. **Build a miniature world.** Python constructs puppets, props, materials, sets, cameras and lights in Blender.
3. **Photograph discrete poses.** The director bakes an exposure-based performance, with replacement mouths/eyes and controlled surface variation. A typical style uses 12 exposures per second, encoded at 24 fps without inventing in-between motion.
4. **Finish the film.** Typography, grading, generated effects and music, dialogue mixing and encoding produce an MP4. Cached shots make revisions cheaper.
5. **Check, then approve.** Numeric checks and fresh-render comparisons support—not replace—watching and listening to the result.

## Honest boundaries

- Characters are procedural archetypes or custom code, not automatic reconstructions of an image. Rigid figures cannot perform every articulated-puppet action.
- There is no automatic collision avoidance, natural-language directing service or guarantee that an emotion reads correctly. Good results come from a clear brief and short review loops.
- The pipeline runs locally and has no built-in paid generation API or output-upload step. Installation and first-use model downloads still need network access. An agent or external vision reviewer can have separate costs and data policies.
- The build ledger records pipeline time and cache activity. Its zero API-spend field **does not mean the agent's work was free**. See [Verification and costs](docs/verification.md).
- Code licensing does not clear voices, likenesses, fonts, brands or music you bring to a production. Optional voice models have different terms; some are unsuitable for commercial work.

## Go deeper

| Guide | What it covers |
|---|---|
| [AGENTS.md](AGENTS.md) | Producer handoffs, autonomous work, production stages and delivery |
| [Installation](docs/installation.md) | Dependencies, platform limits and a first smoke test |
| [Authoring](docs/authoring.md) | Project layout, commands, character types, typography and cache rules |
| [Staging](docs/staging.md) · [Props and sets](docs/props.md) | Animation vocabulary and procedural building blocks |
| [Verification and costs](docs/verification.md) | Render repair, visual/audio review and honest accounting |
| [Security and privacy](docs/security.md) | Trusted code, private production data and safe sharing |

## License

Stopmo Studio's original code and documentation are [MIT licensed](LICENSE). External software and optional models retain their own licenses: read [THIRD_PARTY.md](THIRD_PARTY.md) before installing or publishing with them. No affiliation or endorsement by those projects is implied.
