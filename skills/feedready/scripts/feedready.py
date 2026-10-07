from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import critique
import diagnose
import masks as maskmod
import render
import review
from detect import (
    CACHE,
    MissingCapability,
    Scene,
    edgetam_available,
    engine_available,
    engine_stale,
    migan_available,
    run_engine,
    segformer_available,
)
from imaging import cv2, icc_profile, is_p3, load_rgb, luma, save_jpeg, save_png16

USAGE = """feedready: render Claude's photo-edit recipes, version by version, and export a post-ready image.

  feedready.py doctor
  feedready.py inspect IMG                       grid overlay + stats + profile + findings (JSON)
  feedready.py masks RECIPE IMG                  contact sheet of every step's mask
  feedready.py board IMG RECIPE [RECIPE ...]     original + each recipe side by side (directions, versions)
  feedready.py preview RECIPE IMG [--note TEXT]  screen-size render saved as the next version, with critique
  feedready.py apply RECIPE IMG [-o OUT]         full-resolution export + before/after compare

RECIPE is a path to a JSON file, an inline JSON string (reference/recipe.md), or a
saved version such as v3. Mac tier renders with Core Image + Vision (feedready-engine);
elsewhere a numpy fallback renders the subset that needs no models.
"""

CLAUDE_OUTPUTS = Path("/mnt/user-data/outputs")
LARGE_MEGAPIXELS = 30
WORKING_COPY_VERSION = 2
PREVIEW_EDGE = 1600
SINGLE_EDGE = 900
BOARD_EDGE = 900
SIMILAR = 0.025
VERSION = re.compile(r"[vV]\d+")


def tier() -> str:
    return "mac" if engine_available() and sys.platform == "darwin" else "basic"


def output_dir() -> Path:
    if CLAUDE_OUTPUTS.exists():
        return CLAUDE_OUTPUTS
    return Path.home() / "Pictures" / "feedready"


def prepare(src: Path) -> tuple[Path, Path, np.ndarray]:
    h = hashlib.sha1()
    with open(src, "rb") as f:
        h.update(f.read(1 << 20))
    h.update(str(src.stat().st_size).encode())
    h.update(str(WORKING_COPY_VERSION).encode())
    work = CACHE / "work" / f"{src.stem}-{h.hexdigest()[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    working = work / "working.png"
    if not working.exists():
        if tier() == "mac":
            run_engine("decode", str(src), str(working))
        else:
            icc = icc_profile(src)
            save_png16(load_rgb(src), working, icc if is_p3(icc) else None)
    return work, working, load_rgb(working)


def wide_profile(working: Path) -> bytes | None:
    icc = icc_profile(working)
    return icc if is_p3(icc) else None


def versions_dir(work: Path) -> Path:
    return work / "versions"


def version_numbers(work: Path) -> list[int]:
    return sorted(int(p.stem[1:]) for p in versions_dir(work).glob("v*.json") if re.fullmatch(r"v\d+", p.stem))


def version_index(work: Path) -> dict:
    path = versions_dir(work) / "index.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_recipe(arg: str, work: Path) -> dict:
    if VERSION.fullmatch(arg.strip()):
        path = versions_dir(work) / f"v{int(arg.strip()[1:])}.json"
        if not path.exists():
            have = ", ".join(f"v{n}" for n in version_numbers(work)) or "none yet"
            raise render.fail(f"no version {arg} for this photo (saved: {have})")
        recipe = json.loads(path.read_text())
    else:
        text = arg if arg.lstrip().startswith("{") else Path(arg).expanduser().read_text()
        try:
            recipe = json.loads(text)
        except json.JSONDecodeError as e:
            raise render.fail(f"recipe is not valid JSON: {e}")
    recipe.setdefault("steps", [])
    return recipe


def stats(img: np.ndarray) -> dict:
    lum = luma(img)
    return {
        "mean_luma": round(float(lum.mean()), 3),
        "p01_p99_luma": [round(float(np.percentile(lum, 1)), 3), round(float(np.percentile(lum, 99)), 3)],
        "clipped_highlights_pct": round(float((img.max(-1) >= 0.995).mean() * 100), 2),
        "crushed_shadows_pct": round(float((lum <= 0.01).mean() * 100), 2),
    }


def cmd_doctor(_args) -> dict:
    report = {
        "tier": tier(),
        "python": sys.version.split()[0],
        "engine (Core Image + Vision)": engine_available(),
        "opencv": cv2 is not None,
        "segformer scene masks": segformer_available(),
        "object masks (EdgeTAM)": edgetam_available(),
        "heal model (MI-GAN)": migan_available(),
        "output_dir": str(output_dir()),
    }
    report["heic"] = importlib.util.find_spec("pillow_heif") is not None or tier() == "mac"
    missing = []
    if sys.platform == "darwin" and not engine_available():
        missing.append("engine: run setup.sh (compiles Swift, no download)")
    elif engine_stale():
        missing.append("engine: built from an older version of this skill; rerun setup.sh (no download)")
    if not segformer_available():
        missing.append("segformer: run setup.sh --segformer (4.4 MB download, ask first)")
    if not edgetam_available():
        missing.append("edgetam: run setup.sh --models (69 MB download, ask first)")
    if not migan_available():
        missing.append("migan: run setup.sh --models (69 MB download, ask first)")
    if cv2 is None:
        missing.append("opencv: grabcut refine unavailable, and heal too unless MI-GAN is installed")
    report["missing"] = missing
    return report


def cmd_inspect(args) -> dict:
    src = Path(args.image).expanduser()
    work, working, img = prepare(src)
    scene = Scene(work, working, img)
    out = {"work_dir": str(work), "size": [img.shape[1], img.shape[0]], "tier": tier(), "stats": stats(img)}
    out.update(_resolution(img, src))
    icc = wide_profile(working)
    out["color_space"] = "display-p3" if icc else "srgb"
    faces = []
    if tier() == "mac":
        v = scene.vision()
        faces = v.get("faces", [])
        out["faces"] = [{k: f.get(k) for k in ("box", "left_pupil", "right_pupil", "confidence")} for f in faces]
        out["person_mask"] = bool(v.get("person"))
        out["subject_instances"] = v.get("subject_instances", 0)
        out["salient_boxes"] = v.get("salient_boxes", [])
        if "horizon_degrees" in v:
            out["horizon_degrees"] = round(v["horizon_degrees"], 2)
    if segformer_available():
        out["scene_classes"] = scene.segment_summary()
    out["profile"] = diagnose.profile(scene)
    out["diagnostics"] = diagnose.run(scene)
    if numbers := version_numbers(work):
        index = version_index(work)
        out["previous_versions"] = [{"version": f"v{n}", "note": index.get(str(n), {}).get("note", "")} for n in numbers]
    grid = work / "grid.jpg"
    review.grid_image(img, faces, grid, icc)
    out["grid"] = str(grid)
    out["original"] = str(working)
    return out


def _resolution(img: np.ndarray, src: Path) -> dict:
    mp = img.shape[0] * img.shape[1] / 1e6
    return {
        "megapixels": round(mp, 1),
        "file_mb": round(src.stat().st_size / 1e6, 1),
        "large": mp > LARGE_MEGAPIXELS,
    }


def _step_masks(steps: list[dict], scene: Scene) -> list[np.ndarray | None]:
    result = []
    for i, step in enumerate(steps):
        try:
            result.append(maskmod.build(step.get("mask"), scene))
        except (MissingCapability, ValueError) as e:
            raise SystemExit(json.dumps({"error": f"step {i + 1} ({step.get('name', '')}): {e}", "tier": tier()}))
    return result


def cmd_masks(args) -> dict:
    src = Path(args.image).expanduser()
    work, working, img = prepare(src)
    recipe = load_recipe(args.recipe, work)
    scene = Scene(work, working, img)
    built = _step_masks(recipe["steps"], scene)
    if not built:
        return {"error": "recipe has no steps"}
    path = work / "masks.jpg"
    review.mask_sheet(img, recipe["steps"], built, path, wide_profile(working))
    coverage = [None if m is None else round(float(m.mean()), 3) for m in built]
    return {"contact_sheet": str(path), "mask_coverage": coverage, "notes": scene.notes}


class Session:
    def __init__(self, src: Path):
        self.src = src
        self.work, self.working, self.img = prepare(src)
        self.scene = Scene(self.work, self.working, self.img)
        self.icc = wide_profile(self.working)
        self.engine = tier() == "mac"
        self.stage = self.work / "stage"
        self.stage.mkdir(exist_ok=True)

    def recipe(self, arg: str) -> dict:
        return load_recipe(arg, self.work)

    def prepare_steps(self, recipe: dict):
        steps, warnings = render.resolve(recipe)
        return steps, _step_masks(steps, self.scene), warnings

    def scaled(self, built: list, edge: int):
        small, small_masks = render.downscale(self.img, built, edge)
        if not self.engine:
            return small, small_masks, None
        path = self.stage / f"base-{small.shape[1]}x{small.shape[0]}.png"
        if not path.exists():
            save_png16(small, path, self.icc)
        return small, small_masks, path

    def render(self, img, steps, built, recipe, out, tag, source, **kw):
        return render.render(img, steps, built, recipe, out, stage=self.stage, tag=tag, engine=self.engine,
                             icc=self.icc, source=source, **kw)


def cmd_apply(args) -> dict:
    s = Session(Path(args.image).expanduser())
    recipe = s.recipe(args.recipe)
    steps, built, warnings = s.prepare_steps(recipe)
    out_dir = output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = args.recipe.strip()
    suffix = ref.lower() if VERSION.fullmatch(ref) else recipe.get("preset", "edit")
    out = Path(args.output).expanduser() if args.output else out_dir / f"{s.src.stem}-{suffix}.jpg"
    crop = render.render(s.img, steps, built, recipe, out, stage=s.work, tag="apply", engine=s.engine, icc=s.icc,
                         source=s.working)
    result = load_rgb(out)
    before = render.frame(s.img, crop)
    compare = out.with_name(out.stem + "-compare.jpg")
    review.pair(before, result, ("before", "after"), compare, s.icc)
    (s.work / "last_recipe.json").write_text(json.dumps(recipe, indent=2))
    return {
        "output": str(out),
        "compare": str(compare),
        "size": [result.shape[1], result.shape[0]],
        "file_mb": round(out.stat().st_size / 1e6, 1),
        "color_space": "display-p3" if s.icc else "srgb",
        "renderer": "core-image" if s.engine else "numpy",
        "before": stats(before),
        "after": stats(result),
        "warnings": warnings,
        "notes": s.scene.notes,
    }


def _frame_faces(scene: Scene, crop, W: int, H: int) -> list[list[float]]:
    try:
        faces = scene.faces()
    except MissingCapability:
        return []
    x, y, w, h = crop if crop else (0, 0, W, H)
    out = []
    for f in faces:
        x0, y0, x1, y1 = f["box"]
        box = [(x0 * W - x) / w, (y0 * H - y) / h, (x1 * W - x) / w, (y1 * H - y) / h]
        if box[2] > 0 and box[3] > 0 and box[0] < 1 and box[1] < 1:
            out.append([min(max(v, 0.0), 1.0) for v in box])
    return out


def _frame_person(scene: Scene, small: np.ndarray, crop) -> np.ndarray | None:
    person = diagnose.person_mask(scene)
    if person is None:
        return None
    H, W = small.shape[:2]
    _, (scaled,) = render.downscale(scene.img, [person], max(H, W))
    return render.frame(scaled, crop)


def _singles(s: Session, recipe: dict, steps: list[dict], built: list):
    tiny, tiny_masks, source = s.scaled(built, SINGLE_EDGE)
    singles, impacts = [], []
    for i, (step, m) in enumerate(zip(steps, tiny_masks)):
        out = s.stage / f"single-{i}.png"
        s.render(tiny, [step], [m], {"steps": [step]}, out, f"single{i}", source, framed=False)
        alone = load_rgb(out)
        imp = critique.impact(tiny, alone, m)
        impacts.append(imp)
        raw = recipe["steps"][i]
        singles.append({"index": i, "name": step.get("name", f"step {i + 1}"), "why": step.get("why", ""),
                        "summary": review.describe(raw.get("adjust", {}), raw.get("look"), raw.get("amount")),
                        "after": alone, "mask": m, **imp})
    return tiny, singles, impacts


def cmd_preview(args) -> dict:
    s = Session(Path(args.image).expanduser())
    recipe = s.recipe(args.recipe)
    steps, built, warnings = s.prepare_steps(recipe)
    vdir = versions_dir(s.work)
    vdir.mkdir(exist_ok=True)
    previous = version_numbers(s.work)
    n = (previous[-1] if previous else 0) + 1
    tag = f"v{n}"

    small, small_masks, source = s.scaled(built, PREVIEW_EDGE)
    out = vdir / f"{tag}.jpg"
    crop = s.render(small, steps, small_masks, recipe, out, "preview", source, full_size=False)
    after = load_rgb(out)
    before = render.frame(small, crop)
    before_path = vdir / ("before-" + "-".join(map(str, crop or (0, 0, small.shape[1], small.shape[0]))) + ".jpg")
    if not before_path.exists():
        save_jpeg(before, before_path, 92, s.icc)

    tiny, singles, impacts = _singles(s, recipe, steps, built)
    faces = _frame_faces(s.scene, crop, small.shape[1], small.shape[0]) if s.engine else []
    person = _frame_person(s.scene, small, crop) if s.engine else None
    verdict = critique.run(before, after, faces, person, recipe.get("vignette", 0), steps, impacts)

    compare = vdir / f"{tag}-compare.jpg"
    review.pair(before, after, ("before", tag), compare, s.icc)
    diff = None
    if previous:
        last = f"v{previous[-1]}"
        diff = vdir / f"{last}-{tag}.jpg"
        review.pair(load_rgb(vdir / f"{last}.jpg"), after, (last, tag), diff, s.icc)
    edit_map = vdir / f"{tag}-map.jpg"
    review.edit_map(small, steps, small_masks, edit_map, s.icc)
    cards = None
    if singles:
        cards = vdir / f"{tag}-cards.jpg"
        review.cards(tiny, singles, cards, s.icc)

    (vdir / f"{tag}.json").write_text(json.dumps(recipe, indent=2))
    index = version_index(s.work)
    index[str(n)] = {"note": args.note, "before": before_path.name, "verdict": verdict["verdict"]}
    (vdir / "index.json").write_text(json.dumps(index, indent=2))
    page = s.work / "review.html"
    review.review_html(f"{s.src.stem} · {tag}", [
        {"n": k, "note": index.get(str(k), {}).get("note", ""), "after": vdir / f"v{k}.jpg",
         "before": vdir / index.get(str(k), {}).get("before", before_path.name)}
        for k in version_numbers(s.work)], page)

    return {
        "version": tag,
        "preview": str(out),
        "compare": str(compare),
        "diff": str(diff) if diff else None,
        "map": str(edit_map),
        "cards": str(cards) if cards else None,
        "review": str(page),
        "critique": verdict,
        "impact": [{"step": i + 1, "name": st.get("name", ""), "level": imp["level"], "delta": imp["delta"],
                    "reach": imp["reach"]} for i, (st, imp) in enumerate(zip(steps, impacts))],
        "after": stats(after),
        "warnings": warnings,
        "notes": s.scene.notes,
    }


def cmd_board(args) -> dict:
    s = Session(Path(args.image).expanduser())
    tiles = [("original", "as shot", render.downscale(s.img, [], BOARD_EDGE)[0])]
    index = version_index(s.work)
    for i, arg in enumerate(args.recipes):
        recipe = s.recipe(arg)
        steps, built, _ = s.prepare_steps(recipe)
        small, small_masks, source = s.scaled(built, BOARD_EDGE)
        out = s.stage / f"board-{i}.png"
        s.render(small, steps, small_masks, recipe, out, f"board{i}", source, full_size=False)
        ref = arg.strip()
        is_version = VERSION.fullmatch(ref) is not None
        if is_version:
            title, note = f"v{int(ref[1:])}", index.get(str(int(ref[1:])), {}).get("note", "")
        else:
            title, note = recipe.get("label") or chr(ord("A") + i), recipe.get("note", "")
        if not note:
            note = ", ".join(f"{st['look']} look" if st.get("look") else st.get("name", "") for st in recipe["steps"])
        tiles.append((title, note, load_rgb(out)))
    path = s.work / "board.jpg"
    review.board(tiles, path, s.icc)
    pairs = critique.distinctness([t[2] for t in tiles])
    names = [t[0] for t in tiles]
    alike = [f"{names[i]} and {names[j]} look alike (difference {d})" for (i, j), d in
             ((pr["pair"], pr["delta"]) for pr in pairs) if d < SIMILAR]
    return {"board": str(path), "tiles": names, "too_similar": alike,
            "differences": {f"{names[pr['pair'][0]]} | {names[pr['pair'][1]]}": pr["delta"] for pr in pairs}}


def main():
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("inspect")
    p.add_argument("image")
    p = sub.add_parser("masks")
    p.add_argument("recipe")
    p.add_argument("image")
    p = sub.add_parser("board")
    p.add_argument("image")
    p.add_argument("recipes", nargs="+")
    p = sub.add_parser("preview")
    p.add_argument("recipe")
    p.add_argument("image")
    p.add_argument("--note", default="")
    p = sub.add_parser("apply")
    p.add_argument("recipe")
    p.add_argument("image")
    p.add_argument("-o", "--output")
    args = ap.parse_args()
    handler = {"doctor": cmd_doctor, "inspect": cmd_inspect, "masks": cmd_masks, "board": cmd_board,
               "preview": cmd_preview, "apply": cmd_apply}[args.cmd]
    print(json.dumps(handler(args), indent=2))


if __name__ == "__main__":
    main()
