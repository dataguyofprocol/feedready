"""Self-test: every slider moves the image the right way, on both renderers.

  .venv/bin/python tests/selftest.py

Builds a synthetic test card (gradient, colour patches, texture), applies each
slider globally, and checks the expected direction on the Core Image renderer
(when the engine is built) and the numpy fallback.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import develop  # noqa: E402
import masks  # noqa: E402
from detect import Scene, edgetam_available, engine_available, migan_available  # noqa: E402
from imaging import gaussian, load_rgb, luma, rgb_to_hsv, save_png16, srgb_to_linear  # noqa: E402

FAILS = []


def card() -> np.ndarray:
    rng = np.random.default_rng(0)
    h, w = 400, 600
    x = np.linspace(0, 1, w, dtype=np.float32)
    img = np.repeat(np.repeat(x[None, :, None], h, 0), 3, 2) * 0.9 + 0.05
    colours = [(0.8, 0.2, 0.2), (0.9, 0.6, 0.2), (0.2, 0.7, 0.3), (0.2, 0.4, 0.85), (0.6, 0.3, 0.7), (0.5, 0.5, 0.5)]
    for i, c in enumerate(colours):
        img[250:330, 20 + i * 95:100 + i * 95] = c
    texture = gaussian(rng.normal(0, 0.06, (h, w)).astype(np.float32), 1.5)
    img[20:120] += texture[20:120, :, None]
    return img.clip(0, 1)


def run(cmd, recipe, src, out):
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "feedready.py"), cmd, json.dumps(recipe), str(src), "-o", str(out)],
                         capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(res.stderr or res.stdout)
    return load_rgb(out)


def check(name, ok, detail=""):
    print(f"  {'ok ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


def metrics(img):
    _, s, _ = rgb_to_hsv(img)
    lum = luma(img)
    lin = srgb_to_linear(img)
    return {
        "mean": float(lum.mean()),
        "dark": float(lum[:, :120].mean()),
        "bright": float(lum[:, -120:].mean()),
        "sat": float(s[250:330].mean()),
        "blue_sat": float(s[250:330, 305:385].mean()),
        "rb": float(lin[..., 0].mean() / lin[..., 2].mean()),
        "green": float(lin[..., 1].mean() / lin.mean()),
        "local": float(np.abs(lum[20:120] - gaussian(lum[20:120], 12)).mean()),
        "fine": float(np.abs(lum[20:120] - gaussian(lum[20:120], 1.5)).mean()),
        "std": float(lum.std()),
    }


EXPECT = {
    "exposure": (1.0, lambda b, a: a["mean"] > b["mean"] + 0.05),
    "contrast": (60, lambda b, a: a["std"] > b["std"] * 1.03),
    "highlights": (-80, lambda b, a: a["bright"] < b["bright"] - 0.01),
    "shadows": (80, lambda b, a: a["dark"] > b["dark"] + 0.01),
    "whites": (80, lambda b, a: a["bright"] > b["bright"] + 0.005),
    "blacks": (-80, lambda b, a: a["dark"] < b["dark"] - 0.005),
    "temp": (60, lambda b, a: a["rb"] > b["rb"] * 1.1),
    "tint": (60, lambda b, a: a["green"] < b["green"] * 0.98),
    "vibrance": (80, lambda b, a: a["sat"] > b["sat"] + 0.02),
    "saturation": (-60, lambda b, a: a["sat"] < b["sat"] - 0.05),
    "clarity": (80, lambda b, a: a["local"] > b["local"] * 1.1),
    "texture": (80, lambda b, a: a["fine"] > b["fine"] * 1.1),
    "sharpen": (120, lambda b, a: a["fine"] > b["fine"] * 1.05),
}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="feedready-test-"))
    src = tmp / "card.png"
    base = card()
    save_png16(base, src)
    renderers = ["core-image"] if engine_available() else []
    renderers.append("numpy")

    for renderer in renderers:
        print(f"[{renderer}]")
        if renderer == "numpy":
            import detect

            detect.ENGINE = Path("/nonexistent")  # force fallback in-process
        identity = _apply(renderer, {"steps": []}, src, tmp / f"id_{renderer}.png")
        err = float(np.abs(identity - base).max())
        check("identity", err <= 1.5 / 255, f"max err {err * 255:.2f}/255")

        before = metrics(base)
        for slider, (value, ok) in EXPECT.items():
            out = _apply(renderer, {"steps": [{"adjust": {slider: value}}]}, src, tmp / f"{slider}_{renderer}.png")
            check(f"{slider}={value}", ok(before, metrics(out)))

        hazy = base * 0.55 + 0.4
        save_png16(hazy, tmp / "hazy.png")
        out = _apply(renderer, {"steps": [{"adjust": {"dehaze": 60}}]}, tmp / "hazy.png", tmp / f"dehaze_{renderer}.png")
        hb, ha = metrics(hazy), metrics(out)
        check("dehaze=60 on hazy card", ha["std"] > hb["std"] * 1.15 and ha["mean"] > hb["mean"] - 0.2,
              f"std {hb['std']:.3f}->{ha['std']:.3f} mean {hb['mean']:.3f}->{ha['mean']:.3f}")

        out = _apply(renderer, {"steps": [{"adjust": {"hsl": {"blue": {"sat": -100}}}}]}, src, tmp / f"hsl_{renderer}.png")
        a = metrics(out)
        check("hsl blue sat -100", a["blue_sat"] < before["blue_sat"] * 0.4 and abs(a["sat"] - before["sat"]) < 0.2)

        out = _apply(renderer, {"steps": [{"adjust": {"exposure": 1}, "mask": {"type": "radial", "center": [-0.5, -0.5], "radius": 0.1}}]},
                     src, tmp / f"zero_{renderer}.png")
        check("empty mask changes nothing", float(np.abs(out - base).max()) <= 1.5 / 255)

        gray = np.full((64, 64, 3), 0.3, np.float32)
        save_png16(gray, tmp / "gray.png")
        out = _apply(renderer, {"steps": [{"adjust": {"exposure": 1}}]}, tmp / "gray.png", tmp / f"gray_{renderer}.png")
        ratio = float(srgb_to_linear(out).mean() / srgb_to_linear(gray).mean())
        check("exposure +1 doubles linear light", abs(ratio - 2) < 0.03, f"ratio {ratio:.3f}")

    print("[diagnostics]")
    _diagnostics(tmp)

    print("[models]")
    _object_mask()
    _heal()

    rect = develop.crop_rect(1000, 1500, {"aspect": "4:5", "focus": [0.5, 0.3], "focus_at": [0.5, 0.33]}, None)
    check("crop 4:5 geometry", rect[2] == 1000 and rect[3] == 1250 and rect[1] == 38, str(rect))

    print("\nALL PASSED" if not FAILS else f"\nFAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


def _findings(tmp, name, img):
    import feedready

    path = tmp / f"{name}.png"
    save_png16(img, path)

    class Args:
        image = str(path)

    found = {}
    for f in feedready.cmd_inspect(Args())["diagnostics"]["findings"]:
        found.setdefault(f["check"], f)
    return found


def _diagnostics(tmp):
    dark = np.full((400, 600, 3), 0.08, np.float32)
    dark[300:306, 450:470] = 0.9
    dark += np.random.default_rng(1).normal(0, 0.01, dark.shape).astype(np.float32)
    spots = _findings(tmp, "spot", dark.clip(0, 1)).get("distractions")
    check("distractions finds the lone bright strip",
          spots is not None and spots["evidence"]["spots"][0][:2] == [0.766, 0.756], str(spots and spots["evidence"]))

    gray = np.full((400, 600, 3), 0.5, np.float32)
    gray[200:] = 0.6
    warm = develop.np_apply_op(gray, {"op": "matrix", "r": 1.12, "g": 1.0, "b": 0.9})
    cast = _findings(tmp, "warm", warm).get("color_cast")
    check("color_cast proposes cooling a warm cast", cast is not None and cast["step"]["adjust"].get("temp", 0) < -8,
          str(cast and cast["step"]))

    under = _findings(tmp, "under", card() * 0.25).get("exposure")
    check("exposure proposes brightening an underexposed photo", under is not None and under["step"]["adjust"].get("exposure", 0) > 0,
          str(under and under["step"]))

    clean = _findings(tmp, "clean", card())
    check("a well-exposed neutral card gets no exposure or cast findings",
          "exposure" not in clean and "color_cast" not in clean, str(sorted(clean)))


def _iou(m, truth):
    b = m > 0.5
    return float((b & truth).sum() / (b | truth).sum())


def _object_mask():
    if not edgetam_available():
        print("  skip object mask (EdgeTAM model not installed)")
        return
    img = 0.1 + np.random.default_rng(2).normal(0, 0.03, (400, 600, 3)).astype(np.float32)
    img[120:260, 200:380] = (0.9, 0.3, 0.1)
    truth = np.zeros((400, 600), bool)
    truth[120:260, 200:380] = True
    scene = Scene(None, None, img.clip(0, 1))
    iou = _iou(masks.build({"type": "object", "box": [190 / 600, 110 / 400, 390 / 600, 270 / 400]}, scene), truth)
    check("object mask from a box finds the rectangle", iou >= 0.9, f"iou {iou:.3f}")
    iou = _iou(masks.build({"type": "object", "points": [[290 / 600, 190 / 400]]}, scene), truth)
    check("object mask from one click finds the rectangle", iou >= 0.8, f"iou {iou:.3f}")


def _heal():
    import detect
    from imaging import cv2

    h, w = 400, 600
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    clean = np.stack([0.3 + 0.3 * xx / w, 0.35 + 0.2 * yy / h, np.full((h, w), 0.45, np.float32)], -1)
    clean = (clean + gaussian(np.random.default_rng(3).normal(0, 0.02, (h, w, 3)).astype(np.float32), 1)).clip(0, 1)
    spotted = clean.copy()
    spotted[190:210, 290:310] = 0.98
    mask = np.zeros((h, w), np.float32)
    mask[186:214, 286:314] = 1
    backends = [("mi-gan", migan_available()), ("opencv fsr", cv2 is not None and hasattr(cv2, "xphoto"))]
    saved = detect.MIGAN
    for name, available in backends:
        if not available:
            print(f"  skip heal ({name} not installed)")
            continue
        healed = develop.heal(spotted, mask)
        inside = float(np.abs(healed[190:210, 290:310] - clean[190:210, 290:310]).mean())
        outside = float(np.abs(healed[:150] - spotted[:150]).max())
        check(f"heal ({name}) fills the blob from its surroundings", inside < 0.05, f"mean abs diff {inside:.3f}")
        check(f"heal ({name}) leaves the rest untouched", outside <= 1.5 / 255, f"max err {outside * 255:.2f}/255")
        detect.MIGAN = Path("/nonexistent")  # next backend down the chain
    detect.MIGAN = saved


def _apply(renderer, recipe, src, out):
    if renderer == "core-image":
        return run("apply", recipe, src, out)
    import feedready  # in-process so the forced fallback applies

    class Args:
        pass

    args = Args()
    args.recipe, args.image, args.output = json.dumps(recipe), str(src), str(out)
    feedready.tier = lambda: "basic"
    feedready.cmd_apply(args)
    return load_rgb(out)


if __name__ == "__main__":
    main()
