<p align="center">
  <img src="assets/logo.svg" width="96" alt="feedready logo">
</p>

<h1 align="center">feedready</h1>

<p align="center">
  <b>Hand Claude a phone photo. Get back one that's ready for Instagram or LinkedIn.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-plugin-D97757" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/macOS-14%2B-000000?logo=apple" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white" alt="Python 3.14">
</p>

---

Attach a photo in Claude Code and say where it's going. Claude edits it the way a Lightroom photographer you hired would. It measures what's holding the photo back ("the wall is 1.0 stop brighter than your face"), shows you three rendered directions side by side, then edits in numbered versions. Before you see a version, Claude checks it against a measured critique: halos, orange skin, blown highlights, steps that change nothing. You reply in plain words, like "darker background" or "back to v2", and it keeps going until the photo is done. You get a full-resolution JPEG with the GPS location stripped out.

On a Mac it renders with Apple's Core Image and Vision, plus small models for sky masks, object masks and object removal. A lighter version runs in the claude.ai app on your phone.

[See it work](#see-it-work) · [Install](#install) · [Edit a photo](#edit-a-photo) · [On your phone](#on-your-phone) · [Other agents](#other-agents) · [Troubleshooting](#troubleshooting) · [Development](#development)

## See it work

One real session, start to finish, on a blue-hour trek photo headed for Instagram.

### 1. Claude reads the photo

`inspect` measures the photo before Claude suggests anything:

| Finding | What it means for the edit |
|---|---|
| Person in scene, outdoors | it's a travel portrait, not a landscape |
| You're 3.9 stops darker than the sky | the jacket pattern is lost in shadow |
| 10.5% of the sky is pure white | the top of the frame reads as blank paper |
| 31% of the frame is empty above you | crop to 4:5 and trim the sky |
| A bright logo on the glove | a small spot pulling the eye away from you |
| Face covered, not readable as skin | face checks are skipped; Claude places the eye light from a zoomed grid |

### 2. Three directions, rendered

All three share the base fixes: the 4:5 crop, the sky recovered, texture on the snow peaks, the eyes lit and the reflective bits tamed. Each adds its own look on top, and `board` warns if two of them come out looking alike.

<p align="center"><img src="assets/demo/1-directions.jpg" alt="The original next to three rendered directions: A Clean, B Cinematic, C Mono editorial"></p>

> **You:** what do you suggest? C is out
>
> **Claude:** B's dusk mood with A's lift on you. The blue, the snow and your black-and-white jacket carry this photo. A leaves the sky flat; B buries you in shadow.

### 3. Each version is reviewed before you see it

v3 lifted the whole body, and Claude's own review caught the black pants turning muddy brown. v4 fades the lift down the legs and holds the blacks. You only ever see v4.

<p align="center"><img src="assets/demo/2-self-review.jpg" width="720" alt="v3 with muddy brown pants next to v4 with black pants"></p>

### 4. What each edit did, and where

The cards render each step on its own, zoomed to where it acts, and rank the steps by how much they changed the photo. The map numbers where every step lands. On the Mac you also get `review.html`, where you can drag a before/after split, click between v1 to v4, and hold <kbd>B</kbd> to see the original.

<table>
  <tr>
    <td width="60%"><img src="assets/demo/3-cards.jpg" alt="Edit cards: each step before and after, ranked by measured impact"></td>
    <td width="40%" valign="top"><img src="assets/demo/4-map.jpg" alt="Edit map with numbered outlines of where each step applies"></td>
  </tr>
</table>

### 5. Ship it

`apply v4` renders the final at full resolution for the 4:5 crop (1333 × 1666), with no metadata.

<p align="center"><img src="assets/demo/5-final.jpg" width="720" alt="Before and after: the original photo and the final v4"></p>

## Install

You need an Apple Silicon Mac on macOS 14 or later, the Xcode Command Line Tools (`xcode-select --install`), and `uv` or Python 3.14. It's built and tested on macOS 26 on an M4.

The repo is a Claude Code plugin and also its own marketplace, so Claude Code installs it straight from your clone:

```bash
git clone git@github.com:dataguyofprocol/feedready.git
claude plugin marketplace add ./feedready
claude plugin install feedready@feedready
```

Then build the runtime. Rerunning it is safe.

```bash
./feedready/skills/feedready/setup.sh --segformer --models
```

| What it sets up | Size | Used for |
|---|---:|---|
| Python 3.14 venv | ~90 MB download | everything |
| Swift engine | compiled locally | Core Image render, Vision masks |
| SegFormer-B0 (`--segformer`) | 4.4 MB | sky, mountain, water and tree masks |
| EdgeTAM (`--models`) | 41 MB | object masks |
| MI-GAN (`--models`) | 28 MB | object removal |

Everything goes in `~/.cache/feedready`, about 400 MB in all. Setup finishes with a `doctor` report; you're done when it says `"tier": "mac"` and `"missing": []`.

You can also install from GitHub without cloning (`claude plugin marketplace add dataguyofprocol/feedready`). In that case, run `setup.sh` from the installed copy under `~/.claude/plugins/cache/feedready/`.

## Edit a photo

Attach a photo in any Claude Code session and ask. "make this insta ready" is enough, or call the skill by name:

```
/feedready:feedready suggest edits for my linkedin profile picture
```

Claude answers with a board of three directions, unless you already named the vibe. From there you steer with short replies. Every version is saved, so you can go back to any of them.

| You reply | Claude does |
|---|---|
| `B` or `B but darker` | edits toward that direction and shows you v1 |
| `warmer`, `too much`, `make me pop` | makes the next version, changing only what you asked about |
| `back to v2`, `v2 but warmer` | starts again from that saved version |
| `show me all versions` | puts every version on one board |
| `ship it` | exports that version at full resolution |
| a pasted edit list, then `apply` | skips the directions and maps each item to an edit |

Each round comes with a before/after, the edit cards and the edit map from the demo above, and on the Mac the `review.html` page.

The finished photo lands in `~/Pictures/feedready/`, next to a `-compare.jpg` before/after. It's a quality-100 JPEG at full resolution; only the crop changes the size, and for photos over 30 MP Claude asks whether to shrink first. Wide-gamut photos, which covers most iPhone shots, stay in Display P3 so saturated colours aren't clipped to sRGB. All metadata is stripped, so your post carries no GPS location.

## On your phone

The phone version runs as an uploaded skill in the claude.ai app. It renders with numpy instead of Core Image and has none of the models, so some edits only work on the Mac:

| | Mac | Phone |
|---|:---:|:---:|
| Crops (Instagram 4:5, LinkedIn square, story 9:16) | ✅ | ✅ |
| Lightroom-style global sliders | ✅ | ✅ |
| Shape, brightness and colour masks | ✅ | ✅ |
| Person, subject and face masks | ✅ | |
| Sky, mountain, water and tree masks | ✅ | |
| Masks for any object you box or click | ✅ | |
| Object removal | ✅ | |

If you ask the phone for one of the Mac-only edits, Claude tells you to do it on the Mac rather than faking it.

To set it up:

1. Build the bundle on the Mac. It lands at `~/Desktop/feedready.zip`; pass a path to put it somewhere else.

   ```bash
   ./feedready/build_zip.sh
   ```

2. In claude.ai, upload the zip under Settings → Capabilities → Skills.
3. Attach a photo in any chat and ask for edits.

> [!NOTE]
> The zip is a snapshot. Rebuild and re-upload it whenever the skill changes.

## Other agents

`skills/feedready/` is a standard [Agent Skill](https://agentskills.io): a `SKILL.md` with `name` and `description`, plus its scripts and references. Any agent that reads that format can run it, as long as it can look at images and run shell commands.

1. Build the runtime once, as in [Install](#install).
2. Link the skill into the agent's skills folder. Codex and other agents that read `~/.agents/skills` use:

   ```bash
   mkdir -p ~/.agents/skills && ln -s "$PWD/feedready/skills/feedready" ~/.agents/skills/feedready
   ```

   Agents with their own folder, such as `.agent/skills/` in a project, get the same link there.

Because it's a link to your clone, edits reach the agent without a version bump. The agent shows you images with whatever file-sending tool it has, or gives you their paths if it has none.

## Troubleshooting

| Problem | Fix |
|---|---|
| `doctor` says `engine` is missing or out of date | `xcode-select --install` if needed, then rerun `skills/feedready/setup.sh` |
| `needs SegFormer` or `object masks need … EdgeTAM` | `skills/feedready/setup.sh --segformer --models` |
| A mask spills onto the wrong area | Check the `masks` contact sheet. Subtract `person` or `sky`, tighten the object box, or add `exclude` points. |
| `notes` calls an object mask low-confidence | The box is probably catching two things. Tighten it or add a point inside the object. |
| HEIC fails on the phone | Send a JPEG. The claude.ai sandbox may not read HEIC. |
| You want a clean slate for a photo | Delete its folder in `~/.cache/feedready/work/` |

## Development

### The engine CLI

Claude runs these commands for you, but you can run them yourself to debug or script edits. Each one prints JSON.

```bash
cd feedready/skills/feedready
./run.sh doctor
./run.sh inspect photo.jpg
./run.sh masks recipe.json photo.jpg
./run.sh board photo.jpg a.json b.json c.json
./run.sh preview recipe.json photo.jpg --note "warmer"
./run.sh apply v3 photo.jpg -o out.jpg
```

| Command | What you get |
|---|---|
| `doctor` | the tier and anything missing |
| `inspect` | a coordinate grid, brightness stats, faces, scene classes, a `profile` (genre and hero), and `diagnostics.findings` (each problem with a ready-made recipe step) |
| `masks` | a contact sheet with every step's mask in red |
| `board` | the original next to each recipe or saved version, plus a `too_similar` warning for look-alike tiles |
| `preview` | a screen-size render saved as the next version (`v1`, `v2`…), with a compare, a diff against the last version, edit cards, an edit map, a review page and a measured `critique` |
| `apply` | the full-resolution photo and compare image, in `~/Pictures/feedready/` unless you pass `-o`. The recipe can be a saved version such as `v3`. |

A recipe is JSON, passed as a file or an inline string. This one crops for Instagram, brightens the eyes, adds bite to the snow caps and removes a reflective strip:

```json
{
  "preset": "instagram",
  "crop": {"aspect": "4:5", "focus": [0.545, 0.335], "focus_at": [0.5, 0.33]},
  "steps": [
    {"name": "lift eyes", "mask": {"type": "radial", "center": [0.555, 0.352], "radius": [0.07, 0.03]},
     "adjust": {"exposure": 0.4}},
    {"name": "snow caps", "mask": {"type": "object", "box": [0.0, 0.40, 1.0, 0.56],
      "points": [[0.72, 0.45], [0.12, 0.47]], "exclude": [[0.5, 0.45]]},
     "adjust": {"clarity": 30, "dehaze": 15}},
    {"name": "remove strip", "mask": {"type": "object", "box": [0.39, 0.80, 0.44, 0.835], "grow": 0.004},
     "adjust": {"heal": true}}
  ]
}
```

> [!IMPORTANT]
> Coordinates are fractions of the original photo, origin top-left, measured before the crop. Read them off the `inspect` grid, not by eye.

[`reference/recipe.md`](skills/feedready/reference/recipe.md) lists every slider, look, mask type, combinator and preset. [`reference/vibes.md`](skills/feedready/reference/vibes.md) is the photographer's playbook: which looks to offer for each genre, how notes map to moves, and the self-review checklist.

### How it fits together

```mermaid
flowchart LR
    P(["photo"]) --> I["<b>inspect</b><br/>diagnose.py"]
    I --> S["directions, notes<br/>vibes.md"]
    S --> R(["recipe / vN"])
    R --> M["<b>masks</b><br/>masks.py, detect.py"]
    M --> X["<b>prepass</b><br/>develop.py"]
    X --> E{"Swift engine<br/>built?"}
    E -->|"yes (Mac)"| C["Core Image render"]
    E -->|"no (phone)"| N["numpy render"]
    C --> O(["version or export"])
    N --> O
    O --> V["<b>critique</b> + visuals<br/>critique.py, review.py"]
    V --> S
```

All paths are under `skills/feedready/`:

| File | Owns |
|---|---|
| `scripts/feedready.py` | the CLI: working copy, saved versions, and the `inspect`, `board`, `preview` and `apply` flows |
| `scripts/render.py` | one render path for every command: looks resolved, prepass, crop, Core Image or numpy |
| `scripts/critique.py` | the self-review on each version: per-step impact, halos, skin, clipping, face vs background, HDR crunch, noise, and board similarity |
| `scripts/review.py` | everything you look at: grid, mask sheet, compare, edit cards, edit map, board, and the HTML review page |
| `scripts/diagnose.py` | the photo `profile` and the checks behind every finding (exposure, subject vs background, face vs background, face, skin-aware colour cast, haze, sky, bright distractions, headroom and crop). Add a check as one function in `CHECKS`. |
| `scripts/masks.py` | mask specs to masks, from simple shapes to EdgeTAM objects, plus combinators and edge refinement |
| `scripts/detect.py` | model access and per-photo caching. Every model path lives here. |
| `scripts/develop.py` | sliders and looks to engine ops, and the prepass: dehaze, clarity and texture via a guided filter, heal via MI-GAN |
| `swift/feedready_engine.swift` | decode, Vision masks and the Core Image render |

Per-photo working files, including every saved version, are cached in `~/.cache/feedready/work/<photo>-<hash>/`.

### Shipping a change

Claude Code runs an installed copy of the plugin, not this repo, so a change only reaches it through a version bump:

1. Edit and test in this repo.
2. Bump `version` in `.claude-plugin/plugin.json` and commit.
3. Update the installed copy:

   ```bash
   claude plugin marketplace update feedready && claude plugin update feedready@feedready
   ```

4. If you touched `swift/feedready_engine.swift`, rerun `setup.sh`. Until you do, `doctor` reports the engine as stale.
5. Run `/reload-plugins` in Claude Code.
6. Rebuild and re-upload the phone zip.

If you change how `board`, the edit cards, the edit map or the before/after compare are drawn, regenerate the images in `assets/demo/` so the demo above still matches what you'd get.

### Tests

```bash
~/.cache/feedready/venv/bin/python tests/selftest.py
```

Run it from the repo root. It covers every slider's direction on both renderers, mask blending, crop geometry, the diagnostics, object masks and heal, and must end with `ALL PASSED`.

> [!TIP]
> Model checks print `skip` when that model isn't installed, so a pass with skips doesn't cover everything.

## Model licences

| Model | Licence |
|---|---|
| EdgeTAM | Apache-2.0 |
| MI-GAN | MIT (training data is research-only) |
| SegFormer-B0 | NVIDIA source licence, non-commercial |

That's fine for your own posts. Check them before using feedready commercially.
