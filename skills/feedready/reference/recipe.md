# Recipe reference

A recipe is JSON. Pass `masks`, `board`, `preview` or `apply` a file path, an inline string, or a saved version such as `v3` (`preview` saves each recipe as the next version in `<work_dir>/versions/`).

```json
{
  "label": "B · Warm & soft",
  "note": "keeps the warm room, golden skin, gentle vignette",
  "preset": "instagram",
  "crop": {"aspect": "4:5", "focus": [0.545, 0.335], "focus_at": [0.5, 0.33]},
  "steps": [
    {"name": "warm grade", "look": "warm-golden", "amount": 70},
    {"name": "lift eyes", "why": "puts the light where you're looking",
     "mask": {"type": "radial", "center": [0.555, 0.352], "radius": [0.07, 0.03]},
     "adjust": {"exposure": 0.4}}
  ],
  "vignette": -10
}
```

- `steps` run in order. Each step is applied through its mask, or to the whole image if there is no mask.
- `name` and `why` are plain-language labels shown on the edit cards and map. Write them for the user, not in slider terms.
- `label` and `note` caption the recipe on a `board`.
- Coordinates are normalized to the **original** photo: `[x, y]` with the origin top-left, read from the `inspect` grid.
- Sizes (`radius`, `size`, `soft`, `feather`, `grow`) are fractions of the photo's short side.

## Output

| key | values |
|---|---|
| `preset` | Sets the crop aspect only; the output keeps the crop's full resolution. `instagram` (4:5), `story` (9:16), `linkedin` (1:1; the profile picture is shown as a circle, so keep the face centered and the corners unimportant), `original` (no crop) |
| `crop` | `{"aspect": "4:5", "focus": [x, y], "focus_at": [ax, ay], "scale": 1.0}`: the largest crop of that aspect that places `focus` at position `focus_at` inside the frame. `scale` < 1 zooms in. Or use `{"box": [x0, y0, x1, y1]}`. If omitted, the preset's aspect is used, centered. |
| `vignette` | -100…100. Negative darkens the edges. Applied after the crop. |
| `max_edge` | Long edge in pixels, applied after the crop; shrinks only, never enlarges. Omit it to keep full resolution. Set it only after the user agreed to shrink a `large` photo. |
| `quality` | JPEG quality, default 100 (4:4:4 chroma). Leave it unless the user asks for a smaller file. |

## Looks

`"look": "<name>"` on a step expands into a full grade, and `"amount"` (0–200, default 100) scales it the way Lightroom's preset Amount does. Any `adjust` keys in the same step override the look's values, and `hsl` merges band by band. Looks: `natural`, `bright-airy`, `warm-golden`, `moody`, `film`, `cinematic`, `punchy`, `mono`. What each does and when to use it is in `vibes.md`.

## Adjustments (Lightroom JPEG-mode units)

| key | range | notes |
|---|---|---|
| `exposure` | -5…5 | stops, applied in linear light |
| `contrast` | -100…100 | S-curve |
| `highlights` | -100…100 | negative values use a local recovery (Core Image highlight/shadow) |
| `shadows` | -100…100 | local, edge-aware |
| `whites` / `blacks` | -100…100 | moves the top or bottom end of the tone curve |
| `temp` / `tint` | -100…100 | + warmer / + magenta (white balance applied in linear light) |
| `vibrance` / `saturation` | -100…100 | vibrance protects already-saturated colors |
| `texture` | -100…100 | fine local contrast |
| `clarity` | -100…100 | midtone local contrast; negative softens |
| `dehaze` | -100…100 | dark-channel dehaze, applied before the other sliders. Mask it to the scenery. |
| `sharpen` | 0…150 | luminance only |
| `hsl` | `{"blue": {"hue": -10, "sat": -20, "lum": 10}, …}` | bands: red, orange, yellow, green, aqua, blue, purple, magenta; each value -100…100 |
| `curve` | `[[0,0],[0.25,0.22],[0.75,0.8],[1,1]]` | point curve on the photo's encoded values, sRGB or Display P3 (smooth, monotone) |
| `heal` | `true` | removes whatever the step's mask covers and fills it from the surroundings (MI-GAN). Works for spots and whole objects, through any mask (brush, object). Add a small `grow` so the fill covers the edges. Mac only. |

Typical amounts for a post: ±0.3–0.7 exposure on a region, ±20–40 on most sliders, and 10–25 for dehaze and clarity.

## Masks

### Shapes

- `{"type": "radial", "center": [x, y], "radius": r or [rx, ry], "angle": deg, "falloff": 0.5}`: an ellipse, where `falloff` is the soft fraction of the radius.
- `{"type": "linear", "start": [x, y], "end": [x, y]}`: full strength at `start`, fading to 0 at `end`.
- `{"type": "polygon", "points": [[x, y], …], "soft": 0.004}`
- `{"type": "brush", "dots": [[x, y, r], …], "soft": 0.006}`: a dab per dot, for spots and small objects.

### Ranges

Computed on the original photo.

- `{"type": "luminance", "min": 0.6, "max": 1, "soft": 0.08}`
- `{"type": "color", "hue": 210, "range": 25, "soft": 15, "min_sat": 0.08}`: hue in degrees (red 0, orange 30, yellow 60, green 120, aqua 180, blue 240, magenta 300).

### Detected (Mac only)

- `{"type": "person"}`: everyone in the photo (Vision person segmentation).
- `{"type": "subject"}`: the main subject(s), which can be any object (Vision subject lift). `{"type": "background"}` is the inverse.
- `{"type": "face", "part": "face" | "eyes", "index": 0, "scale": 1.0}`: built from Vision face points. Check it on the contact sheet, because covered or profile faces mislead it.
- `{"type": "segment", "class": "mountain"}`, or a list of classes: SegFormer ADE20K. Friendly names: sky, mountain(s), tree(s), vegetation, water, ground, building, rock. Any ADE20K label also works (e.g. grass, sea, sand, road, field, hill). Edges are snapped to the photo; set `"edge_refine": false` to skip that.
- `{"type": "sky"}`: SegFormer sky when the model is available, otherwise a heuristic.
- `{"type": "object", "box": [x0, y0, x1, y1], "points": [[x, y], …], "exclude": [[x, y], …]}`: the object the prompt points at (EdgeTAM), for anything without a dedicated type. Give a `box`, at least one `points` click, or both. `exclude` clicks push look-alike neighbours out. A tight box from the grid works best. `notes` in the `masks` and `apply` output flags a low-confidence result.

### Combine

- `{"op": "union" | "intersect" | "subtract", "masks": [A, B, …]}`. For `subtract`, the first mask has all the others removed from it.

### Modifiers

These work on any mask.

- `"invert": true`
- `"grow": ±0.01`: dilate or erode by that fraction of the short side.
- `"refine": "edges"` (guided snap to edges) or `"grabcut"` (turns a rough polygon or brush into a clean object outline; Mac only).
- `"feather": 0.01`: extra blur.
- `"strength": 0.5`: scales how strongly the step applies through this mask.

## Worked example: a direction refined by notes

This is the session shown in the README's "See it work". The user dropped direction C, so Claude blended B's dusk mood with A's subject lift as v3. Self-review caught the black pants turning muddy brown, so v4 fades the lift down the legs and holds the blacks. The face is covered (`face_readable: false`), so the eye light is a radial read from a zoomed grid, not `type: face`.

```json
{
  "label": "Blue hour, lifted", "note": "B's dusk mood with you lifted out of the shadow",
  "preset": "instagram", "vignette": -15,
  "crop": {"aspect": "4:5", "focus": [0.563, 0.375], "focus_at": [0.5, 0.33]},
  "steps": [
    {"name": "remove the reflective strip", "why": "the white tick on your pants is the brightest thing below your chest",
     "mask": {"type": "brush", "dots": [[0.405, 0.824, 0.012], [0.417, 0.818, 0.012], [0.429, 0.812, 0.012]], "grow": 0.004},
     "adjust": {"heal": true}},
    {"name": "bring back the sky", "why": "10% of the sky was pure white",
     "mask": {"type": "sky"}, "adjust": {"highlights": -50, "whites": -15}},
    {"name": "bite on the snow peaks", "why": "the peaks are the second subject; give them texture",
     "mask": {"op": "subtract", "masks": [
        {"op": "intersect", "masks": [
           {"type": "segment", "class": "mountain"},
           {"type": "linear", "start": [0.5, 0.42], "end": [0.5, 0.62]}]},
        {"type": "person", "grow": 0.01},
        {"type": "sky"}]},
     "adjust": {"clarity": 25, "dehaze": 15}},
    {"name": "tone down the glove logo", "why": "small bright marks on the gloves pull the eye",
     "mask": {"op": "intersect", "masks": [
        {"type": "brush", "dots": [[0.44, 0.675, 0.014], [0.495, 0.71, 0.014], [0.578, 0.692, 0.012]]},
        {"type": "luminance", "min": 0.3, "soft": 0.08}]},
     "adjust": {"exposure": -0.8, "highlights": -50}},
    {"name": "blue hour grade", "why": "cool teal dusk with deeper contrast", "look": "cinematic", "amount": 70},
    {"name": "deepen the sky to dusk blue", "why": "turns the blown white into dusk and frames you from above",
     "mask": {"type": "linear", "start": [0.5, 0.0], "end": [0.5, 0.42]},
     "adjust": {"exposure": -0.45, "temp": -30, "tint": -6}},
    {"name": "darken the valley", "why": "frames you from below and pushes the eye up to you and the peaks",
     "mask": {"op": "subtract", "masks": [
        {"type": "linear", "start": [0.5, 1.0], "end": [0.5, 0.62]},
        {"type": "person", "grow": 0.01}]},
     "adjust": {"exposure": -0.4, "highlights": -20}},
    {"name": "lift you out of the shadow", "why": "shows the jacket; the lift fades down your legs so black pants stay black",
     "mask": {"op": "intersect", "masks": [
        {"type": "person", "grow": -0.002},
        {"type": "linear", "start": [0.5, 0.62], "end": [0.5, 0.9]}]},
     "adjust": {"exposure": 0.5, "shadows": 30, "blacks": -20}},
    {"name": "light the eyes", "why": "the eyes are the only part of the face showing; make them land",
     "mask": {"type": "radial", "center": [0.563, 0.354], "radius": [0.055, 0.026], "falloff": 0.7},
     "adjust": {"exposure": 0.4, "shadows": 20}}
  ]
}
```

Patterns worth copying:
- Fixes that are right whatever the vibe come first: heal, recover the sky, texture on the scenery, tame distractions. Then one `look` step sets the grade, and region steps after it shape the light.
- Gradients do the framing: a linear from the top darkens and cools the sky, and one from the bottom darkens the valley, with `person` subtracted so you aren't darkened.
- Intersecting a mask with a `linear` fades a move across the subject instead of applying it evenly.
- Each `name` and `why` is written for the user, because the edit cards show them.
