# feedready

feedready is a Claude skill that edits phone photos for Instagram and LinkedIn. You share a photo. Claude measures it, suggests up to six ranked edits with the evidence behind each, and waits for your pick. It then applies them, including edits to specific regions such as your face, the sky, a mountain, or one object. You get back a finished JPEG and a before/after image.

It runs in two places:

| Where | What works |
|---|---|
| **Mac** (Claude Code, desktop app or terminal) | Everything: Lightroom-style sliders on Apple Core Image; person, subject and face masks from Apple Vision; sky and mountain masks; box/click object masks; object removal |
| **Phone** (claude.ai app, as an uploaded skill) | Crops, global sliders, and shape, brightness and colour masks. Anything that needs a model is routed to the Mac. |

## Requirements

- An Apple Silicon Mac on macOS 14 or later (built and tested on macOS 26, M4).
- Xcode Command Line Tools, for `swiftc`. Install with `xcode-select --install`.
- `uv` (recommended) or Python 3.14.
- About 400 MB of disk: a 263 MB Python venv, 71 MB of models, plus working files.

## Install on the Mac

The skill lives in `~/.claude/skills/feedready`. Claude Code picks up skills from there automatically.

```bash
cd ~/.claude/skills/feedready
./setup.sh --segformer --models
```

`setup.sh` is safe to rerun. It does four things:

1. Creates `.venv` with Python 3.14 and installs `requirements.txt` from PyPI (about 90 MB download).
2. Compiles `swift/feedready_engine.swift` to `~/.cache/feedready/bin/feedready-engine`. This downloads nothing.
3. With `--segformer`, it downloads the SegFormer-B0 scene model (4.4 MB) for sky, mountain, water and tree masks.
4. With `--models`, it downloads EdgeTAM (41 MB, object masks) and MI-GAN (28 MB, object removal).

When it finishes, it prints the `doctor` report. A complete install shows `"tier": "mac"` and `"missing": []`.

## Use it in Claude Code

Open any Claude Code session, attach a photo, and either ask naturally or invoke the skill by name:

```
/feedready make this insta ready
```

```
/feedready suggest edits for my linkedin profile picture
```

Claude replies with a numbered list of suggestions. Reply `go` to apply all of them, a list of numbers such as `1, 3, 4`, or a tweak such as "2 but subtler". Claude then shows you the masks it built, renders the edit, checks the before/after, and sends you the final image.

If you already have a list of edits, for example from an earlier chat, paste it and say `apply`. Claude skips the suggestion step and maps each item onto an edit.

Final images go to `~/Pictures/feedready/`. Each one is an sRGB JPEG at quality 95 with no metadata, so no GPS location, next to a `-compare.jpg` before/after.

## Use it from the phone

1. On the Mac, build the upload bundle:

   ```bash
   ~/.claude/skills/feedready/build_zip.sh
   ```

   It writes `~/Desktop/feedready.zip`. Pass a path to write it somewhere else.
2. In claude.ai, open Settings → Capabilities → Skills and upload the zip.
3. In any chat, attach a photo and ask for edits. Downloads appear in the chat.

The phone tier ships no models. When an edit needs one (person, sky, object masks, or removal), Claude tells you to do that one on the Mac. Rebuild and re-upload the zip whenever the skill changes.

## Run the engine directly

Claude normally drives these commands. You can run them yourself to debug or script edits. Every command prints JSON.

```bash
cd ~/.claude/skills/feedready
./run.sh doctor
./run.sh inspect photo.jpg
./run.sh masks recipe.json photo.jpg
./run.sh apply recipe.json photo.jpg -o out.jpg
```

- `doctor` reports the tier and anything missing.
- `inspect` writes a coordinate grid image, brightness stats, detected faces and scene classes, and `diagnostics.findings`: measured problems, each with a ready-made recipe step.
- `masks` writes a contact sheet with each step's mask in red.
- `apply` renders the image and writes the compare image. Without `-o`, the output lands in `~/Pictures/feedready/`.

A recipe is JSON, passed as a file path or an inline string. This one crops for Instagram, lifts the eyes, and removes a reflective strip:

```json
{
  "preset": "instagram",
  "crop": {"aspect": "4:5", "focus": [0.545, 0.335], "focus_at": [0.5, 0.33]},
  "steps": [
    {"name": "lift eyes", "mask": {"type": "radial", "center": [0.555, 0.352], "radius": [0.07, 0.03]},
     "adjust": {"exposure": 0.4}},
    {"name": "snow caps", "mask": {"type": "object", "box": [0.0, 0.40, 1.0, 0.56], "exclude": [[0.5, 0.45]]},
     "adjust": {"clarity": 30, "dehaze": 15}},
    {"name": "remove strip", "mask": {"type": "object", "box": [0.39, 0.80, 0.44, 0.835], "grow": 0.004},
     "adjust": {"heal": true}}
  ]
}
```

Coordinates are fractions of the original photo, origin top-left. Read them off the `inspect` grid. `reference/recipe.md` lists every slider, mask type, combinator and preset.

## How it works

```
photo ─► inspect ─► diagnostics + grid ─► Claude suggests ─► you pick
                                                              │
     final JPEG ◄─ Core Image render ◄─ prepass ◄─ masks ◄─ recipe
```

- `scripts/feedready.py` is the CLI and the pipeline: working copy, masks, prepass, render, compare.
- `scripts/diagnose.py` holds the measured checks behind the suggestions: exposure, subject vs background, face, colour cast, haze, sky, bright distractions, and headroom/crop. Each check is one function in the `CHECKS` list.
- `scripts/masks.py` turns mask specs into masks: shapes, ranges, Vision, SegFormer, EdgeTAM objects, combinators, edge refinement.
- `scripts/detect.py` handles model access and per-photo caching (`Scene`). All model paths live here.
- `scripts/develop.py` maps Lightroom-style sliders to engine operations, and runs the prepass: dehaze, clarity and texture with an edge-aware guided filter, and heal with MI-GAN.
- `swift/feedready_engine.swift` is the Core Image and Vision executable: decode, Vision masks, and the render.
- Without the Swift engine, a numpy renderer takes over. That is the phone tier.

Working files for each photo are cached under `~/.cache/feedready/work/<photo>-<hash>/`.

## Test

```bash
cd ~/.claude/skills/feedready
.venv/bin/python tests/selftest.py
```

This checks every slider's direction on both renderers, mask blending, crop geometry, the diagnostics, object masks and heal. It must end with `ALL PASSED`. Model checks print `skip` when the model isn't installed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor` lists `engine` as missing | Run `xcode-select --install`, then `./setup.sh` |
| `needs SegFormer` or `object masks need … EdgeTAM` | Run `./setup.sh --segformer --models` |
| A mask spills onto the wrong area | Check the `masks` contact sheet. Subtract `person` or `sky`, tighten the object box, or add `exclude` points. |
| `notes` says an object mask is low-confidence | The box probably catches two things. Tighten it or add a positive point inside the object. |
| HEIC fails on the phone | Send a JPEG; the claude.ai sandbox may lack HEIC support |
| Want to start fresh for a photo | Delete its folder under `~/.cache/feedready/work/` |

## Licences of the downloaded models

- EdgeTAM: Apache-2.0.
- MI-GAN: MIT. Its training data is research-only.
- SegFormer-B0: NVIDIA source licence, non-commercial.

All three are fine for personal posts. Check the licences before any commercial use.
