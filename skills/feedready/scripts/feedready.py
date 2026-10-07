from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))

import develop
import diagnose
import masks as maskmod
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
from imaging import cv2, load_rgb, luma, save_jpeg, save_mask, save_png16, to_u8

USAGE = """feedready: apply Claude's photo-edit recipe and export a post-ready image.

  feedready.py doctor
  feedready.py inspect IMG                 grid overlay + stats + detections (JSON)
  feedready.py masks RECIPE IMG            contact sheet of every step's mask
  feedready.py apply RECIPE IMG [-o OUT]   render final JPEG + before/after compare

RECIPE is a path to a JSON file or an inline JSON string (reference/recipe.md).
Mac tier renders with Core Image + Vision (feedready-engine); elsewhere a numpy
fallback renders the subset that needs no models.
"""

CLAUDE_OUTPUTS = Path("/mnt/user-data/outputs")
LARGE_MEGAPIXELS = 30


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
    work = CACHE / "work" / f"{src.stem}-{h.hexdigest()[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    working = work / "working.png"
    if not working.exists():
        if tier() == "mac":
            run_engine("decode", str(src), str(working))
        else:
            save_png16(load_rgb(src), working)
    return work, working, load_rgb(working)


def load_recipe(arg: str) -> dict:
    text = arg if arg.lstrip().startswith("{") else Path(arg).expanduser().read_text()
    recipe = json.loads(text)
    recipe.setdefault("steps", [])
    return recipe


def _font(size: int):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _thumb(img: np.ndarray, long_edge: int) -> Image.Image:
    im = Image.fromarray(to_u8(img))
    im.thumbnail((long_edge, long_edge), Image.LANCZOS)
    return im


def grid_image(img: np.ndarray, scene: Scene | None, path: Path) -> None:
    im = _thumb(img, 1400).convert("RGB")
    W, H = im.size
    draw = ImageDraw.Draw(im, "RGBA")
    font = _font(max(12, W // 60))
    for i in range(1, 10):
        x, y = W * i / 10, H * i / 10
        width = 2 if i == 5 else 1
        draw.line([(x, 0), (x, H)], fill=(255, 255, 0, 150), width=width)
        draw.line([(0, y), (W, y)], fill=(255, 255, 0, 150), width=width)
        draw.text((x + 3, 3), f".{i}", fill=(255, 255, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        draw.text((3, y + 2), f".{i}", fill=(255, 255, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
    if scene is not None and tier() == "mac":
        for f in scene.faces():
            x0, y0, x1, y1 = f["box"]
            draw.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=(0, 255, 255, 255), width=2)
    im.save(path, quality=90)


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
    if tier() == "mac":
        v = scene.vision()
        out["faces"] = [{k: f.get(k) for k in ("box", "left_pupil", "right_pupil", "confidence")} for f in v.get("faces", [])]
        out["person_mask"] = bool(v.get("person"))
        out["subject_instances"] = v.get("subject_instances", 0)
        out["salient_boxes"] = v.get("salient_boxes", [])
        if "horizon_degrees" in v:
            out["horizon_degrees"] = round(v["horizon_degrees"], 2)
    if segformer_available():
        out["scene_classes"] = scene.segment_summary()
    out["diagnostics"] = diagnose.run(scene)
    grid = work / "grid.jpg"
    grid_image(img, scene, grid)
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


def _step_masks(recipe: dict, scene: Scene) -> list[np.ndarray | None]:
    result = []
    for i, step in enumerate(recipe["steps"]):
        try:
            result.append(maskmod.build(step.get("mask"), scene))
        except (MissingCapability, ValueError) as e:
            raise SystemExit(json.dumps({"error": f"step {i + 1} ({step.get('name', '')}): {e}", "tier": tier()}))
    return result


def cmd_masks(args) -> dict:
    recipe = load_recipe(args.recipe)
    work, working, img = prepare(Path(args.image).expanduser())
    scene = Scene(work, working, img)
    built = _step_masks(recipe, scene)
    tiles = []
    font = _font(22)
    for i, (step, m) in enumerate(zip(recipe["steps"], built)):
        base = img.copy()
        if m is not None:
            base = base * (1 - 0.6 * m[..., None]) + np.array([1.0, 0.1, 0.1]) * 0.6 * m[..., None]
        tile = _thumb(base, 520)
        ImageDraw.Draw(tile).text((8, 6), f"{i + 1}. {step.get('name', '')}"[:40], fill="white", font=font,
                                  stroke_width=3, stroke_fill="black")
        tiles.append(tile)
    if not tiles:
        return {"error": "recipe has no steps"}
    cols = min(3, len(tiles))
    rows = -(-len(tiles) // cols)
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw + (cols - 1) * 6, rows * th + (rows - 1) * 6), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (tw + 6), (i // cols) * (th + 6)))
    path = work / "masks.jpg"
    sheet.save(path, quality=88)
    coverage = [None if m is None else round(float(m.mean()), 3) for m in built]
    return {"contact_sheet": str(path), "mask_coverage": coverage, "notes": scene.notes}


def _prepass(img, recipe, built):
    changed = False
    for step, m in zip(recipe["steps"], built):
        adj = step.get("adjust", {})
        weight = 1.0 if m is None else m[..., None]
        if adj.get("heal"):
            if m is None:
                raise SystemExit(json.dumps({"error": "heal needs a mask (brush dots over the spots)"}))
            img = develop.heal(img, m)
            changed = True
        if d := adj.get("dehaze"):
            img = img + (develop.dehaze(img, d / 100) - img) * weight
            changed = True
        for kind in ("texture", "clarity"):
            if v := adj.get(kind):
                img = img + (develop.local_contrast(img, kind, v / 100) - img) * weight
                changed = True
    return np.clip(img, 0, 1), changed


def _output_geometry(recipe, W, H):
    preset = develop.PRESETS.get(recipe.get("preset", "original"))
    if preset is None:
        raise SystemExit(json.dumps({"error": f"unknown preset; use one of {list(develop.PRESETS)}"}))
    try:
        crop = develop.crop_rect(W, H, recipe.get("crop"), preset["aspect"])
    except (ValueError, TypeError) as e:
        raise SystemExit(json.dumps({"error": f"crop: {e}"}))
    cw, ch = (crop[2], crop[3]) if crop else (W, H)
    resize = None
    if (max_edge := recipe.get("max_edge")) is not None:
        if not isinstance(max_edge, (int, float)) or max_edge < 64:
            raise SystemExit(json.dumps({"error": "max_edge: give the long edge in pixels, at least 64"}))
        scale = max_edge / max(cw, ch)
        if scale < 1:
            resize = [max(1, round(cw * scale)), max(1, round(ch * scale))]
    return crop, resize


def cmd_apply(args) -> dict:
    recipe = load_recipe(args.recipe)
    src = Path(args.image).expanduser()
    work, working, img = prepare(src)
    scene = Scene(work, working, img)
    warnings = []
    for step in recipe["steps"]:
        warnings += develop.validate(step.setdefault("adjust", {}))
    built = _step_masks(recipe, scene)
    H, W = img.shape[:2]
    long_edge = max(H, W)

    pre, changed = _prepass(img, recipe, built)
    input_png = working
    if changed:
        input_png = work / "prepass.png"
        save_png16(pre, input_png)

    crop, resize = _output_geometry(recipe, W, H)
    vig = recipe.get("vignette", 0)
    vignette = {"intensity": -vig / 100, "radius": 1.0, "falloff": 0.6} if vig else None

    out_dir = output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.output).expanduser() if args.output else out_dir / f"{src.stem}-{recipe.get('preset', 'edit')}.jpg"

    steps_ops = [develop.build_ops(s["adjust"], long_edge) for s in recipe["steps"]]
    if tier() == "mac":
        _render_ci(work, input_png, recipe, built, steps_ops, crop, resize, vignette, out)
    else:
        _render_np(pre, built, steps_ops, crop, resize, vignette, out, recipe.get("quality", 100))

    result = load_rgb(out)
    before = img if crop is None else img[crop[1]:crop[1] + crop[3], crop[0]:crop[0] + crop[2]]
    compare = out.with_name(out.stem + "-compare.jpg")
    _compare(before, result, compare)
    (work / "last_recipe.json").write_text(json.dumps(recipe, indent=2))
    return {
        "output": str(out),
        "compare": str(compare),
        "size": [result.shape[1], result.shape[0]],
        "file_mb": round(out.stat().st_size / 1e6, 1),
        "renderer": "core-image" if tier() == "mac" else "numpy",
        "before": stats(before),
        "after": stats(result),
        "warnings": warnings,
        "notes": scene.notes,
    }


def _render_ci(work, input_png, recipe, built, steps_ops, crop, resize, vignette, out):
    (work / "masks").mkdir(exist_ok=True)
    (work / "luts").mkdir(exist_ok=True)
    plan_steps = []
    for i, (m, ops) in enumerate(zip(built, steps_ops)):
        if not ops:
            continue
        serial = []
        for op in ops:
            op = dict(op)
            if op["op"] == "curves":
                path = work / "luts" / f"s{i}_curve.bin"
                np.repeat(op.pop("lut"), 3).astype(np.float32).tofile(path)
                op["lut"] = str(path.relative_to(work))
            elif op["op"] == "cube":
                path = work / "luts" / f"s{i}_cube.bin"
                develop.hsl_cube(op.pop("hsl")).tofile(path)
                op.update(lut=str(path.relative_to(work)), dim=develop.CUBE_DIM)
            serial.append(op)
        step = {"ops": serial}
        if m is not None:
            mp = work / "masks" / f"step{i}.png"
            save_mask(m, mp)
            step["mask"] = str(mp.relative_to(work))
        plan_steps.append(step)
    plan = {
        "input": str(Path(input_png).relative_to(work)),
        "output": str(out),
        "quality": recipe.get("quality", 100) / 100,
        "steps": plan_steps,
        "crop": list(crop) if crop else None,
        "resize": resize,
        "vignette": vignette,
    }
    plan_path = work / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    run_engine("render", str(plan_path))


def _render_np(img, built, steps_ops, crop, resize, vignette, out, quality):
    for m, ops in zip(built, steps_ops):
        adjusted = img
        for op in ops:
            adjusted = develop.np_apply_op(adjusted, op)
        img = adjusted if m is None else img + (adjusted - img) * m[..., None]
        img = np.clip(img, 0, 1)
    if crop:
        x, y, w, h = crop
        img = img[y:y + h, x:x + w]
    if resize:
        im = Image.fromarray(to_u8(img)).resize(tuple(resize), Image.LANCZOS)
        img = np.asarray(im, np.float32) / 255
    if vignette:
        H, W = img.shape[:2]
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.hypot(xx - W / 2, yy - H / 2) / (np.hypot(W, H) / 2 * vignette["radius"])
        fall = np.clip((d - (1 - vignette["falloff"])) / vignette["falloff"], 0, 1) ** 2
        img = img * (1 - vignette["intensity"] * 0.8 * fall)[..., None]
    if Path(out).suffix.lower() == ".png":
        save_png16(img, out)
    else:
        save_jpeg(img, out, quality)


def _compare(before, after, path, height=900):
    a, b = _thumb(before, 4000), _thumb(after, 4000)
    a = a.resize((int(a.width * height / a.height), height), Image.LANCZOS)
    b = b.resize((int(b.width * height / b.height), height), Image.LANCZOS)
    sheet = Image.new("RGB", (a.width + b.width + 8, height), "white")
    sheet.paste(a, (0, 0))
    sheet.paste(b, (a.width + 8, 0))
    draw = ImageDraw.Draw(sheet)
    font = _font(26)
    for x, label in ((10, "before"), (a.width + 18, "after")):
        draw.text((x, 8), label, fill="white", font=font, stroke_width=3, stroke_fill="black")
    sheet.save(path, quality=90)


def main():
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("inspect")
    p.add_argument("image")
    p = sub.add_parser("masks")
    p.add_argument("recipe")
    p.add_argument("image")
    p = sub.add_parser("apply")
    p.add_argument("recipe")
    p.add_argument("image")
    p.add_argument("-o", "--output")
    args = ap.parse_args()
    handler = {"doctor": cmd_doctor, "inspect": cmd_inspect, "masks": cmd_masks, "apply": cmd_apply}[args.cmd]
    print(json.dumps(handler(args), indent=2))


if __name__ == "__main__":
    main()
