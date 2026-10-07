---
name: feedready
description: Suggest the best Lightroom/Snapseed-style edits for a photo from measured findings, then apply the ones the user picks (exposure, shadows, clarity, dehaze, colour, crop) including region edits on specific things in the photo (face, eyes, sky, mountains, person, background, small spots), and hand back the final image. Use when the user shares a photo and asks for edit suggestions, says "apply these edits", "make this insta/linkedin ready", "edit this for my profile picture", pastes a numbered edit list to apply, or invokes /feedready.
---

# feedready

You plan the edits; `run.sh` renders them. On a Mac it uses Apple Core Image (adjustments) + Vision (person/subject/face masks) + a 4.4 MB SegFormer model (sky/mountain/water/tree masks) + EdgeTAM (a mask for any object you box or click) + MI-GAN (object removal). Elsewhere (claude.ai) a numpy fallback renders global edits, crops and geometric masks.

Run every command from this skill's base directory: `<base>/run.sh <cmd>` on a Mac, `python3 <base>/scripts/feedready.py <cmd>` on claude.ai. `setup.sh` sits beside `run.sh`. Every command prints JSON.

## 0. Check the tier (first use in a session)
Run `run.sh doctor`.
- `tier: mac` with nothing in `missing`: full feature set.
- `missing` lists something: **ask the user before running `<base>/setup.sh`**, and say what it downloads (Python packages ~90 MB from PyPI; `--segformer` adds the 4.4 MB scene model; `--models` adds the 69 MB object mask and heal models). Compiling the Swift engine downloads nothing. Never download a model or package without a yes.
- `tier: basic` (claude.ai/phone): global sliders, crop/presets, and radial/linear/brush/polygon/luminance/color masks work. Masks of type person/subject/background/face/segment/object and the `heal` adjustment don't. For those, tell the user: "this one's best done on the Mac". Don't fake it with a poor approximation.

## 1. Inspect
`run.sh inspect PHOTO`, then look at the `original` and `grid` images it returns. The grid has yellow lines every 10% labelled .1–.9, with any detected face boxed in cyan. Read every coordinate you use from this grid. Don't estimate pixel positions by eye.

The JSON also gives `size`, `megapixels`, `file_mb`, `large`, brightness stats, faces, subject boxes, `scene_classes`, and `diagnostics.findings`. Each finding is a measured problem with its `evidence` and a ready recipe `step` (or a `crop` per destination). `diagnostics.skipped` lists the checks this tier couldn't run.

## 2. Suggest, then wait for the pick
Never render before the user has chosen. The one exception: the user already gave the exact edits and said to apply them, e.g. a pasted list plus "apply". In that case, map each item to a step in one line ("eyes +0.4 EV → radial on the eyes, exposure 0.4"), flag anything you can't do, and continue.

Otherwise, suggest. Start from the findings, then add what measurements can't judge: mood, composition, distracting objects, colour harmony. Look at the photo for that.
- Give at most 6 items, ranked by impact for the destination. Put the crop first when you know where the photo is going (Instagram 4:5, LinkedIn square, story 9:16). If you don't know, ask in the same message.
- Each item says what to change, where, how much, and why it helps the post. Quote the evidence, e.g. "you're 2.9 stops darker than the sky".
- Mark taste calls as optional: a cast that may be the grade, a silhouette that may be the look.
- Keep the photo's mood unless the user asks for a new look.
- Output stays at full resolution, cropped only. If `inspect` says `large: true` (over 30 MP), ask in the same message whether to keep full size or shrink it, and say what each costs: full size keeps every pixel but the file can run to tens of MB; a 4096 px long edge is still sharp on any screen at a fraction of the size. Only add `max_edge` to the recipe after the user says yes. Never shrink a photo that isn't `large` unless the user asks.
- End with: "Reply 'go' for all, pick numbers (e.g. 1, 3, 4), or tweak any."

Then stop. The picked items become the recipe. A finding's `step` drops in as written; tweak values if the user asked.

## 3. Write the recipe and check the masks
Write the recipe JSON to a file (schema and examples: `reference/recipe.md`). Run `run.sh masks RECIPE PHOTO` and look at the contact sheet, where each step's mask shows as red.

People, faces, sky and broad scenery have their own types (`person`, `face`, `sky`, `segment`). For anything else the user names ("the snowy peaks", "the glove logo", "that car"), use `object` with a box read from the grid.
- A tight box is the most reliable prompt.
- If the box catches extras, add a positive point inside the target and `exclude` points on the look-alike neighbours.
- `masks` and `apply` list low-confidence object masks in `notes`. Check those on the contact sheet first.
- To remove a distraction, heal it through an `object` or `brush` mask with a small `grow` (0.004).

Fix any mask that spills or misses, at most 2 rounds. Common fixes:
- Subtract `person` from scenery masks.
- Subtract `sky` from mountain masks.
- Intersect with a `linear` band to limit the vertical extent.
- Intersect with `luminance` to hit only bright or dark parts.
- Intersect or subtract an `object` mask when a Vision or SegFormer region is wrong, e.g. intersect `segment` mountain with a box on the one peak the user meant.
- Use an explicit `radial` from the grid when Vision's face points miss. Covered or profile faces often fool it.

## 4. Apply and check
Run `run.sh apply RECIPE PHOTO`. Look at the returned `compare` image (before | after). Also check `after` stats: `clipped_highlights_pct` should stay under ~0.5%, and the sky must not go pure white.

Re-tune and re-apply at most 2 times. Prefer subtle: these are Lightroom-scale sliders, and ±20–40 is usually plenty. Dehaze and clarity on a smooth sky bring out streaks, so mask them to the scenery.

## 5. Deliver
`output` is the final JPEG: in Display P3 when the photo is wide-gamut (most iPhone shots), otherwise sRGB (`color_space` in the `inspect` and `apply` output says which), quality 100 with full colour resolution (4:4:4), the crop's full pixel size unless the recipe set `max_edge`, no metadata (so no GPS). `file_mb` gives its size. If the user wants it lossless, pass `-o NAME.png` for a 16-bit PNG. On Mac it goes in `~/Pictures/feedready/`. On claude.ai it goes in `/mnt/user-data/outputs/`, where it shows as a download.

On the Mac, send it with SendUserFile, along with the compare image. Then give a 2–4 line recap of what changed, and offer one optional next tweak.

## Notes
- The recipe always uses coordinates of the original photo, before the crop. The crop is applied last.
- Presets only set the crop aspect; they never resize. Only `max_edge` shrinks the output, and only with the user's yes.
- Inputs: JPEG, PNG, HEIC (iPhone), TIFF, WebP. HEIC on claude.ai needs pillow-heif; otherwise ask for a JPEG.
- The source repo is `~/sideones/feedready`. Edit and test there (`~/.cache/feedready/venv/bin/python tests/selftest.py`), never in the installed plugin copy.
