from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

import lib
import develop
from imaging import save_png16

NEAR_EXACT = {
    "matrix": {"temp": 60},
    "exposure": {"exposure": 0.7},
    "curves": {"contrast": 40, "whites": 20, "blacks": -20},
    "cube": {"hsl": {"blue": {"sat": -30, "hue": -10}}},
}
LOOSE = {
    "vibrance": {"vibrance": 60},
    "saturation": {"saturation": -40},
    "sharpen": {"sharpen": 100},
}


def available():
    from detect import engine_available

    return engine_available() and lib.mac_tier()


def ci_img(recipe, src, name):
    lib.apply_cli(recipe, src, lib.tmp() / f"{name}_ci.jpg")
    return np.asarray(Image.open(lib.tmp() / f"{name}_ci.jpg"), np.float32) / 255


def gate(name, a, b, tol, frac_min, de_max):
    frac, mx = lib.pixel_gate(a, b, tol=tol / 255)
    de = lib.de2000_stats(a, b)
    lib.check(f"engine parity: {name}", frac >= frac_min and de["mean"] < de_max,
              f"frac {frac:.4f}/{frac_min} at {tol}/255, max {mx * 255:.0f}/255, dE {de['mean']:.2f}/{de_max}")


def near_exact(src):
    for name, adj in NEAR_EXACT.items():
        recipe = {"steps": [{"adjust": adj}]}
        gate(name, lib.apply_np(recipe, src, lib.tmp() / f"{name}_np.png"), ci_img(recipe, src, name),
             2, 0.995, 1.0)


def loose_ops(src):
    for name, adj in LOOSE.items():
        recipe = {"steps": [{"adjust": adj}]}
        gate(name, lib.apply_np(recipe, src, lib.tmp() / f"{name}_np.png"), ci_img(recipe, src, name),
             20, 0.92 if name != "sharpen" else 0.97, 1.5)


def geometry(src):
    vig = {"steps": [], "vignette": -30}
    gate("vignette", lib.apply_np(vig, src, lib.tmp() / "vig_np.png"), ci_img(vig, src, "vig"), 10, 0.97, 1.5)
    rs = {"max_edge": 200, "steps": []}
    a = lib.apply_np(rs, src, lib.tmp() / "rs_np.png")
    b = ci_img(rs, src, "rs")
    lib.check("engine parity: resize shape", a.shape == b.shape, f"{a.shape} vs {b.shape}")
    gate("resize", a, b, 20, 0.98, 1.5)
    crop = {"crop": {"aspect": "16:9", "focus": [0.5, 0.2], "focus_at": [0.5, 0.2]}, "steps": []}
    a = lib.apply_np(crop, src, lib.tmp() / "crop_np.png")
    b = ci_img(crop, src, "crop")
    lib.check("engine parity: crop geometry", a.shape == b.shape == (338, 600, 3), f"{a.shape} vs {b.shape}")
    gate("crop rows", a, b, 2, 0.995, 1.0)
    inst = {"preset": "instagram", "steps": []}
    gate("preset crop", lib.apply_np(inst, src, lib.tmp() / "inst_np.png"), ci_img(inst, src, "inst"), 2, 0.995, 1.0)


def highlight_shadow(src):
    adj = {"shadows": 40, "highlights": -40}
    recipe = {"steps": [{"adjust": adj}]}
    base = lib.card()
    np_out = lib.apply_np(recipe, src, lib.tmp() / "hs_np.png")
    ci_out = ci_img(recipe, src, "hs")
    dark = (slice(None), slice(0, 120))
    bright = (slice(None), slice(480, 600))
    lib.check("engine parity: highlight_shadow lifts shadows on both tiers",
              np_out[dark].mean() > base[dark].mean() + 0.02 and ci_out[dark].mean() > base[dark].mean() + 0.02,
              f"np {base[dark].mean():.3f}->{np_out[dark].mean():.3f} ci ->{ci_out[dark].mean():.3f}")
    lib.check("engine parity: highlight_shadow pulls highlights on both tiers",
              np_out[bright].mean() < base[bright].mean() - 0.01 and ci_out[bright].mean() <= base[bright].mean(),
              f"np {base[bright].mean():.3f}->{np_out[bright].mean():.3f} ci ->{ci_out[bright].mean():.3f}")


def determinism(src):
    recipe = {"steps": [{"look": "cinematic", "amount": 80}], "vignette": -15}
    out1, out2 = lib.tmp() / "det1.jpg", lib.tmp() / "det2.jpg"
    lib.apply_cli(recipe, src, out1)
    lib.apply_cli(recipe, src, out2)
    lib.check("engine render is deterministic", out1.read_bytes() == out2.read_bytes(),
              f"{out1.stat().st_size} vs {out2.stat().st_size} bytes")


def plan_schema(src):
    recipe = {"preset": "instagram", "vignette": -10,
              "steps": [{"look": "cinematic", "amount": 80},
                        {"name": "left", "mask": {"type": "linear", "start": [0, 0.5], "end": [0.5, 0.5]},
                         "adjust": {"exposure": 0.4}}]}
    lib.apply_cli(recipe, src, lib.tmp() / "plan_ci.jpg")
    work = lib.work_dir_for(src)
    plan = json.loads((work / "apply-plan.json").read_text())
    lib.check("plan keys", set(plan) == {"input", "output", "quality", "steps", "crop", "resize", "vignette", "p3"},
              str(sorted(plan)))
    lib.check("plan crop matches the recipe", plan["crop"] == [140, 0, 320, 400], str(plan["crop"]))
    lib.check("plan has one masked step", sum(1 for s in plan["steps"] if "mask" in s) == 1)
    lut = None
    cube = None
    for step in plan["steps"]:
        for op in step["ops"]:
            if op["op"] == "curves":
                lut = work / op["lut"]
            if op["op"] == "cube":
                cube = work / op["lut"]
    lib.check("curve lut is float32 x3", lut is not None and lut.stat().st_size == develop.LUT_SIZE * 3 * 4,
              str(lut and lut.stat().st_size))
    lib.check("cube is 32^3 rgba float32", cube is not None and cube.stat().st_size == 32 ** 3 * 4 * 4,
              str(cube and cube.stat().st_size))
    masks = [work / s["mask"] for s in plan["steps"] if "mask" in s]
    lib.check("mask pngs are 8 bit grayscale", all(m.exists() and m.read_bytes()[24] == 8 for m in masks))


def stale_logic():
    import detect

    lib.check("engine is not stale after setup", not detect.engine_stale())
    saved = detect.ENGINE_SOURCE
    detect.ENGINE_SOURCE = lib.tmp() / "pretend.swift"
    detect.ENGINE_SOURCE.write_text("pretend")
    lib.check("engine staleness is detected", detect.engine_stale())
    detect.ENGINE_SOURCE = saved


def run():
    if not available():
        lib.skip("engine (Core Image engine not available)")
        return
    src = lib.tmp() / "card.png"
    save_png16(lib.card(), src)
    near_exact(src)
    loose_ops(src)
    geometry(src)
    highlight_shadow(src)
    determinism(src)
    plan_schema(src)
    stale_logic()
