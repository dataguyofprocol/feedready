---
name: feedready
description: Suggest and apply Lightroom/Snapseed-style photo edits (exposure, shadows, clarity, dehaze, colour, crop) including region edits on specific things in the photo (face, eyes, sky, mountains, person, background, small spots), then hand back the final image. Use when the user shares a photo and asks for edit suggestions, says "apply these edits", "make this insta/linkedin ready", "edit this for my profile picture", pastes a numbered edit list to apply, or invokes /feedready.
---

# feedready

You plan the edits; `run.sh` renders them. On a Mac it uses Apple Core Image (adjustments) + Vision (person/subject/face masks) + a 4.4 MB SegFormer model (sky/mountain/water/tree masks). Elsewhere (claude.ai) a numpy fallback renders global edits, crops and geometric masks.

Command (Mac): `~/.claude/skills/feedready/run.sh <cmd>`. On claude.ai use `python3 <this skill dir>/scripts/feedready.py <cmd>`. Every command prints JSON.

## 0. Check the tier (first use in a session)
Run `run.sh doctor`.
- `tier: mac` with nothing in `missing`: full feature set.
- `missing` lists something: **ask the user before running `setup.sh`**, and say what it downloads (Python packages ~90 MB from PyPI; `--segformer` adds the 4.4 MB scene model). Compiling the Swift engine downloads nothing. Never download a model or package without a yes.
- `tier: basic` (claude.ai/phone): global sliders, crop/presets, and radial/linear/brush/polygon/luminance/color masks work. Masks of type person/subject/background/face/segment and the `heal` adjustment don't. For those, tell the user: "this one's best done on the Mac". Don't fake it with a poor approximation.

## 1. Inspect
`run.sh inspect PHOTO`, then **look at** the `original` and `grid` images it returns. The grid has yellow lines every 10% labelled .1–.9, with any detected face boxed in cyan. Read every coordinate you use from this grid. Don't estimate pixel positions by eye.

The JSON also gives brightness stats, faces (box plus pupils), subject boxes and `scene_classes` (the main things in the photo with their share and box). Use these to choose masks.

## 2. Suggest, or map the user's list
- If the user wants suggestions, give a short numbered list in this style: what to change, where, by how much, and why it helps the post. Keep the photo's mood unless asked. Suggest a crop for the destination: Instagram 4:5, LinkedIn square, story 9:16.
- If they pasted suggestions (often from an earlier chat), map each item to a recipe step and say what each became, e.g. "eyes +0.4 EV → radial mask on the eyes, exposure 0.4". Flag anything you can't do, such as generative fill or object removal bigger than a small spot.

## 3. Write the recipe and check the masks
Write the recipe JSON to a file (schema and examples: `reference/recipe.md`). Run `run.sh masks RECIPE PHOTO` and **look at** the contact sheet, where each step's mask shows as red.

Fix any mask that spills or misses, at most 2 rounds. Common fixes:
- Subtract `person` from scenery masks.
- Subtract `sky` from mountain masks.
- Intersect with a `linear` band to limit the vertical extent.
- Intersect with `luminance` to hit only bright or dark parts.
- Use an explicit `radial` from the grid when Vision's face points miss. Covered or profile faces often fool it.

## 4. Apply and check
Run `run.sh apply RECIPE PHOTO`. **Look at** the returned `compare` image (before | after). Also check `after` stats: `clipped_highlights_pct` should stay under ~0.5%, and the sky must not go pure white.

Re-tune and re-apply at most 2 times. Prefer subtle: these are Lightroom-scale sliders, and ±20–40 is usually plenty. Dehaze and clarity on a smooth sky bring out streaks, so mask them to the scenery.

## 5. Deliver
`output` is the final JPEG: sRGB, quality 95, no metadata (so no GPS). On Mac it goes in `~/Pictures/feedready/`. On claude.ai it goes in `/mnt/user-data/outputs/`, where it shows as a download.

On the Mac, send it with SendUserFile, along with the compare image. Then give a 2–4 line recap of what changed, and offer one optional next tweak.

## Notes
- The recipe always uses coordinates of the original photo, before the crop. The crop is applied last.
- Presets resize down only, to 1080 px wide. Smaller photos keep their size.
- Inputs: JPEG, PNG, HEIC (iPhone), TIFF, WebP. HEIC on claude.ai needs pillow-heif; otherwise ask for a JPEG.
- Self-test after changing any code: `.venv/bin/python tests/selftest.py`.
