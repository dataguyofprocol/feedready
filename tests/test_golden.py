from __future__ import annotations

import json

import numpy as np

import lib
import imaging

FIXTURES = [
    ("card-natural", lib.card, {"steps": [{"look": "natural"}]}),
    ("card-warm-golden-70", lib.card, {"steps": [{"look": "warm-golden", "amount": 70}], "vignette": -15}),
    ("card-moody", lib.card, {"steps": [{"look": "moody"}]}),
    ("card-mono", lib.card, {"steps": [{"look": "mono"}]}),
    ("card-regions", lib.card, {"preset": "instagram", "steps": [
        {"name": "grade", "look": "cinematic", "amount": 80},
        {"name": "lift left", "mask": {"type": "linear", "start": [0, 0.5], "end": [0.5, 0.5]},
         "adjust": {"exposure": 0.4, "shadows": 20}},
        {"name": "calm blue", "mask": {"type": "color", "hue": 240, "range": 25}, "adjust": {"saturation": -30}},
    ]}),
    ("hazy-dehaze", lib.hazy_card, {"steps": [{"adjust": {"dehaze": 60}}]}),
    ("checker-grade", lib.checker, {"steps": [
        {"name": "film", "look": "film", "amount": 90},
        {"name": "cool", "adjust": {"temp": -20, "tint": 10, "hsl": {"red": {"sat": -15}, "blue": {"hue": -10}}}},
    ]}),
    ("checker-vibrance", lib.checker, {"steps": [{"name": "pop", "adjust": {"vibrance": 50, "shadows": 25}}]}),
]


def render(fixture, recipe, name):
    src = lib.tmp() / f"golden-{name}.png"
    imaging.save_png16(fixture(), src)
    return lib.apply_np(recipe, src, lib.tmp() / f"golden-out-{name}.png")


def run():
    if imaging.cv2 is None:
        lib.skip("golden (recorded with the cv2 branches; install opencv to compare)")
        return
    index_path = lib.GOLDEN / "goldens.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for name, fixture, recipe in FIXTURES:
        out = render(fixture, recipe, name)
        if lib.REGEN:
            lib.save_golden(name, out, {"fixture": fixture.__name__, "recipe": recipe,
                                        "shape": list(out.shape)})
            print(f"  regen {name}")
            continue
        if name not in index:
            lib.check(f"golden {name} exists", False, "run with --regen to record")
            continue
        golden = lib.load_golden(name)
        frac, mx = lib.pixel_gate(out, golden)
        de = lib.de2000_stats(out, golden)
        lib.check(f"golden {name}", out.shape == golden.shape and frac >= 0.999 and de["mean"] < 1.0,
                  f"frac {frac:.5f} within 2/255, max {mx * 255:.0f}/255, dE {de['mean']:.3f}, "
                  f"psnr {lib.psnr(out, golden):.1f}dB")
    if lib.REGEN:
        fresh = json.loads(index_path.read_text())
        stale = set(fresh) - {n for n, _, _ in FIXTURES}
        for name in stale:
            del fresh[name]
            (lib.GOLDEN / f"{name}.png").unlink(missing_ok=True)
            print(f"  drop stale golden {name}")
        if stale:
            index_path.write_text(json.dumps(fresh, indent=2, sort_keys=True))
