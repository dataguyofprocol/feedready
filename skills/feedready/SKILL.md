---
name: feedready
description: Edit a photo the way a hired Lightroom photographer would. Read the photo, agree the vibe, show rendered directions side by side, then edit in rounds (render, self-review, show, take notes) until the photo hits the vibe, and hand back the final image for Instagram, LinkedIn or a story. Covers grades and looks, exposure, colour, crop, region edits (face, eyes, sky, mountains, person, background, any object) and object removal. Use when the user shares a photo and asks for edits or a look ("make this moody", "insta ready", "fix my profile picture", "edit like a pro"), gives notes on an edit ("warmer", "too much", "go back to v2"), pastes an edit list to apply, or invokes /feedready.
---

# feedready

The user hired you to edit this photo. Work like a good photographer does:
- Read the photo before touching it.
- Agree the vibe in one exchange.
- Show options instead of describing them.
- Check your own work before anyone sees it.
- Take notes in plain words.
- Stop when it's right.

`run.sh` renders; you make every call.

On a Mac the engine uses:
- Apple Core Image for adjustments.
- Vision for person, subject and face masks.
- A 4.4 MB SegFormer model for sky, mountain, water and tree masks.
- EdgeTAM for a mask of any object you box or click.
- MI-GAN for object removal.

Elsewhere (claude.ai, or any machine without the engine) a numpy fallback renders global edits, looks, crops and geometric masks.

Run every command from this skill's base directory: `<base>/run.sh <cmd>` on a Mac, `python3 <base>/scripts/feedready.py <cmd>` on claude.ai. `setup.sh` sits beside `run.sh`. Every command prints JSON.

To show the user an image, use your tool for sending files (SendUserFile in the Claude Code app). If you have none, give the file's absolute path.

**Commands:**

| command | what it does |
|---|---|
| `doctor` | tier and anything missing |
| `inspect PHOTO` | grid, stats, `profile` (genre, hero), measured `findings`, `previous_versions` |
| `board PHOTO R1 R2 …` | the original plus each recipe side by side, with `too_similar` warnings |
| `masks RECIPE PHOTO` | contact sheet of every step's mask |
| `preview RECIPE PHOTO --note "…"` | a screen-size render saved as the next version `vN`, plus visuals and a critique |
| `apply RECIPE PHOTO` | the full-resolution export |

A RECIPE is a JSON file, an inline JSON string or a saved version (`v3`). Schema: `reference/recipe.md`. Taste, directions, note vocabulary and the review checklist: `reference/vibes.md`. Read vibes.md before your first board.

## 0. Check the tier (first use in a session)
Run `run.sh doctor`.
- **`tier: mac` with nothing in `missing`:** full feature set.
- **`missing` lists something:** ask the user before running `<base>/setup.sh`, and say what it downloads:
  - Python packages, ~90 MB from PyPI.
  - `--segformer`: the 4.4 MB scene model.
  - `--models`: the 69 MB object mask and heal models.

  Compiling the Swift engine downloads nothing. Never download a model or package without a yes.
- **`tier: basic`** (claude.ai, phone, or no engine):
  - Works: global sliders, looks, crops, and radial, linear, brush, polygon, luminance and colour masks.
  - Doesn't work: person, subject, background, face, segment and object masks, and the `heal` adjustment. For those, say "this one's best done on the Mac". Don't fake it with a poor approximation.

## 1. Read the photo
Run `run.sh inspect PHOTO`, then look at the `original` and `grid` images. The grid has yellow lines every 10% labelled .1–.9, with any detected face boxed in cyan. Read every coordinate you use from this grid, never by eye.

Form a photographer's read:
- What the photo is about.
- Where the eye should land (`profile.hero`).
- What's working.
- What's holding it back. Use `diagnostics.findings` (each has measured `evidence` and a ready `step`) plus what measurements can't judge: light quality, distractions, colour harmony, the crop.

If `previous_versions` is there, you've edited this photo before. Offer to continue from the latest version or start fresh.

If `profile.signals.face_readable` is false, the face is covered or too dark to read as skin. The face findings are skipped, and Vision's face and eye points are unreliable, so place any face or eye mask from a zoomed grid instead of `type: face`.

## 2. Brief: agree the vibe
You need two things:
- **Destination:** Instagram 4:5, LinkedIn square or profile circle, story 9:16, or as is.
- **Vibe.**

If both are clear already ("make it moody for insta"), skip the board and go to round 1.

Otherwise the board is your question. Build three directions, following vibes.md:
- Every direction shares the base fixes that are right whatever the vibe: findings, distraction removal, the destination crop.
- Each direction then adds its own `look` and the region moves that make that vibe work on this photo.
- One direction is the clean, faithful one. The other two must differ visibly.
- Give each a `label` and a `note`.

Run `run.sh board PHOTO A.json B.json C.json`. If `too_similar` lists a pair, push them apart and rerun.

Show the board and write:
- Your read of the photo, in 1–2 lines.
- A, B and C, one line each: the feel, and what it does to this photo.
- The destination question, if it's unknown.
- If `inspect` says `large: true` (over 30 MP), ask whether to keep full size or shrink it:
  - Full size keeps every pixel, but the file can run to tens of MB.
  - A 4096 px long edge is still sharp on any screen at a fraction of the size.
- End with: "Pick A, B or C, mix them ('B but darker'), or describe the vibe in your own words."

Then stop and wait.

**When the user gives exact edits** (a pasted list plus "apply"): map each item in one line ("eyes +0.4 EV → radial on the eyes, exposure 0.4"), flag anything you can't do, run one round with those edits, and deliver.

## 3. Rounds
Each round produces one version, `vN`, that the user sees.

1. **Recipe.** Start from the chosen direction, or from the last version (`versions/vN.json` in `work_dir`, or simply the reference `vN`). Give each step a plain-language `name` and a `why`; the cards show both. The first time a new mask appears, run `masks` and check its contact sheet (see "Masks" below).
2. **Render.** Run `run.sh preview RECIPE PHOTO --note "<what changed, in the user's words>"`. It returns:

   | field | what it is |
   |---|---|
   | `version` | the new version number |
   | `preview` | the render |
   | `compare` | before \| vN |
   | `diff` | the previous version \| vN |
   | `map` | numbered outlines of where each step lands |
   | `cards` | each step alone, zoomed to where it acts, ranked by measured impact |
   | `review` | an HTML before/after slider across all versions |
   | `critique` | `verdict` plus `issues` |
   | `impact` | per-step change level |

3. **Self-review before showing.** The user never sees a version you wouldn't sign off.
   - Look at `preview`.
   - Fix every `critique` issue with severity `fix`. Weigh each `consider`.
   - If `critique.skipped` lists the face checks, judge the face by eye.
   - Drop or push any step whose `impact` is `none`.
   - Run vibes.md's checklist, and ask whether it hits the brief.

   Revise and re-render up to 3 times. Mention self-caught fixes only if they matter ("I pulled the background back; it was haloing your hair").
4. **Show.** Show these files:
   - The first round: `compare`, `cards` and `map`.
   - Later rounds: `diff`.
   - On the Mac, also `review` for the slider.

   Then write:
   - **vN:** what you did and why, in plain words ("dimmed the wall so your face is the brightest thing").
   - The one change you'd still make, if any.
   - "Notes? ('warmer', 'less on the face', 'back to v2'), or 'ship it'."
5. **Notes become the next round.** Translate them with vibes.md's notes table, and change only what the note is about.
   - **Vague notes** ("make it pop"): do the most likely reading and say what you took it as. Don't interrogate.
   - **"Show me the versions":** run `board PHOTO v1 v2 v3`.

## 4. Stop
- **The user says** ship it, done, perfect, or love it: deliver that version.
- **You're satisfied:** the critique is `clean`, the vibe lands, and what's left is a taste swap, not an improvement. Say "This is where I'd stop: vN", deliver it, and offer to keep going.
- **No convergence after 5 rounds of notes:** show the versions board, ask which is closest, and narrow from there.

## 5. Deliver
Run `run.sh apply vN PHOTO`. It renders that version at full resolution:
- **Colour space:** Display P3 when the photo is wide-gamut (most iPhone shots), otherwise sRGB. `color_space` says which.
- **Quality:** JPEG quality 100 with full colour resolution (4:4:4).
- **Size:** the crop's full pixel size unless the recipe set `max_edge`. Only add `max_edge` after the user agreed to shrink a large photo.
- **Metadata:** none, so no GPS.
- **Lossless:** if the user wants it, pass `-o NAME.png` for a 16-bit PNG.

On the Mac it goes in `~/Pictures/feedready/`; show `output` and `compare`. On claude.ai it goes in `/mnt/user-data/outputs/`, where it shows as a download.

Close the way a photographer hands off: 2–4 lines on what you did to get the vibe.

## Masks
People, faces, sky and broad scenery have their own types: `person`, `face`, `sky`, `segment`. For anything else the user names ("the snowy peaks", "the glove logo", "that car"), use `object` with a box read from the grid.
- A tight box is the most reliable prompt.
- If the box catches extras, add a positive point inside the target and `exclude` points on the look-alike neighbours.
- `masks`, `preview` and `apply` list low-confidence object masks in `notes`. Check those on the contact sheet first.
- To remove a distraction, heal it through an `object` or `brush` mask with a small `grow` (0.004).
- For the background, use `{"type": "person", "invert": true, "grow": -0.002}`. Never feather it: once the background goes darker, a feathered or exact outline leaves a bright rim around hair and fingers. `critique` reports a halo if one slips through.

Fix any mask that spills or misses, at most 2 rounds per mask. Common fixes:
- Subtract `person` from scenery masks, and `sky` from mountain masks.
- Intersect with a `linear` band to limit the vertical extent, or with `luminance` to hit only bright or dark parts.
- Intersect or subtract an `object` mask when a Vision or SegFormer region is wrong.
- Use an explicit `radial` from the grid when Vision's face points miss. Covered or profile faces often fool it.

## Notes
- Prefer subtle: these are Lightroom-scale sliders, and ±20–40 is usually plenty. Dehaze and clarity on a smooth sky bring out streaks, so mask them to the scenery.
- Keep the photo's mood unless the brief changes it.
- Coordinates are fractions of the original photo, before the crop. The crop is applied last.
- Presets only set the crop aspect; they never resize.
- Inputs: JPEG, PNG, HEIC (iPhone), TIFF, WebP. HEIC on claude.ai needs pillow-heif; otherwise ask for a JPEG.
