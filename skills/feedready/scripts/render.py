from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

import develop
from detect import run_engine
from imaging import resize as resize_arr
from imaging import save_jpeg, save_mask, save_png16, to_u8


def fail(message: str) -> SystemExit:
    return SystemExit(json.dumps({"error": message}))


def resolve(recipe: dict) -> tuple[list[dict], list[str]]:
    steps, warnings = [], []
    for i, step in enumerate(recipe["steps"]):
        try:
            adjust = develop.step_adjust(step)
        except ValueError as e:
            raise fail(f"step {i + 1} ({step.get('name', '')}): {e}")
        warnings += develop.validate(adjust)
        steps.append({**step, "adjust": adjust})
    return steps, warnings


def downscale(img: np.ndarray, built: list, edge: int) -> tuple[np.ndarray, list]:
    H, W = img.shape[:2]
    scale = edge / max(H, W)
    if scale >= 1:
        return img, built
    w, h = max(1, round(W * scale)), max(1, round(H * scale))
    return resize_arr(img, w, h).clip(0, 1), [None if m is None else resize_arr(m, w, h).clip(0, 1) for m in built]


def prepass(img, steps, built):
    changed = False
    for step, m in zip(steps, built):
        adj = step["adjust"]
        weight = 1.0 if m is None else m[..., None]
        if adj.get("heal"):
            if m is None:
                raise fail("heal needs a mask (brush dots over the spots)")
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


def output_geometry(recipe, W, H):
    preset = develop.PRESETS.get(recipe.get("preset", "original"))
    if preset is None:
        raise fail(f"unknown preset; use one of {list(develop.PRESETS)}")
    try:
        crop = develop.crop_rect(W, H, recipe.get("crop"), preset["aspect"])
    except (ValueError, TypeError) as e:
        raise fail(f"crop: {e}")
    cw, ch = (crop[2], crop[3]) if crop else (W, H)
    resize = None
    if (max_edge := recipe.get("max_edge")) is not None:
        if not isinstance(max_edge, (int, float)) or max_edge < 64:
            raise fail("max_edge: give the long edge in pixels, at least 64")
        scale = max_edge / max(cw, ch)
        if scale < 1:
            resize = [max(1, round(cw * scale)), max(1, round(ch * scale))]
    return crop, resize


def frame(arr: np.ndarray | None, crop) -> np.ndarray | None:
    if arr is None or crop is None:
        return arr
    x, y, w, h = crop
    return arr[y:y + h, x:x + w]


def render(img, steps, built, recipe, out: Path, *, stage: Path, tag: str, engine: bool, icc: bytes | None,
           source: Path | None = None, framed: bool = True, full_size: bool = True):
    H, W = img.shape[:2]
    pre, changed = prepass(img, steps, built)
    crop, resize = output_geometry(recipe, W, H) if framed else (None, None)
    if not full_size:
        resize = None
    vig = recipe.get("vignette", 0) if framed else 0
    vignette = {"intensity": -vig / 100, "radius": 1.0, "falloff": 0.6} if vig else None
    ops = [develop.build_ops(s["adjust"], max(H, W)) for s in steps]
    quality = recipe.get("quality", 100)
    if engine:
        input_png = source
        if changed or source is None:
            input_png = stage / f"{tag}-input.png"
            save_png16(pre, input_png, icc)
        _render_ci(stage, tag, input_png, built, ops, crop, resize, vignette, out, quality, icc is not None)
    else:
        _render_np(pre, built, ops, crop, resize, vignette, out, quality, icc)
    return crop


def _render_ci(stage, tag, input_png, built, steps_ops, crop, resize, vignette, out, quality, p3):
    (stage / "masks").mkdir(parents=True, exist_ok=True)
    (stage / "luts").mkdir(exist_ok=True)
    plan_steps = []
    for i, (m, ops) in enumerate(zip(built, steps_ops)):
        if not ops:
            continue
        serial = []
        for op in ops:
            op = dict(op)
            if op["op"] == "curves":
                path = stage / "luts" / f"{tag}-s{i}_curve.bin"
                np.repeat(op.pop("lut"), 3).astype(np.float32).tofile(path)
                op["lut"] = str(path.relative_to(stage))
            elif op["op"] == "cube":
                path = stage / "luts" / f"{tag}-s{i}_cube.bin"
                develop.hsl_cube(op.pop("hsl")).tofile(path)
                op.update(lut=str(path.relative_to(stage)), dim=develop.CUBE_DIM)
            serial.append(op)
        step = {"ops": serial}
        if m is not None:
            mp = stage / "masks" / f"{tag}-s{i}.png"
            save_mask(m, mp)
            step["mask"] = str(mp.relative_to(stage))
        plan_steps.append(step)
    plan = {
        "input": str(Path(input_png).relative_to(stage)),
        "output": str(out),
        "quality": quality / 100,
        "steps": plan_steps,
        "crop": list(crop) if crop else None,
        "resize": resize,
        "vignette": vignette,
        "p3": p3,
    }
    plan_path = stage / f"{tag}-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    run_engine("render", str(plan_path))


def _render_np(img, built, steps_ops, crop, resize, vignette, out, quality, icc):
    for m, ops in zip(built, steps_ops):
        adjusted = img
        for op in ops:
            adjusted = develop.np_apply_op(adjusted, op)
        img = adjusted if m is None else img + (adjusted - img) * m[..., None]
        img = np.clip(img, 0, 1)
    img = frame(img, crop)
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
        save_png16(img, out, icc)
    else:
        save_jpeg(img, out, quality, icc)
