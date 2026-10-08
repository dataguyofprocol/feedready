<p align="center">
  <img src="assets/art/mascot.svg" width="132" alt="The feedready mascot: a little camera in a beret">
</p>

<h1 align="center">feedready</h1>

<p align="center">
  <b>Hand Claude a phone photo. Get back one that's ready for the feed.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-plugin-D97757" alt="Claude Code plugin">
  <img src="https://img.shields.io/badge/macOS-14%2B-000000?logo=apple" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white" alt="Python 3.14">
  <img src="https://img.shields.io/badge/Licence-MIT-3DA639" alt="MIT licence">
</p>

<p align="center">
  <picture>
    <source srcset="assets/hero.webp" type="image/webp">
    <img src="assets/hero.gif" width="880" alt="A real session: Claude measures a trek photo, shows three rendered directions, catches its own mistake between v3 and v4, and ships the final with a before/after wipe">
  </picture>
</p>

Claude edits your photo like an experienced Lightroom editor you hired. It reads the photo before touching it, shows you three rendered directions, then edits in versions and checks each one before you see it. You give notes in plain words until it's right.

feedready is early (v0.2.x) and hobby-paced: the edit loop is solid and covered by a self-test, but the recipe format may still change between minor versions.

## It edits in parts, like a retoucher

<p align="center"><img src="assets/sees.webp" width="880" alt="The demo photo split into the regions Claude found and edited separately: sky, snow peaks, you, eyes, glove logo, valley and a reflective strip, each with how it was found and what was done to it"></p>

One slider moves the sky, your face and your jacket together, so Claude masks them apart. Apple Vision finds people, faces and eyes. SegFormer labels the sky, mountains, water, trees and about 150 other scene classes. EdgeTAM cuts out any object you point at, and brightness and colour ranges catch the rest. Masks combine the way you'd stack them in Lightroom: the snow peaks above are the mountain class, minus you, minus the sky. Each part then gets the edit it needs, and a distraction like the reflective strip gets healed out of the photo entirely.

## Talk to it like a photographer

<p align="center"><img src="assets/art/talk.svg" width="880" alt="Six example notes and what Claude does with each: B but darker, warmer, too much, back to v2, show me all versions, ship it"></p>

Every version is saved, so nothing you liked is ever lost. Already know what you want? Paste an edit list and say `apply`.

## Every round shows its work

<p align="center"><img src="assets/work.webp" width="880" alt="The three edits that changed the demo photo most, each rendered alone as a before and after, with why it was made, its slider values and its measured impact"></p>

Every round renders each edit on its own, zoomed to where it acts, and ranks them by how much they changed the photo, so an edit that changes nothing gets caught. On the Mac you also get a review page with a before/after slider across every version.

## Install

You need an Apple Silicon Mac on macOS 14+, the Xcode Command Line Tools and `uv` or Python 3.14.

```bash
claude plugin marketplace add dataguyofprocol/feedready
claude plugin install feedready@feedready
```

Then attach a photo in any Claude Code session and say "make this insta ready". On first use Claude checks what's missing and asks before it runs setup, which builds the engine and downloads the models. Finished photos land in `~/Pictures/feedready/`.

To update later, run `claude plugin marketplace update feedready && claude plugin update feedready@feedready`.

<details>
<summary><b>What setup installs</b> (about 400 MB, all in <code>~/.cache/feedready</code>)</summary>

| Piece | Size | Used for |
|---|---:|---|
| Python 3.14 venv | ~90 MB download | everything |
| Swift engine | compiled locally | Core Image render, Vision masks |
| SegFormer-B0 (`--segformer`) | 4.4 MB | sky, mountain, water and tree masks |
| EdgeTAM (`--models`) | 41 MB | object masks |
| MI-GAN (`--models`) | 28 MB | object removal |

Setup is safe to rerun. It ends with a `doctor` report; you're done when it says `"tier": "mac"` and `"missing": []`.

To run setup yourself, or to work on feedready from a clone, see [CONTRIBUTING.md](CONTRIBUTING.md#working-from-a-clone).

</details>

<details>
<summary><b>What you get back</b></summary>

- A quality-100 JPEG at full resolution, next to a `-compare.jpg` before/after. Only the crop changes the size; over 30 MP, Claude asks whether to shrink first.
- Wide-gamut photos (most iPhone shots) stay in Display P3, so saturated colours aren't clipped to sRGB.
- All metadata is stripped, so your post carries no GPS location.

</details>

## On your phone

A lighter version runs as an uploaded skill in the claude.ai app. It renders with numpy and has no models, so a few edits stay on the Mac. Ask for one and Claude says so instead of faking it.

| | Mac | Phone |
|---|:---:|:---:|
| Crops, Lightroom-style sliders, looks | ✅ | ✅ |
| Shape, brightness and colour masks | ✅ | ✅ |
| Person, face, sky and scenery masks | ✅ | |
| Masks for any object, and object removal | ✅ | |

<details>
<summary><b>Set it up</b></summary>

1. On the Mac, clone this repo (`git clone https://github.com/dataguyofprocol/feedready.git`) and run `./feedready/build_zip.sh`. The bundle lands at `~/Desktop/feedready.zip`.
2. In claude.ai, upload it under Settings → Capabilities → Skills.
3. Attach a photo in any chat and ask for edits.

The zip is a snapshot, so rebuild and re-upload it whenever the skill changes.

</details>

## More

<details>
<summary><b>Use it from Codex or another agent</b></summary>

`skills/feedready/` is a standard [Agent Skill](https://agentskills.io). Any agent that reads that format can run it, as long as it can look at images and run shell commands. Clone this repo and build the runtime once with `./feedready/skills/feedready/setup.sh --segformer --models`, then link the skill into the agent's skills folder:

```bash
mkdir -p ~/.agents/skills && ln -s "$PWD/feedready/skills/feedready" ~/.agents/skills/feedready
```

Agents with their own folder, such as `.agent/skills/` in a project, get the same link there. Because it's a link, edits to your clone reach the agent without a version bump.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

| Problem | Fix |
|---|---|
| `doctor` says `engine` is missing or out of date | `xcode-select --install` if needed, then ask Claude to rerun setup |
| `needs SegFormer` or `object masks need … EdgeTAM` | Ask Claude to rerun setup with `--segformer --models` |
| A mask spills onto the wrong area | Check the `masks` contact sheet. Subtract `person` or `sky`, tighten the object box, or add `exclude` points. |
| `notes` calls an object mask low-confidence | The box is probably catching two things. Tighten it or add a point inside the object. |
| HEIC fails on the phone | Send a JPEG. The claude.ai sandbox may not read HEIC. |
| You want a clean slate for a photo | Delete its folder in `~/.cache/feedready/work/` |

</details>

<details>
<summary><b>Model licences</b></summary>

| Model | Licence |
|---|---|
| EdgeTAM | Apache-2.0 |
| MI-GAN | MIT (training data is research-only) |
| SegFormer-B0 | NVIDIA source licence, non-commercial |

That's fine for your own posts. Check them before using feedready commercially.

</details>

## Licence

The code is MIT — see [LICENSE](LICENSE). The models `setup.sh` downloads keep their own licences; check the table above before using them commercially.

Want to drive the engine yourself, read the recipe format or change the skill? See [CONTRIBUTING.md](CONTRIBUTING.md).
