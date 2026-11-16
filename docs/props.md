# Procedural props and sets

All dimensions are metres at tabletop scale; a typical biped is 0.25 m tall.
Front is -Y, up is +Z. The built-in builders use procedural geometry and
materials rather than downloaded assets. Custom additions have their own
provenance and rights requirements.

```python
from stopmo_bl import props, sets, stage, style
style.use()
workshop = sets.build_set("workshop", seed=29)
tool = props.build_prop("wrench", "spare_tool", at=(0.1, -0.1, 0),
                        heading=0.2, scale=1.0, seed=5, color="#87969C")
grip_world = props.anchor(tool, "grip")
```

`build_prop(kind, name=None, *, at=(0,0,0), heading=0, scale=1, seed=0,
**params)` returns one Empty owning all pieces and practical lights. Heading is
radians; scale must be positive. `root["anchors"]` stores local XYZ arrays;
`props.anchor(root, name)` transforms to world space (also after parenting).
Every mesh has its `rest` attribute and a material. The entry point removes small
bottom drift before placement; decorative wall-mounted items also stand at z=0
in isolation, then callers raise them to mount height.

## Catalog: furniture and domestic objects

Colors below are hex sRGB. Unless specified, wood is `#987044`, cream is
`#E6D7AF`, teal is `#4D8C88`. Every kind also accepts the common build parameters
above. Listed numbers are nominal design sizes, not exact evaluated AABBs.

| Kind | Parameters (defaults) | Local anchors |
|---|---|---|
| table | width=.19, depth=.12, height=.10, color=wood, top_color=None | top |
| chair | width=.065, seat_height=.060, color=wood, cushion=#B45B3D | seat, back |
| stool | height=.060, radius=.032, color=wood | seat |
| armchair | color=#9F5649, feet=wood | seat |
| shelf | width=.18, depth=.05, color=wood | top |
| cupboard | width=.14, height=.18, depth=.065, color=#849C83, trim=cream | top, handle |
| teapot | color=#B76642, trim=cream | handle, spout, lid |
| mug | color=teal, tea=True | handle, rim |
| plate | radius=.025, color=cream | center |
| biscuit | radius=.012, color=#C78D45, chips=True | center |
| bowl | radius=.024, color=teal | rim, center |
| spoon | color=#A7A7A0 | handle |
| lamp | height=.23, color=#C89B50, shade=cream, lit=True | bulb |
| clock | hour=10, minute=10, radius=.035, color=wood | center |
| picture | width=.075, height=.060, color=wood | center |
| rug | width=.18, depth=.12, color=#A6503E, trim=#D7BA78 | center |
| book | width=.034, depth=.045, height=.009, color=#7C463D | top |
| book_stack | count=4, color=#6A7E83 | top |
| plant | color=#47764A, pot=#AD6546, height=.095 | pot, top |
| bed | width=.14, length=.25, color=wood, blanket=#7C9184 | pillow, mattress |
| window_box | width=.16, color=#9A6647, flowers=#C96D60 | rim, top |

Lamp height scales its whole design. `lit=True` creates a warm point light plus
a glowing bulb; `lit=False` creates neither light nor emissive material. The
physical shade remains open top and bottom. The wall shelf's root is the
bracket bottom, not the board surface. `plant.height` places the upper leaf
centres, so leaves extend above it. Book stacks have count books with seeded
small heading/placement differences. Picture is geometry representing painted
sky/hills/sun, not an external image. Rug fringe extends past depth.

## Catalog: workshop and outdoors

| Kind | Parameters (defaults) | Local anchors |
|---|---|---|
| crate | width=.075, depth=.065, height=.060, color=wood | top, inside |
| ball | radius=.023, color=#B74B36, stripe=cream | center |
| toaster | color=cream, toast=True | lever, top |
| radio | color=#7C4E39, trim=#D5B878 | handle, dial |
| lever | color=#BB5336, metal=#8B9694, angle=-25 (degrees) | handle, pivot |
| gear | radius=.027, teeth=12, color=#B29C64 | hub |
| pipe | color=#89948D, radius=.007 | inlet, outlet |
| tree | height=.40, color=#5B823E, trunk=#795337 | trunk, canopy |
| bush | width=.12, height=.075, color=#527A40 | top |
| flower | height=.07, color=#E0A43E, leaf=#537847 | bloom |
| fence | length=.45, height=.12, color=#DED2AD | center, left, right |
| cloud | width=.14, height=.40, color=#F3F0E5, wire=#92948A, shape=plain | cloud |
| rock | width=.060, color=#85877B | top |
| mushroom | height=.050, color=#AE4936, spots=cream | cap |
| sign | width=.11, height=.19, color=wood, board=cream, text="" | board |

Clouds deliberately reveal their wire support for the practical stop-motion
look. Flower height is the bloom centre (petals extend beyond it). Gear has an
open hub and is built standing upright; it is not a mechanically meshing involute
gear. Pipe is an open swept surface with collars, not a pressure-tight tube.
Lever has a real `arm` child pivoting at its base, owning the shaft and knob.
Positive local Y rotation moves the knob toward +X. Its `handle` anchor is arm-local
and follows the hinge (`props.anchor` resolves this through `anchor_parts` metadata).
Use `{prop: control_handle, part: arm, do: turn, by: 35, axis: y, time: .5}`
after creating a lever named `control_handle`.
Signs have blank boards by default, or fitted text facing -Y when supplied.

## Staging props

| Kind | Parameters (defaults) | Local anchors |
|---|---|---|
| crumbs | count=12, spread=.035, color=#C78D45 | center |
| dog_biscuit | color=#BD864A | center, grip |
| flag | text=MINE, color=#E8DCA9 | grip, top |
| note | text=I.O.U., paw=False, color=#F2E9CB | center |
| kettle | color=#9BA9A1, handle=#373B35 | handle, spout, lid |
| bell | color=#C3A14F | button |
| sugar_cube | size=.009, color=#F5EDD9 | center, top |
| toast | color=#D7AF6E, crust=#8C5129 | grip, top |
| raindrop | color=#8AC6DC, size=.012 | center, tip |
| tea_towel | color=#DED6BC, stripe=#657C86 | top |
| oil_can | color=#AC4934 | handle, spout |
| blueprint | text="", width=.13, height=.085, color=#326887 | center, top |
| block | size=(.05, .03, .04), color=#D9742B, text="", text_color=#373B35, role=default | top, front, grip |
| bridge | length=.11, height=.035, width=.034, color=#3E6753, road=#55595C, line=#F3E7D3 | start, end, top |
| star_map | width=.3, height=.12, size=.009, color=#F0A36B, wire=#B9A88E, stars=five, shape=ball | center |
| plinth | radius=.07, height=.014, color=#E08A4F, top=#FFF4E8 | top, center |
| dome | radius=.062, height=.165, color=#FFFFFF | top, grip |
| monitor | width=.11, color=#F7EEDD, trim=#E08A4F, screen=#5C947F | screen, top |
| phone | height=.085, color=#F7EEDD, screen=#5C947F | screen, top |
| notebook | width=.10, color=#F7EEDD, cover=#E08A4F, tab=#5C947F | page, top |
| link | length=.11, color=#E08A4F, bar=#5C947F | start, end, top |
| machine | width=.10, color=#F7EEDD, trim=#E08A4F, belt=#5C947F | top, slot |
| magnifier | length=.045, color=#5C947F | grip, top |
| wrench | length=.045, color=#9FA7A3 | grip, top |
| clipboard | height=.04, color=#E08A4F, check=#5C947F | grip, top |
| task_card | width=.05, color=#FFF4E8, accent=#E08A4F, done=False, check=#5C947F | top, center, grip |
| star | radius=.018, thickness=.008, color=#F0B45A, stem=0, thread=0, role=default | center, top |
| strand | to=(.1, 0, 0), radius=.0011, color=#F6E7B8, role=glow | start, end |
| desk | width=.22, depth=.10, height=.095, color=#96643A, drawers=right, pull=#C8A45A | front, knee, top |
| office_chair | seat_height=.052, width=.068, color=#3F5E8C, frame=#3A3B3F | back, seat |
| padded_chair | seat_height=.058, width=.066, color=#E0A93B, frame=#987044 | back, seat |
| computer | width=.066, color=#3A3835, screen=#EFE6D6, keys=#DCD7CC, keyboard=True, gap=.045 | keyboard, screen, top |
| bookshelf | width=.16, height=.26, depth=.06, shelves=4, color=#7A4E2D, fill=.8 | center, top |
| desk_lamp | height=.105, reach=.045, color=#3A3B3F, lit=True, light=None, power=.03 | bulb, foot, top |
| wall_lamp | reach=.04, drop=.03, color=#3A3B3F, lit=True, light=None, power=.05 | bulb, plate |
| hanging_plant | drop=.045, trail=.075, color=#4C7A45, pot=#B98C55 | hook, pot |
| corkboard | width=.36, height=.21, frame=.013, color=#C99A64, frame_color=#8A5631 | center, top |
| paper_note | width=.045, height=.045, lines=(), sketch=, color=#F3EADA, ink=#373B35, pin= | center, pin, top |
| sticky_note | size=.022, color=#F0C94A | center, top |
| push_pin | color=#A9B0AC, size=.0045 | grip, head, tip |
| vintage_camera | width=.036, color=#3B2B22, metal=#A9B0AC | grip, lens, top |
| headlamp | width=.03, color=#E3B02F, face=#8D9299, strap=#3A3B3F, lit=False, light=None, power=.01 | grip, lens, top |
| berry_vase | height=.075, color=#EFE9DC, leaf=#4F7A45, berry=#B9382F | rim, top |
| beam | length=.6, thick=.03, color=#6B4326 | center, top |
| snowy_pine | height=.40, color=#3F6247, snow=#EEF2F7, trunk=#5B4030 | top, trunk |
| round_rug | radius=.18, color=#D2B48A, color2=#BFA074 | center |
| round_table | radius=.08, height=.10, color=#A56B3B, legs=4 | top |
| folder | width=.036, height=.048, color=#3D5F9A, pages=#F3EADA | front, grip, top |
| basket_plant | height=.22, color=#4B7C45, basket=#B48A52 | pot, top |
| pencil_cup | height=.02, color=#8A5A3A | rim, top |

Block is a chunky building block with optional lettering on its front; made thin (`size: [0.075, 0.004,
0.048]`, `role: paper`) it is a card a character can carry. Bridge is one span of a toy road bridge along
X; spans placed `length` apart join into one road, and `start` / `end` are the deck ends at rolling
height. Star map is a wall decoration: clay stars joined in order by wire, given as (x, z) pairs from 0 to 1.

Plinth to star are rounded, smooth designer-toy objects suited to the `vinyl`
style. The dome is a thin clear shell (role `glass`), open underneath, that
stands over a figure on a plinth and can be lifted off. Scale hand props to the
character rather than assuming every archetype has the same reach. A task card
shows two lines of abstract writing, or a tick with `done: true`; swap between
two instances with hide and show. A star can stand on a rod (`stem`) or hang
from a thread (`thread`) extending out of frame.

Desk to pencil cup provide office dressing: desks with drawers,
chairs, a computer with keyboard, filled bookcases and corkboards. Paper notes
accept `lines: [[text, size], ...]` for lettering or `sketch: mug | headlamp |
mountains | circles` for a line drawing; `pin` adds a pin at the top.
Desk lamp, wall lamp and headlamp carry a real lamp: `light: NAME` gives the light object that name
so an episode can switch or fade it (`{light: NAME, scale: 0..1}`), `power` is its strength.

Crumbs are seeded irregular biscuit fragments with occasional chocolate flecks;
spread is the scatter-disc radius. The dog biscuit is an unmistakable four-lobed bone.
Flag is a cocktail stick with a paper rectangle. Note lies on a shallow 12-degree
incline toward -Y; `paw: true` adds a pad and four toes below the lettering.
Kettle is a broad conical stove kettle with a black overhead carrying handle and
whistle cap; bell is a brass desk service bell. Sugar has a single cube body and
a combined surface-grain mesh. Toast stands upright, ready to launch from a toaster.
Raindrop is opaque blue sculpted clay, not a fluid simulation.
Tea towel has two thin rumpled cloth layers, coloured stripes and fine hem threads.
Oil can has a pump, long spout and loop handle. Blueprint is a wall-facing paper sheet
with wheel/spoke drawings, dimension arrows, borders and a title block.

Text uses Blender font curves converted to meshes, not downloaded fonts/images.
It is centred and fitted to the available width. Default flag/note text is `MINE`
and `I.O.U.`; sign/blueprint default to blank. Very long text shrinks to fit and
may not be readable in a wide shot; use short wording and a close view.

Cloud `shape` accepts `plain`, `teapot`, `rabbit`, or `storm`. The first three
default to warm white; storm defaults to dark grey, has fused lobes and a genuinely
flat cut bottom (not a rectangular pedestal). Teapot has a spout, open loop handle,
lid and knob; rabbit has a body, head, two long ears and bob tail. The wire remains
intentionally visible. Width controls the silhouette; height sets the wire/cloud
mount height, not the total extent of ears or lid knob.

## Materials and style portability

All prop pieces request materials through `style.active().material(role,color)`.
Changing role recipes re-skins existing builder designs when rebuilt. Shape
irregularity uses the active style's `lumpiness`; random seeds are deterministic.

Import `stopmo_bl.materials.patterns` to register these in `library.RECIPES`:

- `stripes(name, color, color2='#F5E8BE', *, width=.012, axis='X')`: width of
  **one stripe**, metres; X/Y/Z bands.
- `checker(name, color, color2='#F2DFB5', *, size=.025)`: XY square side, metres.
- `grass(name, color='#649247')`: short felt lawn, fine blade bump and broad dye.
- `sky(name, top='#79B9D3', bottom='#E2EACD', *, height=.65)`: matte Z gradient.
- `brick(name, color='#A96548', mortar='#D8C49F', *, width=.045, height=.022)`:
  staggered XZ brick pattern (back-wall mapping).

Patterns use unshifted `rest` coordinates in metres. Default sets use these
patterns where the active style retains its default role recipe. A custom
wall/floor recipe is respected instead, so changing to felt or clay doesn't get
silently overwritten by wallpaper. A style pack can explicitly select a pattern
recipe too. `sky` takes the top color as its second positional argument, matching
`library.make`'s color convention.

## Sets

`sets.build_set(kind, *, seed=0, clutter=.6, **params)` returns `anchors`, `cameras`,
`light_rig`, `props`, and walkable `bounds=((minx,miny),(maxx,maxy))`, plus `shell`
and measured `build_seconds`. It builds practical lights but no camera or stage
rig. Every set is open toward -Y; the garden has a curved three-sided painted
backdrop. Interior floor area is 1.10 × .85 m; garden is 1.22 × 1.00 m.

All sets share `center=(0,-.12,0)`, `mark_a=(-.11,-.12,0)` and
`mark_b=(.11,-.12,0)`. These three floor positions are at least .05 m from every
placed prop's evaluated bounding-box footprint (including elevated prop pieces).
The central strip is intentionally empty for foreground puppet dialogue.
Clutter is validated in 0..1 and is deterministic. Extra kitchen items stay off the
table's front edge. Extra workshop items stay off the bench top at X=-.08..+.34;
the original lever/radio/gear/pipe hero equipment is retained there, so remove or
move those explicitly with dress when a gag needs the whole bench.
Cluttered sets add kitchen cloth/crockery/pictures/crumbs; workshop drawings, oil,
loose hardware and swarf; garden flowers/stones/mushrooms, chair/cup, seedling crate
and a forgotten ball. The garden sign says `MIND THE PEAS` when clutter is enabled.

| Set | Parameters | Additional anchors | Rig |
|---|---|---|---|
| kitchen | seed=0, wall=#A5B395, floor=#A88459 | table_top, seat_a, seat_b, window, door | cosy |
| workshop | seed=0, wall=#A56D51, floor=#786548 | bench_top, lever | cosy |
| garden | seed=0, grass=#668E49, sky=#7AB8D0 | path_start, path_end, sign | bright |

Kitchen includes striped wallpaper, daylight window panel with frame, sill and
curtains, table/chairs, tea service, rug, cupboard/toaster, crockery shelf,
clock, picture, potted plant and floor lamp. Workshop has brick and plank walls,
workbench, radio, gear/pipe shelves, lever machine, crates, stool and a hanging
practical lamp. Garden has felt lawn, path, fence, tree, bushes, flowers, wire
clouds, mushroom, rock and signpost.

Each camera dict contains `from`, `to` and `lens` (mm):

| Camera | Interior from → to | Lens |
|---|---|---|
| wide | (-.09,-1.34,.57) → (0,.06,.17) | 39 |
| two_shot | (0,-.83,.29) → (0,-.09,.15) | 46 |
| close_a | (-.17,-.56,.26) → (-.11,-.12,.19) | 65 |
| close_b | (.17,-.56,.26) → (.11,-.12,.19) | 65 |

Garden wide uses (-.07,-1.55,.63) → (0,.055,.23), lens 39. Other garden cameras
share the interior defaults. Cameras are suggestions, not a locked shot grammar.

`room(*, width=1.10, depth=.85, height=.50, wall='#B6C1A1',
floor='#97724C', wallpaper=None, window=None, door=None, skirting=True,
name='room')` builds a reusable shell. Wallpaper is a stripe-options dict;
window accepts x/width/height/sill, door accepts x/width/height/color. Both are
back-wall openings, built by wall segmentation rather than booleans. Door is a
closed decorative panel, not yet hinged. Do not specify overlapping openings.

## Render, check, extend

```sh
tools/bl.sh tools/check_props.py
```

There is no bundled rendered catalog. To inspect a prop, create a small local
shot with that prop in `dress`, then use `stopmo build --stills` or a complete
short build. See [Staging](staging.md) for placement and animation and
[Authoring](authoring.md) for the command sequence.

To add a prop, write a plain function in `props.py`, decorate with `_register`,
and use the small `_box`, `_cyl`, `_ball`, `_tube`, `_ring`, `_vessel` helpers.
Parent all pieces under its root, set `_anchors`, and work at z=0. The entry
point finishes meshes, adds rest coordinates and places the hierarchy. Nested
`build_prop` roots can be parented to the outer root. Keep materials role-based.

To add a set, write a function returning the same set contract, reuse `room` or
a three-sided custom backdrop, place library props, provide the four camera
suggestions and register in `SETS`. Keep marks .05 m clear of footprints. Add
new required set-specific anchors to `check_props.py`.

The checker covers registered prop/set defaults at selected seeds, including
finite geometry, materials/rest data, bounds, dimensions, anchor transforms,
practical lights, camera metadata and clear marks. Read the current checker and
its results for exact coverage; this document is not a saved test receipt.

## Limits

- These are miniature scene parts, not physics-ready or manufacturing assets.
  Authored motion does not automatically avoid collisions or transfer props.
- Catalog sizes are nominal. Measure evaluated geometry for framing and contact,
  especially after non-default parameters, scale changes or parenting.
- Interior wide cameras may show the edges of the roofless diorama. Other
  cameras intentionally crop peripheral dressing.
- Foliage, food and machinery are simplified. Recognition and emotional tone
  need visual review; numeric checks cannot establish either.
- Extreme parameter combinations, close-up surface quality and full walking
  paths need production-specific checks. No hardware throughput guarantee is
  made.
