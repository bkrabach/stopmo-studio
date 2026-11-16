# Authoring reference

Run commands from the repository root with its editable environment. Paths below are local examples, not bundled productions. Replace project, episode and shot names with those in your own show.

## The three layers

| Layer | Entry points | Responsibility |
|---|---|---|
| Host Python | `src/stopmo/`, `stopmo` CLI | Load YAML, record/cache speech, compile plans, run Blender, composite type, mix and encode |
| Blender Python | `src/stopmo_bl/`, `tools/bl.sh` | Build geometry/materials, schedule and bake exposures, render PNGs and optionally save `.blend` |
| Optional speech environment | `src/stopmo_voice/` | Run approved local acting models in a separate process/environment |

The host Python is not Blender's embedded Python. Run Blender scripts through `tools/bl.sh`, not the ordinary interpreter. Keep the repository's `src/`, `styles/` and `tools/` layout intact; this version is not a self-contained wheel distribution.

## Project layout

```text
shows/garden/
  show.yaml
  characters/
    sprout.yaml
  episodes/
    discovery.yaml
```

A character's file stem is its cast identifier. An episode argument is the file stem without `.yaml`. Use simple unique folder and shot identifiers. Output paths use the **show directory's basename**, so two projects named `garden` share the same default output namespace even if stored in different locations.

A tiny invented show configuration:

```yaml
title: A Small Discovery
style:
  extends: felt
  camera_drift: 0
set: garden
```

A tiny invented character configuration:

```yaml
archetype: toy
height: 0.12
body: '#537B62'
skin: '#F0D6AD'
mouth: {rest: smile}
```

A minimal no-dialogue episode fragment using that character:

```yaml
seed: 17
shots:
  - id: notice
    camera: {shot: full, of: sprout}
    cast:
      sprout: {at: center, facing: camera}
    beats:
      - {who: sprout, do: hop}
      - {wait: 0.5}
```

These are schema illustrations, not a finished story or a promised exact duration. Shot lead/hold and action lengths contribute to the output. Use the generated starter described in [Installation](installation.md) for the first smoke test, then edit it into your own production.

## Command workflow

```sh
# Inspect the project; lineup selects explicitly declared archetypes.
.venv/bin/stopmo info shows/garden
mkdir -p out/lookdev
.venv/bin/stopmo lineup shows/garden out/lookdev/cast.png

# Once approved local speech tools are installed, audition before rendering.
.venv/bin/stopmo voices shows/garden discovery

# Sample a shot. This produces stills, not a video or final text composite.
.venv/bin/stopmo build shows/garden discovery --shot notice \
  --quality draft --stills 12 --jobs 1 --tag framing

# Compare one style parameter; these clips are silent.
.venv/bin/stopmo sweep shows/garden discovery --shot notice \
  --set boil=0,0.15,0.3 --seconds 2 --quality draft --jobs 1

# Render an editable rough cut, then the approved full cut.
.venv/bin/stopmo build shows/garden discovery --quality draft --jobs 1 --save-blend
.venv/bin/stopmo build shows/garden discovery --quality final --jobs 1 --save-blend
```

`build --set KEY=VALUE` applies a dotted override to the loaded **show**, including its style or characters, for that build only. For example, `--set style.grade.grain=0.01`. `sweep --set` instead takes a **style-relative** key and comma-separated alternatives, such as `grade.grain=0,0.01,0.02`. The two forms are not interchangeable.

`--shot` is repeatable. A filtered build assembles only the selected shots; it is not automatically inserted into a previous full episode. `--tag` keeps comparison build directories apart. `--jobs` controls concurrent Blender shots, not the number of animation exposures.

### Outputs and quality

Default build location: `out/<show>/<episode>/<quality>[-TAG]/`.

- `<episode>.mp4`: assembled delivery when all frames were rendered.
- `summary.json`: local pipeline timing, counts, cache hits and sound measurements.
- `<shot>/plan.json`, `timing.json`, `done.json`, `blender.log`: resolved inputs, scheduling evidence, cache marker and diagnostics.
- `<shot>/frames/`: raw rendered exposures; `frames_titled/` holds overlay composites when used.
- `<shot>/shot.blend`: only when `--save-blend` was requested for a render that actually ran.

Current Cycles defaults are draft: 24 samples at 50% resolution; preview: 32 samples at 100%; final: 96 samples at 100%. The base resolution is 1920×1080. Quality changes sampling and dimensions, not story quality. Python callers of `build_episode` can supply `resolution=(width, height)`; the CLI does not expose a `--resolution` flag. Verify your aspect-ratio integration with a short render before promising vertical delivery.

## Character mechanisms and custom figures

The supported archetypes are `biped`, `toy` and `figure`. Biped specifications and semantic pose channels are documented in `src/stopmo_bl/archetypes/biped.py`; toy geometry options are in `toy.py`. Use a toy's `hop_to` performance instead of trying to make its hidden legs read as a walk.

For an original rigid figurine, create a local `models/<package>/<module>.py` and use:

```yaml
archetype: figure
model: garden_props/seedling
height: 0.12
```

The module must provide `build() -> root`, returning an Empty with all model parts beneath it. The flat base should be at Z=0, centred on the origin, facing -Y; +Z is up. Use positive height and sensible miniature dimensions. The importer executes the module; inspect it as code, not an inert asset.

Face discovery is name-based. Supply mesh eyes `eye_l` and `eye_r`, optional `glint*` and `brow*` objects, and a mesh whose name begins `mouth`. A mesh named `head` helps establish the face bounds. The rigid figure adapter adds closed-eye arcs and open-mouth replacements. It does not reconstruct a rig or create independent arm motion.

**Do not guess mesh names from another archetype.** Biped facial objects are character-prefixed; toy eyes include state names and numeric side suffixes such as `NAME_eye_open_1` and `NAME_eye_open_-1`, and its mouths use replacements such as `NAME_mouth_small_smile` rather than a complete set of phoneme-named objects. Inspect the current builder and the scene's actual object list before writing modifiers, checkers or visibility rules. Scale-swapped parts are not reliably identified by `hide_render`.

A saved `.blend` is an inspection artifact, not a project source automatically loaded by subsequent builds. Editing it manually does not update YAML, a model module or the cache hash. Transfer intended changes back to source and rebuild, or document a separate manual finishing workflow.

## Voice configuration

After installing approved Kokoro tools, a character can have:

```yaml
voice:
  kokoro: bm_george
  rate: 1.0
  pitch: 0
```

Add a spoken beat such as `{who: sprout, say: "That seed is enormous!"}`.
`kokoro` selects a voice identifier, not a speech engine named `kokoro`.
An absent acting `engine` chooses the basic Kokoro path. Do not expect
acting direction fields to turn that path into an expressive acting model.

For an approved acting model, `voice.engine` names one of `dramabox`, `voxcpm`,
`breeze` or `higgs`; `ref_audio` and `ref_text` identify a permitted reference
recording and its exact transcript. Relative reference paths are resolved from
the show directory. `who` describes the speaker, and `takes` bounds attempts.
If the named reference file does not exist, the builder tries to synthesize it
with Kokoro—so check that this is the intended reference, rather than assuming
a misspelled path will fail. Explicit acting engines do not silently fall back
when the acting environment is missing.

On a spoken beat, `acting` accepts `direction`, `stage`, `emotion`, `pace`,
`event`, `style`, and an optional engine or take override. For example,
`acting: {direction: "Quietly, with growing curiosity.", pace: slow}`.
The meaning is engine-specific; read `src/stopmo_voice/engines.py` before
relying on a control. Keep the spoken `say` text separate from stage direction.
`event_engine` and `fallback` can switch engines; only configure them when
each engine and its terms have been approved.

Use `stopmo voices` before a full build and listen to the generated audition
page locally. A `--engine` comparison can run additional models and incur
large first-use downloads; it is not just a label filter.

## Text, music and sound

A shot's `overlay` list is composited with Pillow after rendering. Font paths without a leading root are resolved under `assets/fonts/` in the checkout. You must supply the font and its license; none are included. `at` is the ink's top-left corner, `center` is its centre, and `width` is a fraction of the frame width. `size` can instead specify a font size relative to frame height.

```yaml
overlay:
  - text: A small surprise
    font: LocalSans.ttf
    center: [0.5, 0.84]
    width: 0.55
    color: '#FFFFFF'
    pop: [0.2, 0.5]
```

Times are seconds within the shot. `line: 0` makes fade/pop times relative to the first spoken line. Keep layout and animation inside the frame throughout the pop's overshoot. Inspect titled frames or the encoded result, not just raw PNGs. Text meshes on props use Blender's built-in font rather than these overlay font files.

`music` settings on a show are merged with episode settings. Built-in synthesized styles include `brass_band`, `ukulele`, `music_box`, `marimba` and `starlight`; `tempo`, `key`, `seed` and `gain` configure the track. These are procedural arrangements, not a general music-composition model. Changing a seed does not guarantee a substantively new composition.

Sound effects are scheduled as `sfx` beats; `music_off` and `music_on` control musical pauses. Inspect `src/stopmo/sfx.py` for the current effect vocabulary. The mixer currently produces mono audio, with dialogue normalization, ducking, limiting and loudness measurements. Delivery encoding uses H.264 video and AAC audio in MP4; inspect the actual file before reporting its properties.

## Cache and reuse: intentional sharp edges

Speech is cached by text and voice-related settings; rendered shots use a resolved-plan hash plus the Blender-side source hash. A change in `src/stopmo_bl/` can therefore invalidate every shot, not just the one you are fixing.

Do not assume arbitrary external files are hashed. In particular, custom Python figure modules under `models/` are outside the Blender-side source hash; their contents may change while the plan still names the same module. Use `--force` or a new tag after editing custom model code. Music/effect implementation changes may also require targeted cache invalidation. Inspect relevant keys before reusing generated sound.

`--force` forces shot rendering; it is not a universal purge of line/music/effect caches. Preserve or remove only known stale cache entries when needed, within the user's authority.

`--reuse` bypasses the shot-plan freshness comparison and accepts completed renders on disk. It is useful for remixes, grading, typography-only changes and repaired exposures. It is unsafe after changing cast, animation, camera, dialogue duration, frame count or shot order unless you have explicitly reconciled the saved timings.

```sh
# Only after confirming the saved imagery and timing are still the intended ones:
.venv/bin/stopmo build shows/garden discovery --quality final --reuse
```

Do not reuse a sparse `--stills` directory as a complete render. Do not use `--reuse` to conceal a stale cache. `--force` takes precedence when both flags are present. Builds can replace shot directories and assembled outputs; use tags or preserve the previous deliverable before a revision.
