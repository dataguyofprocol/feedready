from __future__ import annotations

import json

import numpy as np
from PIL import Image

import lib
import critique
import develop
import diagnose
import imaging
import masks
import recrops
import review
from detect import Scene
from imaging import (
    box_blur,
    gaussian,
    hsv_to_rgb,
    icc_profile,
    linear_to_srgb,
    load_rgb,
    luma,
    min_filter,
    resize,
    rgb_to_hsv,
    skin_mask,
    smoothstep,
    srgb_to_linear,
    to_u8,
)

LOOKS_SNAPSHOT = {
    "natural": {"contrast": 8, "whites": 10, "blacks": -8, "vibrance": 12},
    "bright-airy": {
        "exposure": 0.3, "contrast": -12, "highlights": -25, "shadows": 30, "whites": 12, "blacks": 10,
        "saturation": -8, "temp": 4,
        "hsl": {"orange": {"lum": 6}, "green": {"sat": -20, "lum": 10}, "blue": {"sat": -10, "lum": 10}},
    },
    "warm-golden": {
        "temp": 18, "tint": 4, "contrast": 8, "highlights": -15, "shadows": 10, "vibrance": 15,
        "hsl": {"orange": {"sat": 8, "lum": 4}, "yellow": {"hue": -8, "sat": 10}, "green": {"hue": -10, "sat": -15},
                "blue": {"sat": -20}},
        "curve": [[0, 0.03], [0.5, 0.52], [1, 0.98]],
    },
    "moody": {
        "exposure": -0.25, "contrast": 18, "highlights": -35, "shadows": -10, "blacks": -10, "saturation": -18,
        "clarity": 10, "temp": -4,
        "hsl": {"orange": {"sat": -5}, "yellow": {"sat": -30}, "green": {"hue": 15, "sat": -40, "lum": -20},
                "aqua": {"sat": -20}, "blue": {"sat": -25, "lum": -20}},
        "curve": [[0, 0.05], [0.25, 0.2], [0.75, 0.75], [1, 0.96]],
    },
    "film": {
        "contrast": -5, "saturation": -12, "temp": 6, "tint": 3,
        "hsl": {"red": {"hue": 5}, "orange": {"sat": -5}, "green": {"hue": 20, "sat": -25}, "blue": {"hue": -10, "sat": -15}},
        "curve": [[0, 0.07], [0.25, 0.26], [0.75, 0.76], [1, 0.94]],
    },
    "cinematic": {
        "contrast": 15, "highlights": -25, "temp": -6, "vibrance": 10,
        "hsl": {"orange": {"hue": -4, "sat": 12}, "yellow": {"hue": -15, "sat": -10}, "green": {"hue": 40, "sat": -35},
                "blue": {"hue": -25, "sat": 10, "lum": -10}},
        "curve": [[0, 0.04], [0.3, 0.26], [0.7, 0.74], [1, 0.97]],
    },
    "punchy": {"contrast": 25, "whites": 15, "blacks": -18, "clarity": 18, "texture": 10, "vibrance": 28},
    "rim-backlit": {
        "exposure": -0.1, "contrast": 16, "highlights": -20, "shadows": -12, "blacks": -12, "whites": 8,
        "temp": 10, "vibrance": 14,
        "hsl": {"orange": {"sat": 12, "lum": 6}, "yellow": {"sat": 10}, "blue": {"sat": -18, "lum": -12},
                "aqua": {"sat": -12}},
        "curve": [[0, 0.02], [0.3, 0.25], [0.7, 0.73], [1, 0.97]],
    },
    "neon-night": {
        "exposure": -0.15, "contrast": 20, "highlights": -18, "shadows": 12, "blacks": -8, "temp": -8,
        "vibrance": 18, "saturation": -6,
        "hsl": {"orange": {"sat": 14, "lum": 4}, "magenta": {"sat": 18}, "purple": {"sat": 12},
                "blue": {"hue": -12, "sat": 14, "lum": -8}, "aqua": {"hue": 10, "sat": 10}},
        "curve": [[0, 0.03], [0.25, 0.2], [0.75, 0.78], [1, 0.96]],
    },
    "overcast-soft": {
        "contrast": -8, "highlights": -12, "shadows": 18, "blacks": 6, "whites": 10, "temp": 4, "vibrance": 16,
        "hsl": {"green": {"sat": -14, "lum": 8}, "blue": {"sat": -8, "lum": 8}, "orange": {"sat": 8, "lum": 6}},
        "curve": [[0, 0.04], [0.5, 0.52], [1, 0.99]],
    },
    "mono": {
        "saturation": -100, "contrast": 22, "whites": 12, "blacks": -15, "clarity": 12,
        "hsl": {"orange": {"lum": 15}, "red": {"lum": 8}, "blue": {"lum": -25}, "aqua": {"lum": -15}, "green": {"lum": -10}},
    },
}

SLIDERS_SNAPSHOT = {
    "exposure": (-5, 5, "stops"),
    "contrast": (-100, 100, ""),
    "highlights": (-100, 100, ""),
    "shadows": (-100, 100, ""),
    "whites": (-100, 100, ""),
    "blacks": (-100, 100, ""),
    "temp": (-100, 100, "+ warmer"),
    "tint": (-100, 100, "+ magenta"),
    "vibrance": (-100, 100, ""),
    "saturation": (-100, 100, ""),
    "texture": (-100, 100, ""),
    "clarity": (-100, 100, ""),
    "dehaze": (-100, 100, ""),
    "sharpen": (0, 150, ""),
}

HSL_BANDS_SNAPSHOT = {"red": 0, "orange": 30, "yellow": 60, "green": 120, "aqua": 180, "blue": 240, "purple": 280,
                      "magenta": 320}

PRESETS_SNAPSHOT = {
    "instagram": {"aspect": (4, 5)},
    "story": {"aspect": (9, 16)},
    "linkedin": {"aspect": (1, 1)},
    "original": {"aspect": None},
}


def test_tables():
    lib.check("looks snapshot", develop.LOOKS == LOOKS_SNAPSHOT)
    lib.check("sliders snapshot", develop.SLIDERS == SLIDERS_SNAPSHOT)
    lib.check("hsl bands snapshot", develop.HSL_BANDS == HSL_BANDS_SNAPSHOT)
    lib.check("presets snapshot", develop.PRESETS == PRESETS_SNAPSHOT)


def test_color_math():
    rng = np.random.default_rng(1)
    x = rng.random((40, 60, 3)).astype(np.float32)
    lib.check("srgb linear roundtrip", np.allclose(linear_to_srgb(srgb_to_linear(x)), x, atol=1e-6))
    lib.check("srgb breakpoint continuity",
              abs(float(srgb_to_linear(np.float32(0.04045))) - 0.04045 / 12.92) < 1e-6
              and abs(float(srgb_to_linear(np.float32(0.04046))) - float(srgb_to_linear(np.float32(0.04045)))) < 1e-5)
    lib.check("luma weights", luma(np.array([1.0, 0, 0])) == 0.2126 and luma(np.array([0, 1.0, 0])) == 0.7152
              and luma(np.array([0, 0, 1.0])) == 0.0722)
    h, s, v = rgb_to_hsv(np.array([[1.0, 0, 0], [0, 1.0, 1.0], [1.0, 0, 1.0], [0.5, 0.5, 0.5]]))
    lib.check("hsv hues", list(h) == [0, 180, 300, 0] and list(s[:3]) == [1, 1, 1] and s[3] == 0 and v[3] == 0.5)
    lib.check("hsv roundtrip", np.allclose(hsv_to_rgb(*rgb_to_hsv(x)), x, atol=1e-6))
    lib.check("smoothstep midpoint and clamp", smoothstep(0, 1, 0.5) == 0.5 and smoothstep(0, 1, -1) == 0
              and smoothstep(0, 1, 2) == 1)
    lib.check("to_u8 rounding", to_u8(np.array([1.0, 0.0, 0.5, -0.2])).tolist() == [255, 0, 128, 0])
    lib.check("sharma ciede2000 vectors",
              max(abs(float(lib.de2000_lab(np.array([[a]], float), np.array([[b]], float)).reshape(())) - want)
                  for a, b, want in lib.SHARMA) < 1e-3)


def test_io():
    tmp = lib.tmp()
    img = lib.card()
    p16 = tmp / "round16.png"
    imaging.save_png16(img, p16)
    lib.check("png16 roundtrip", np.allclose(load_rgb(p16), img, atol=1e-4))
    lib.check("png16 is 16 bit", (p16.read_bytes()[24] == 16))
    p8 = tmp / "round8.png"
    saved, imaging.cv2 = imaging.cv2, None
    imaging.save_png16(img, p8)
    imaging.cv2 = saved
    lib.check("png8 fallback roundtrip", np.allclose(load_rgb(p8), img, atol=1 / 255))
    picc = tmp / "icc.png"
    imaging.save_png16(img, picc, b"fake-profile-bytes")
    lib.check("icc embed roundtrip", icc_profile(picc) == b"fake-profile-bytes")


def test_filter_branches():
    ramp = np.tile(np.linspace(0, 1, 200, dtype=np.float32)[:, None], (1, 200))
    saved, imaging.cv2 = imaging.cv2, None
    g_fallback = imaging.gaussian(ramp.copy(), 2.0)
    b_fallback = imaging.box_blur(ramp.copy(), 3)
    m_fallback = imaging.min_filter(np.pad(ramp, 0), 2)
    r_fallback = imaging.resize(ramp.copy(), 100, 100)
    imaging.cv2 = saved
    lib.check("gaussian branch parity", np.allclose(g_fallback[10:-10, 10:-10], gaussian(ramp, 2.0)[10:-10, 10:-10],
                                                    atol=5e-3))
    lib.check("box blur branch parity", np.allclose(b_fallback[10:-10, 10:-10], box_blur(ramp, 3)[10:-10, 10:-10],
                                                    atol=1e-5))
    lib.check("min filter branch parity", np.allclose(m_fallback[4:-4, 4:-4], min_filter(ramp, 2)[4:-4, 4:-4],
                                                      atol=1e-6))
    lib.check("resize branch parity", np.allclose(r_fallback[5:-5, 5:-5], resize(ramp, 100, 100)[5:-5, 5:-5],
                                                  atol=5e-3))


def test_look_math():
    half = develop.step_adjust({"look": "moody", "amount": 50})
    lib.check("look amount scales the grade", abs(half["exposure"] + 0.125) < 1e-9
              and half["hsl"]["green"]["sat"] == -20)
    over = develop.step_adjust({"look": "moody", "adjust": {"exposure": 0.1, "hsl": {"green": {"lum": 5}}}})
    lib.check("adjust overrides the look and merges hsl bands", over["exposure"] == 0.1
              and over["hsl"]["green"] == {"hue": 15, "sat": -40, "lum": 5})
    zero = develop.step_adjust({"look": "film", "amount": 0})
    lib.check("amount 0 is a no-op curve", all(abs(x - y) < 1e-9 for x, y in zero["curve"]))
    lib.check("amount clamps at 200", develop.step_adjust({"look": "natural", "amount": 500})["contrast"] == 16)
    try:
        develop.step_adjust({"look": "vaporwave"})
        lib.check("unknown look is rejected", False)
    except ValueError as e:
        lib.check("unknown look is rejected", "vaporwave" in str(e) and "moody" in str(e))
    clamped = {"exposure": 9, "sharpen": 400, "bogus": 1, "hsl": {"teal": {"sat": -10}}}
    warnings = develop.validate(clamped)
    lib.check("validate clamps and warns", clamped["exposure"] == 5 and clamped["sharpen"] == 150
              and any("exposure" in w for w in warnings) and any("bogus" in w for w in warnings)
              and any("teal" in w for w in warnings))


def test_tone_curves():
    lib.check("no tonal keys gives no lut", develop.tone_lut({}) is None
              and develop.tone_lut({"exposure": 1, "vibrance": 50}) is None)
    lut = develop.tone_lut({"contrast": 100})
    lib.check("contrast anchors endpoints and midpoint", lut[0] == 0 and abs(lut[-1] - 1) < 1e-6
              and abs(lut[512] - 0.5) < 2e-3)
    lib.check("contrast lut is monotone", bool((np.diff(lut) >= -1e-7).all()))
    soft = develop.tone_lut({"contrast": -100})
    lib.check("negative contrast pulls toward mid grey", abs(soft[0] - 0.225) < 1e-5
              and abs(soft[-1] - 0.775) < 1e-5 and abs(soft[512] - 0.5) < 2e-3)
    x = np.linspace(0, 1, develop.LUT_SIZE)
    hi = develop.tone_lut({"highlights": 100})
    lib.check("highlights bump peaks at 0.72", hi[737] - x[737] > 0.11 and hi[900] - x[900] < 0.05
              and hi[500] - x[500] < 0.03)
    w = develop.tone_lut({"whites": 100})
    lib.check("whites lift the top", w[-1] == 1 and w[900] > 0.9)
    b = develop.tone_lut({"blacks": -100})
    lib.check("blacks pull the bottom", b[0] == 0 and b[200] < 0.2)
    curved = develop.tone_lut({"curve": [[0, 0.05], [1, 0.95]]})
    lib.check("curve passes through its points", abs(curved[0] - 0.05) < 1e-5 and abs(curved[-1] - 0.95) < 1e-5)
    mono = develop._monotone_cubic([(0, 0), (1, 1), (2, 4)], np.array([0.0, 0.5, 1.0, 1.5, 2.0]))
    lib.check("monotone cubic passes through points", mono[2] == 1 and mono[4] == 4
              and bool((np.diff(mono) >= -1e-9).all()))
    lib.check("monotone cubic handles a single point", develop._monotone_cubic([(5, 5)], np.array([0.3])) == 0.3)


def test_white_balance():
    lib.check("zero wb gives no gains", develop.wb_gains({"temp": 0, "tint": 0}) is None)
    r, g, b = develop.wb_gains({"temp": 100})
    lib.check("warm temp boosts red over blue", r > 1 > b)
    lib.check("wb gains are luma normalized", abs(0.2126 * r + 0.7152 * g + 0.0722 * b - 1) < 1e-6)
    r, g, b = develop.wb_gains({"tint": 100})
    lib.check("green tint pulls green down evenly", g < 1 and abs(r - b) < 1e-9)


def test_hsl():
    blue = np.full((10, 10, 3), (0.0, 0.0, 1.0), np.float32)
    out = develop.apply_hsl(blue, {"blue": {"sat": -100}})
    lib.check("hsl desaturates the target band", np.allclose(out, 1.0, atol=1e-6))
    red = np.full((10, 10, 3), (1.0, 0.0, 0.0), np.float32)
    out = develop.apply_hsl(red, {"red": {"hue": 30}})
    lib.check("hsl hue shifts by 0.3x degrees", abs(float(out[..., 1].mean()) - 0.15) < 1e-5
              and abs(float(out[..., 0].mean()) - 1) < 1e-5)
    card = lib.card()
    out = develop.apply_hsl(card, {"blue": {"sat": -100}})
    lib.check("hsl leaves other bands untouched",
              np.allclose(out[250:330, 20:100], card[250:330, 20:100], atol=1e-5))
    cube = develop.hsl_cube({})
    g = np.linspace(0, 1, 32, dtype=np.float32)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)[:, ::-1]
    lib.check("identity hsl cube", cube.shape == (32 ** 3, 4) and np.allclose(cube[:, 3], 1)
              and np.allclose(cube[:, :3], grid, atol=1e-5))
    cube = develop.hsl_cube({"red": {"sat": -100}})
    red_corner = cube[np.argmax(np.sum(grid > 0.99, 1))]
    lib.check("hsl cube transforms the red corner", np.allclose(red_corner[:3], 1.0, atol=1e-4))


def test_build_ops():
    ops = develop.build_ops({"exposure": 0.5}, 1600)
    lib.check("exposure only builds one op", ops == [{"op": "exposure", "ev": 0.5}])
    full = {"temp": 10, "tint": -10, "exposure": 0.3, "shadows": 20, "highlights": -20, "contrast": 10,
            "whites": 10, "blacks": -10, "hsl": {"blue": {"sat": -10}}, "vibrance": 10, "saturation": -10,
            "sharpen": 10}
    ops = develop.build_ops(full, 1600)
    lib.check("op order matches the engine contract", [o["op"] for o in ops] ==
              ["matrix", "exposure", "highlight_shadow", "curves", "cube", "vibrance", "saturation", "sharpen"])
    hs = next(o for o in ops if o["op"] == "highlight_shadow")
    lib.check("highlight shadow scales and clamps", hs["shadow"] == 0.2 and hs["highlight"] == 0.8
              and hs["radius"] == 6.4)
    sharpen = next(o for o in ops if o["op"] == "sharpen")
    lib.check("sharpen radius scales with the long edge", sharpen["radius"] == 1.5
              and develop.build_ops({"sharpen": 10}, 6000)[0]["radius"] == 3.0)
    lib.check("unknown op is rejected", True)
    try:
        develop.np_apply_op(np.zeros((4, 4, 3), np.float32), {"op": "quantum"})
        lib.check("np_apply_op rejects unknown ops", False)
    except ValueError:
        lib.check("np_apply_op rejects unknown ops", True)


def test_crop():
    rect = develop.crop_rect(1000, 1500, {"aspect": "4:5", "focus": [0.5, 0.3], "focus_at": [0.5, 0.33]}, None)
    lib.check("crop 4:5 geometry", rect[2] == 1000 and rect[3] == 1250 and rect[1] == 38, str(rect))
    lib.check("parse aspect accepts x and :", develop.parse_aspect("4x5") == (4.0, 5.0)
              and develop.parse_aspect("16:9") == (16.0, 9.0) and develop.parse_aspect(None) is None)
    lib.check("crop box is clamped to the photo", develop.crop_rect(100, 100, {"box": [-0.5, 0.2, 1.5, 0.8]}, None)
              == (0, 20, 100, 60))
    try:
        develop.crop_rect(100, 100, {"box": [0.5, 0.2, 0.4, 0.8]}, None)
        lib.check("empty crop box is rejected", False)
    except ValueError:
        lib.check("empty crop box is rejected", True)
    lib.check("crop zoom and focus land where asked",
              develop.crop_rect(2000, 1000, {"aspect": "1:1", "scale": 0.1, "focus": [0.1, 0.1], "focus_at": [0, 0]},
                                None) == (200, 100, 100, 100))
    lib.check("crop stays inside the frame",
              all(0 <= r[0] and 0 <= r[1] and r[0] + r[2] <= 2000 and r[1] + r[3] <= 1000
                  for r in (develop.crop_rect(2000, 1000, {"aspect": "9:16", "focus": [f, 0.5]}, None)
                            for f in (0.0, 0.3, 0.5, 0.9, 1.0))))
    lib.check("no aspect means no crop", develop.crop_rect(100, 100, None, None) is None)


def test_mask_geometry():
    img = np.zeros((400, 600, 3), np.float32)
    scene = Scene(None, None, img)
    lib.check("none and all build no mask", masks.build(None, scene) is None
              and masks.build({"type": "all"}, scene) is None)
    m = masks.build({"type": "radial", "center": [0.5, 0.5], "radius": 0.2}, scene)
    lib.check("radial peaks at the centre and dies at the corner", m.shape == (400, 600)
              and m[200, 300] > 0.99 and m[5, 5] < 0.01)
    rot = masks.build({"type": "radial", "center": [0.5, 0.5], "radius": [0.2, 0.05], "angle": 90}, scene)
    swap = masks.build({"type": "radial", "center": [0.5, 0.5], "radius": [0.05, 0.2]}, scene)
    lib.check("radial angle rotates the ellipse", np.allclose(rot, swap, atol=1e-5))
    m = masks.build({"type": "linear", "start": [0.0, 0.5], "end": [1.0, 0.5]}, scene)
    lib.check("linear fades start to end", m[:, 0].mean() > 0.99 and m[:, -1].mean() < 0.01)
    m = masks.build({"type": "polygon", "points": [[0.3, 0.3], [0.7, 0.3], [0.5, 0.8]]}, scene)
    lib.check("polygon fills inside only", m[250, 300] > 0.9 and m[10, 10] < 0.01)
    m = masks.build({"type": "brush", "dots": [[0.5, 0.5]]}, scene)
    lib.check("brush dot defaults to size 0.02", m[200, 300] > 0.9 and float((m > 0.5).sum()) < 0.02 * 600 * 400)
    half = img.copy()
    half[:, 300:] = 1.0
    m = masks.build({"type": "luminance", "min": 0.6, "max": 1.0}, Scene(None, None, half))
    lib.check("luminance selects the bright half", m[:, 400:].mean() > 0.9 and m[:, :100].mean() < 0.1)
    blue = np.zeros((100, 100, 3), np.float32)
    blue[..., 2] = 1.0
    m = masks.build({"type": "color", "hue": 240, "range": 25}, Scene(None, None, blue))
    grey = masks.build({"type": "color", "hue": 240, "range": 25}, Scene(None, None, np.full((100, 100, 3), 0.5, np.float32)))
    lib.check("color mask gates on hue and saturation", m.mean() > 0.9 and grey.mean() < 0.05)
    left = {"type": "radial", "center": [0.25, 0.5], "radius": 0.15}
    right = {"type": "radial", "center": [0.75, 0.5], "radius": 0.15}
    a = masks.build(left, scene)
    lib.check("union takes the max", np.allclose(masks.build({"op": "union", "masks": [left, right]}, scene),
                                                 np.maximum(a, masks.build(right, scene))))
    lib.check("subtract removes the second", np.allclose(masks.build({"op": "subtract", "masks": [left, right]}, scene),
                                                         a * (1 - masks.build(right, scene))))
    lib.check("intersect of disjoint masks is empty", masks.build({"op": "intersect", "masks": [left, right]},
                                                                  scene).mean() < 0.01)
    lib.check("invert flips", np.allclose(masks.build({**left, "invert": True}, scene), 1 - a, atol=1e-6))
    lib.check("strength scales", np.allclose(masks.build({**left, "strength": 0.5}, scene), a * 0.5, atol=1e-6))
    small = masks.build({"type": "radial", "center": [0.5, 0.5], "radius": 0.05}, scene)
    grown = masks.build({"type": "radial", "center": [0.5, 0.5], "radius": 0.05, "grow": 0.05}, scene)
    lib.check("grow dilates", float((grown > 0.5).sum()) > float((small > 0.5).sum()) * 2)
    try:
        masks.build({"type": "torus"}, scene)
        lib.check("unknown mask type is rejected", False)
    except ValueError as e:
        lib.check("unknown mask type is rejected", "torus" in str(e))
    faces_scene = Scene(None, None, img)
    faces_scene._vision = {"faces": [{"box": [0.4, 0.3, 0.6, 0.5]}]}
    m = masks.build({"type": "face"}, faces_scene)
    lib.check("face mask centres on the face box", m[160, 300] > 0.9 and m[40, 300] < 0.05)


def test_critique_units():
    lib.check("impact levels have thresholds", critique.level(0.001) == "none" and critique.level(0.006) == "subtle"
              and critique.level(0.02) == "clear" and critique.level(0.05) == "strong")
    img = lib.card()
    imp = critique.impact(img, img, None)
    lib.check("identical images have no impact", imp["delta"] == 0 and imp["level"] == "none" and imp["reach"] == 1)
    mask = np.zeros((400, 600), np.float32)
    mask[:, :100] = 1
    imp = critique.impact(img, img * 0.2, mask)
    lib.check("impact reach follows the mask", abs(imp["reach"] - 100 / 600) < 0.01 and imp["delta"] > 0.05)
    lib.check("level fill covers every level",
              set(review.LEVEL_FILL) == {name for _, name in critique.LEVELS} | {"strong"})


def test_review_units():
    lib.check("describe renders looks amounts and sliders",
              review.describe({"exposure": 0.4}) == "exposure +0.4"
              and review.describe({}, "warm-golden", 70) == "look warm-golden 70%"
              and review.describe({}, "mono") == "look mono"
              and review.describe({"hsl": {"blue": {"sat": -20}}, "heal": True}) == "hsl blue, heal"
              and review.describe({}) == "no change")
    m = np.zeros((100, 100), np.float32)
    m[30:50, 40:60] = 1
    x0, y0, x1, y1 = review._lens(m, 100, 100)
    lib.check("lens frames the mask as a padded square", x0 <= 40 and x1 >= 60 and y0 <= 30 and y1 >= 50
              and (x1 - x0) == (y1 - y0) and review._lens(None, 100, 100) == (0, 0, 100, 100))
    lib.check("lens keeps small masks at a quarter minimum", (x1 - x0) >= 25)


def test_opportunities():
    hard = np.full((400, 600, 3), 0.12, np.float32)
    hard[:, 300:] = 0.95
    soft = np.full((400, 600, 3), 0.45, np.float32)
    rng = np.random.default_rng(3)
    soft += gaussian(rng.normal(0, 0.02, (400, 600)).astype(np.float32), 2)[..., None]
    st_hard, st_soft = diagnose._light_stats(hard), diagnose._light_stats(soft)
    lib.check("light stats separate hard from soft",
              st_hard["quality"] == "hard" and st_hard["direction"] == "right"
              and st_soft["quality"] == "soft" and st_soft["direction"] == "even")
    warm = np.full((400, 600, 3), 0.25, np.float32)
    warm[:200] = (1.0, 0.85, 0.6)
    warm[200:] = (0.2, 0.25, 0.45)
    lib.check("warm split reads highlights against shade", diagnose._light_stats(warm)["warm_split"] >= 0.5)
    pair = np.full((400, 600, 3), 0.2, np.float32)
    pair[:, :300] = (0.95, 0.45, 0.1)
    pair[:, 300:] = (0.1, 0.65, 0.7)
    out = diagnose.colour_pairs(Scene(None, None, pair))
    lib.check("colour pairs finds orange on aqua",
              out and out[0]["evidence"]["names"] == ["orange", "aqua"])
    quiet = np.full((400, 600, 3), 0.4, np.float32)
    quiet[100:160, 250:350] = (0.8, 0.1, 0.1)
    out = diagnose.colour_pairs(Scene(None, None, quiet))
    lib.check("colour pairs flags a lone accent", out and out[0]["evidence"]["accent"] == "red")
    field = np.full((400, 600, 3), 0.18, np.float32)
    field[60:140, 60:180] = 0.6
    scene = Scene(None, None, field)
    scene._vision = {"faces": []}
    out = diagnose.eye_path(scene)
    lib.check("eye path seals when the hero owns the eye",
              out and out[0]["evidence"]["rival_ratio"] <= 0.6)
    field[240:320, 420:540] = 1.0
    scene = Scene(None, None, field)
    scene._vision = {"faces": [{"box": [0.1, 0.15, 0.3, 0.35]}]}
    out = diagnose.eye_path(scene)
    lib.check("eye path flags a rival that out-pulls the face",
              out and out[0]["evidence"]["rival_ratio"] >= 1.0)
    work = lib.tmp() / "sep"
    (work / "vision").mkdir(parents=True, exist_ok=True)
    pmask = np.zeros((200, 300), np.float32)
    pmask[60:140, 110:190] = 1.0
    imaging.save_mask(pmask, work / "vision" / "person.png")
    lit = np.full((200, 300, 3), 0.1, np.float32)
    lit[60:140, 110:190] = 0.85
    scene = Scene(work, None, lit)
    scene._vision = {}
    out = diagnose.separation_potential(scene)
    lib.check("separation potential sees the lit subject", out and "more light" in out[0]["finding"])
    dark = np.full((200, 300, 3), 0.75, np.float32)
    dark[60:140, 110:190] = 0.08
    scene = Scene(work, None, dark)
    scene._vision = {}
    out = diagnose.separation_potential(scene)
    lib.check("separation potential sees the silhouette", out and "silhouette" in out[0]["finding"])


def test_recrops():
    img = np.full((600, 900, 3), 0.15, np.float32)
    img[150:350, 520:760] = 0.9
    img[180:260, 590:670] = 1.0
    scene = Scene(None, None, img)
    scene._vision = {"faces": [{"box": [0.62, 0.26, 0.78, 0.44]}]}
    out = recrops.mine(scene)
    lib.check("recrops stay inside the frame",
              1 <= len(out) <= 3
              and all(0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1 for b in (r["box"] for r in out)))
    top = out[0]
    face = scene.faces()[0]["box"]
    inside = (top["box"][0] <= face[0] and top["box"][1] <= face[1]
              and top["box"][2] >= face[2] and top["box"][3] >= face[3])
    lib.check("recrops find the off-centre subject",
              inside and top["evidence"].get("face_height_share", 0) >= 0.2)
    lib.check("recrops rank and diversify",
              all(out[i]["score"] >= out[i + 1]["score"] for i in range(len(out) - 1))
              and all(recrops._iou(out[i]["box"], out[j]["box"]) <= 0.55
                      for i in range(len(out)) for j in range(i + 1, len(out))))
    small = Scene(None, None, np.zeros((200, 300, 3), np.float32))
    small._vision = {"faces": []}
    lib.check("no recrops below the resolution floor", recrops.mine(small) == [])


def test_taste():
    import feedready

    root = lib.tmp() / "work"
    w = root / "photo-abc12345"
    (w / "versions").mkdir(parents=True)
    (w / "versions" / "v1.json").write_text(json.dumps({"preset": "instagram", "steps": [
        {"name": "grade", "look": "moody", "amount": 80},
        {"name": "lift", "adjust": {"exposure": 0.4}}]}))
    (w / "versions" / "v2.json").write_text(json.dumps({"preset": "instagram", "vignette": -15, "steps": [
        {"name": "grade", "look": "moody", "amount": 120},
        {"name": "warm", "adjust": {"temp": 10}}]}))
    (w / "versions" / "index.json").write_text(json.dumps({"1": {"note": "warmer"}, "2": {"note": "ship it"}}))
    t = feedready.taste(root)
    lib.check("taste weights the final version double",
              t["photos_edited"] == 1 and t["look_use"]["moody"]["times"] == 3
              and t["look_use"]["moody"]["median_amount"] == 120
              and t["presets"]["instagram"] == 3 and t["vignette_use"] == 2
              and t["slider_medians"]["exposure"] == 0.4 and t["slider_medians"]["temp"] == 10)
    lib.check("taste keeps the note vocabulary", t["recent_notes"] == ["warmer", "ship it"])
    lib.check("taste stays empty without history", feedready.taste(lib.tmp() / "nothing") == {})


def test_cli_pure():
    import feedready

    gray = np.full((60, 80, 3), 0.5, np.float32)
    st = feedready.stats(gray)
    lib.check("stats on flat gray", st["mean_luma"] == 0.5 and st["clipped_highlights_pct"] == 0
              and st["crushed_shadows_pct"] == 0 and st["p01_p99_luma"] == [0.5, 0.5])
    lib.check("version refs parse", bool(feedready.VERSION.fullmatch("v3") and feedready.VERSION.fullmatch("V12"))
              and not feedready.VERSION.fullmatch("vv3") and not feedready.VERSION.fullmatch("v"))
    skin = np.full((300, 300, 3), 0.85, np.float32)
    skin[90:150, 120:180] = (0.45, 0.3, 0.22)
    lib.check("skin mask gates on share", skin_mask(skin, [0.4, 0.3, 0.6, 0.5]) is not None
              and skin_mask(np.full((300, 300, 3), 0.1, np.float32), [0.3, 0.3, 0.7, 0.7]) is None)


def run():
    test_tables()
    test_color_math()
    test_io()
    test_filter_branches()
    test_look_math()
    test_tone_curves()
    test_white_balance()
    test_hsl()
    test_build_ops()
    test_crop()
    test_mask_geometry()
    test_critique_units()
    test_review_units()
    test_opportunities()
    test_recrops()
    test_taste()
    test_cli_pure()
