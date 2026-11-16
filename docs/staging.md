# Staging and performance

The director turns a resolved shot plan into exposure-by-exposure animation. Use the host `stopmo build` command for ordinary production; it resolves the cast, style, recorded dialogue and render options before launching Blender.

For a trusted, already-compiled plan:

```sh
tools/bl.sh src/stopmo_bl/director.py out/local-plan.json
```

A plan includes `shot`, resolved `characters` without their YAML `voice` blocks, `style`, `seed` and render options. `frames: "none"` builds and bakes without rendering; a frame list renders only those exposures. These are low-level plan fields, not extra CLI flags.

Distances are metres at miniature scale. +Z is up and the usual camera is on the -Y side; +X is screen-right for that front view, not for every camera. Beat times are seconds rounded to exposures at the style's `fps`. Values are baked per exposure; this is authored animation, not subframe physics.

## Scheduling

Beats run sequentially unless they specify absolute `t: seconds` or `with: true`. `with` starts with the latest non-`with` beat. A series of parallel beats shares that anchor; delays do not accumulate. Absolute `t` takes precedence, then `delay` is added.

```yaml
beats:
  - {who: sprout, do: hop}
  - {sfx: pop, with: true, delay: 0.1, gain: 0.3}
  - {prop: seed_marker, do: show, with: true, delay: 0.25}
  - {wait: 0.6}
```

This fragment assumes a cast member `sprout` and a prop `seed_marker` already exist. Concurrent/absolute actions can extend the shot without advancing the sequential cursor. Camera moves do not block unless `wait_move: true` is present; sound effects are also nonblocking. Shot `lead`, `hold` and speech `line_gap` affect total duration. Speech lines are separated by at least `line_gap` (default 0.25 seconds), even when an authored start would overlap them. Inspect `timing.json` for the actual result.

A target can be a three-number point, set/shot anchor, `"prop.anchor"`, a prop, a character's face or `"camera"`. Move/reach destinations resolve when scheduled; look targets can be followed during baking. There is no automatic occlusion avoidance, collision detection, gravity or prop transfer.

## Cast, character actions and props

```yaml
cast:
  sprout: {at: mark_a, facing: camera}
dress:
  - {add: sign, name: seed_marker, at: [0.16, -0.08, 0], text: GROW, hidden: true}
beats:
  - {who: sprout, do: look, at: seed_marker}
  - {who: sprout, do: nod, times: 1}
  - {prop: seed_marker, do: show}
```

`cast.at` accepts an anchor or coordinates; a third coordinate sets the standing height. `facing` may be a target or degrees. `holding: PROP, side: r` starts with a prop in an articulated character's hand. For new dressing, `heading` is in **radians**; `turn` for an existing dressed prop and beat rotation angles are **degrees**.

### Character vocabulary

| Action | Use and caveat |
|---|---|
| `say: TEXT` | Spoken beat with `who`, optional gesture/emote/look; host records speech first. A named character outside the visible cast is heard off-screen. |
| `wave`, `nod`, `shake`, `hop`, `lean` | Stock performances; a rigid figure cannot independently wave its arms. |
| `walk`, `hop_to` | Travel to an anchor/point. Prefer hops for toy/rigid figures; `hop_to.turn: false` keeps facing during travel. |
| `look`, `face`, `turn`, `spin` | Gaze/head following or body orientation; rigid figures have limited independent controls. |
| `gesture`, `emote`, `pose` | Named performance, expression preset or explicit pose channels. Preset names do not guarantee the intended emotion reads. |
| `reach`, `take`, `put` | Articulated hand choreography. `put.onto` chooses a point/anchor. Check contact in the actual shot. |
| `startle`, `double_take`, `shifty` | Recoil, snap attention or eye darts; not all archetypes can show every component. |
| `slump`, `peer` | Persistent droop or lean until later keys change those channels. |
| `tremble`, `chew`, `sip` | Temporary performances. `sip.time` is the hold in addition to five exposures up and five down. |

Pose channels are listed in `src/stopmo_bl/archetypes/biped.py`. Persistent look-at is additive to head/gaze posing; release it with `at: null`. Temporary actions restore only channels they touch, but competing actions on the same channels still need deliberate scheduling.

Biped expressions include `skeptical`, `deadpan`, `sheepish`, `guilty` and `proud`. Biped `brows.cock` ranges from -1 to 1; positive raises the character's left brow. Mouths and eyelids use scale-swapped replacements, not continuous facial deformation. Test close-ups and transitions, particularly pupil/lid overlap. See [Authoring](authoring.md) for the different toy/figure capabilities and mesh-name contracts.

### Prop vocabulary

| Action | Parameters and behaviour |
|---|---|
| `move` | Optional `to`, `time`, `arc`, `ease`, `roll`. Omit `to` for a hop in place. |
| `turn` | `by` degrees about local `axis` X/Y/Z, default Z; `time` and `ease`. |
| `spin` | `turns` whole turns around a local axis; linear by default. |
| `show` / `hide` | Three-exposure scale-pop / immediate tiny scale; not `hide_render`. |
| `shake` | Seeded movement controlled by `time` and `amount`. |

`part` selects a unique descendant whose final name segment contains the supplied text; missing or ambiguous matches fail. A lever's `arm` is a real hinge and its `handle` anchor follows it. Positive local Y arm rotation moves the knob toward +X.

A move's `arc` adds a parabolic Z offset independently of horizontal easing. `roll` rotates by distance/radius; a ball uses its authored radius, other props infer one from bounds. Supported eases include `linear`, `in`, `out`, `inout`, `snap` and `step`.

Carried props are positioned after their free motion tracks, so a simultaneous `move` does not pull one out of a hand. Rotation and scale can still affect held props. Grip selection prefers `handle`, then `grip`, then `top`, then the root. There is no automatic handoff; release and take must be choreographed.

## Camera and lighting

```yaml
camera: {shot: medium, of: sprout}
beats:
  - {camera: {from: [0.08, -0.7, 0.3], to: [0, 0, 0.12], lens: 55, roll: 3}, move: 0.8, wait_move: true}
```

Use a named set camera, explicit `from`/`to` camera or character framing (`close`, `medium`, `full`). Lens is millimetres; camera roll is degrees around the view axis. Omitted roll returns to zero. A camera-move endpoint alone does not prove that the subject stays framed during the move.

`shake` is a seeded impact layer with quadratic decay; the style's tiny tripod drift is separate. Use both sparingly. Keep facial features and type readable and inspect the moving sequence, not just its endpoints.

Shot-level extra lights accept `name`, `kind: point|spot|area`, `at`, optional `to`, `power`, `color`, `angle` and `size`. Power is watts, spot angle degrees and size metres. Avoid names reserved by the rig (`key`, `fill`, `rim`). Practical prop/set lights can participate in flicker and targeted fades.

- `{lights: RIG, over: SECONDS}` transitions the stage rig and world settings.
- `{light: NAME, power: VALUE, over: SECONDS}` controls a named light; `scale` can instead express a share of its initial power.
- `{lights: flash, time: SECONDS}` is a temporary lightning overlay; it resumes the underlying lighting afterwards.

Inspect `stage.py` for current rig names. Common rigs include `cosy`, `bright`, `moody`, `interrogation`, `storm` and `softbox`. Flash/shake effects can be uncomfortable or inaccessible; agree on their use and provide an appropriate alternative where needed.

## Sets and acting space

`kitchen`, `workshop` and `garden` offer anchors and named camera suggestions. `clutter` ranges from 0 to 1 and seeds make dressing repeatable. Marks are planned to stay clear of default dressing; that is not a collision guarantee for arbitrary new geometry or movement.

`studio` is a plain stage. `cyc` is a seamless floor/backdrop sweep with configurable colour, depth and cove radius; paired with `softbox` and a smooth style it is useful for toy/product shots. Inspect the selected set builder for exact anchors, parameters and lighting names. These built-in choices do not include a finished production-specific room.

[Props and sets](props.md) lists builder dimensions and anchors. Always measure evaluated bounds after changes, keep action readable, and inspect the intended camera view before rendering the whole sequence.

## Validation is production-specific

Use a bake-only plan for scheduling/geometry diagnostics and a short rendered shot for visual acceptance. The included check tools cover selected contracts, not arbitrary productions. They do not prove that a viewer understands a gag, recognizes a prop, or reads a preset as the intended emotion.

This reference deliberately contains no historical production acceptance logs or machine benchmarks. Run fresh checks for the current source and environment; retain evidence under the local production rather than claiming an earlier run validates a new film.
