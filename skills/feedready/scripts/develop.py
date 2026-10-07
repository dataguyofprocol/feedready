from __future__ import annotations

import numpy as np

from detect import MIGAN, migan_available
from imaging import (
    cv2,
    gaussian,
    guided_filter,
    hsv_to_rgb,
    linear_to_srgb,
    luma,
    min_filter,
    resize,
    rgb_to_hsv,
    smoothstep,
    srgb_to_linear,
    to_u8,
)

SLIDERS = {
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
HSL_BANDS = {"red": 0, "orange": 30, "yellow": 60, "green": 120, "aqua": 180, "blue": 240, "purple": 280, "magenta": 320}
PREPASS = ("heal", "dehaze", "texture", "clarity")
LUT_SIZE = 1024
CUBE_DIM = 32

LOOKS = {
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
    "mono": {
        "saturation": -100, "contrast": 22, "whites": 12, "blacks": -15, "clarity": 12,
        "hsl": {"orange": {"lum": 15}, "red": {"lum": 8}, "blue": {"lum": -25}, "aqua": {"lum": -15}, "green": {"lum": -10}},
    },
}


def _scale_look(look: dict, k: float) -> dict:
    out = {}
    for key, v in look.items():
        if key == "hsl":
            out[key] = {band: {p: q * k for p, q in vals.items()} for band, vals in v.items()}
        elif key == "curve":
            out[key] = [[x, x + (y - x) * k] for x, y in v]
        else:
            out[key] = v * k
    return out


def step_adjust(step: dict) -> dict:
    adjust = dict(step.get("adjust", {}))
    name = step.get("look")
    if not name:
        return adjust
    if name not in LOOKS:
        raise ValueError(f"unknown look '{name}'; use one of {list(LOOKS)}")
    amount = min(max(float(step.get("amount", 100)), 0), 200) / 100
    merged = _scale_look(LOOKS[name], amount)
    hsl = {band: dict(vals) for band, vals in merged.get("hsl", {}).items()}
    for band, vals in adjust.pop("hsl", {}).items():
        hsl.setdefault(band, {}).update(vals)
    merged.update(adjust)
    if hsl:
        merged["hsl"] = hsl
    return merged


def validate(adjust: dict) -> list[str]:
    warnings = []
    for k, v in list(adjust.items()):
        if k in SLIDERS:
            lo, hi, _ = SLIDERS[k]
            if not lo <= v <= hi:
                adjust[k] = min(max(v, lo), hi)
                warnings.append(f"{k}={v} clamped to {adjust[k]}")
        elif k == "hsl":
            for band in v:
                if band not in HSL_BANDS:
                    warnings.append(f"unknown hsl band '{band}' ignored")
        elif k not in ("curve", "heal"):
            warnings.append(f"unknown adjustment '{k}' ignored")
    return warnings


def _monotone_cubic(points, x):
    p = np.array(sorted(points), dtype=np.float64)
    xs, ys = p[:, 0], p[:, 1]
    if len(xs) < 2:
        return x
    d = np.diff(ys) / np.maximum(np.diff(xs), 1e-9)
    m = np.concatenate([[d[0]], (d[:-1] + d[1:]) / 2, [d[-1]]])
    for i, dk in enumerate(d):
        if dk == 0:
            m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / dk, m[i + 1] / dk
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[i], m[i + 1] = t * a * dk, t * b * dk
    k = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
    h = xs[k + 1] - xs[k]
    t = np.clip((x - xs[k]) / h, 0, 1)
    h00, h10 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t
    h01, h11 = -2 * t**3 + 3 * t**2, t**3 - t**2
    return h00 * ys[k] + h10 * h * m[k] + h01 * ys[k + 1] + h11 * h * m[k + 1]


def tone_lut(adjust: dict) -> np.ndarray | None:
    c = adjust.get("contrast", 0) / 100
    hi = max(adjust.get("highlights", 0), 0) / 100
    w = adjust.get("whites", 0) / 100
    b = adjust.get("blacks", 0) / 100
    curve = adjust.get("curve")
    if not any([c, hi, w, b, curve]):
        return None
    x = np.linspace(0, 1, LUT_SIZE)
    y = x.copy()
    if c > 0:
        s = y * y * (3 - 2 * y)
        y = y + (s - y) * c * 0.75
    elif c < 0:
        y = 0.5 + (y - 0.5) * (1 + c * 0.45)
    if hi:
        y = y + hi * 0.12 * np.exp(-(((y - 0.72) / 0.16) ** 2))
    if w:
        y = y + w * 0.14 * smoothstep(0.55, 1.0, y) ** 2
    if b:
        y = y + b * 0.10 * (1 - smoothstep(0.0, 0.45, y)) ** 2
    if curve:
        y = _monotone_cubic(curve, np.clip(y, 0, 1))
    return np.clip(y, 0, 1).astype(np.float32)


def wb_gains(adjust: dict):
    t = adjust.get("temp", 0) / 100
    u = adjust.get("tint", 0) / 100
    if not t and not u:
        return None
    r, g, b = 2 ** (0.35 * t + 0.08 * u), 2 ** (-0.22 * u), 2 ** (-0.35 * t + 0.08 * u)
    norm = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return r / norm, g / norm, b / norm


def _band_weights(h: np.ndarray) -> dict:
    names = list(HSL_BANDS)
    centres = np.array([HSL_BANDS[n] for n in names], dtype=np.float32)
    weights = {}
    for i, name in enumerate(names):
        prev_c = centres[i - 1] - (360 if i == 0 else 0)
        next_c = centres[(i + 1) % len(names)] + (360 if i == len(names) - 1 else 0)
        c = centres[i]
        d = (h - c + 180) % 360 - 180
        weights[name] = np.where(d < 0, np.clip(1 + d / (c - prev_c), 0, 1), np.clip(1 - d / (next_c - c), 0, 1))
    return weights


def apply_hsl(img: np.ndarray, hsl: dict) -> np.ndarray:
    h, s, v = rgb_to_hsv(img)
    weights = _band_weights(h)
    dh = np.zeros_like(h)
    ds = np.zeros_like(h)
    dl = np.zeros_like(h)
    for band, p in hsl.items():
        if band not in weights:
            continue
        w = weights[band]
        dh += w * p.get("hue", 0) * 0.3
        ds += w * p.get("sat", 0) / 100
        dl += w * p.get("lum", 0) / 100
    s2 = np.clip(s * (1 + ds), 0, 1)
    v2 = np.clip(v * 2 ** (dl * 0.8 * s), 0, 1)
    return hsv_to_rgb(h + dh, s2, v2)


def hsl_cube(hsl: dict) -> np.ndarray:
    g = np.linspace(0, 1, CUBE_DIM, dtype=np.float32)
    b_, g_, r_ = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r_, g_, b_], -1).reshape(-1, 1, 3)
    out = apply_hsl(rgb, hsl).reshape(-1, 3)
    return np.concatenate([out, np.ones((out.shape[0], 1), np.float32)], 1).astype(np.float32)


def build_ops(adjust: dict, long_edge: int) -> list[dict]:
    ops = []
    if gains := wb_gains(adjust):
        ops.append({"op": "matrix", "r": gains[0], "g": gains[1], "b": gains[2]})
    if ev := adjust.get("exposure", 0):
        ops.append({"op": "exposure", "ev": ev})
    sh, hl = adjust.get("shadows", 0), adjust.get("highlights", 0)
    if sh or hl < 0:
        ops.append({
            "op": "highlight_shadow",
            "shadow": sh / 100 * (0.45 if sh < 0 else 1.0),
            "highlight": 1 + min(hl, 0) / 100,
            "radius": round(max(2.0, long_edge * 0.004), 1),
        })
    if (lut := tone_lut(adjust)) is not None:
        ops.append({"op": "curves", "lut": lut})
    if hsl := {k: v for k, v in adjust.get("hsl", {}).items() if k in HSL_BANDS}:
        ops.append({"op": "cube", "hsl": hsl})
    if vib := adjust.get("vibrance", 0):
        ops.append({"op": "vibrance", "amount": vib / 100})
    if sat := adjust.get("saturation", 0):
        ops.append({"op": "saturation", "value": 1 + sat / 100})
    if sharp := adjust.get("sharpen", 0):
        ops.append({"op": "sharpen", "sharpness": sharp / 150, "radius": 1.5 * max(1.0, long_edge / 3000)})
    return ops


def _midtones(img):
    x = luma(img)
    return np.clip(4 * x * (1 - x) * 1.25, 0, 1)[..., None]


def np_apply_op(img: np.ndarray, op: dict) -> np.ndarray:
    kind = op["op"]
    if kind == "matrix":
        lin = srgb_to_linear(img) * np.array([op["r"], op["g"], op["b"]], np.float32)
        return linear_to_srgb(lin)
    if kind == "exposure":
        return linear_to_srgb(srgb_to_linear(img) * 2 ** op["ev"])
    if kind == "highlight_shadow":
        lum = luma(img)
        base = guided_filter(lum, lum, max(2, int(op["radius"] * 5)), 0.01)
        shift = op["shadow"] * 1.5 * (1 - smoothstep(0.0, 0.6, base))
        shift -= (1 - op["highlight"]) * 1.5 * smoothstep(0.4, 1.0, base)
        return linear_to_srgb(srgb_to_linear(img) * (2 ** shift)[..., None])
    if kind == "curves":
        lut = op["lut"]
        return np.interp(img, np.linspace(0, 1, len(lut)), lut).astype(np.float32)
    if kind == "cube":
        return apply_hsl(img, op["hsl"])
    if kind in ("vibrance", "saturation"):
        lum = luma(img)[..., None]
        if kind == "saturation":
            factor = op["value"]
        else:
            _, s, _ = rgb_to_hsv(img)
            factor = (1 + op["amount"] * (1 - s))[..., None]
        return lum + (img - lum) * factor
    if kind == "sharpen":
        lum = luma(img)
        detail = lum - gaussian(lum, op["radius"])
        return img + op["sharpness"] * 1.5 * detail[..., None]
    raise ValueError(f"unknown op {kind}")


def local_contrast(img: np.ndarray, kind: str, amount: float) -> np.ndarray:
    long_edge = max(img.shape[:2])
    radius, eps, gain = (max(8, int(long_edge * 0.02)), 4e-3, 2.2) if kind == "clarity" else (max(2, int(long_edge * 0.003)), 1e-3, 1.6)
    lum = luma(img)
    detail = lum - guided_filter(lum, lum, radius, eps)
    k = gain * amount if amount >= 0 else max(-1.0, amount)
    return img + (k * detail)[..., None] * _midtones(img)


def dehaze(img: np.ndarray, amount: float) -> np.ndarray:
    h, w = img.shape[:2]
    scale = 512 / max(h, w)
    small = resize(img, max(1, int(w * scale)), max(1, int(h * scale))) if scale < 1 else img
    dark = min_filter(small.min(-1), 7)
    flat = dark.reshape(-1)
    top = flat >= np.quantile(flat, 0.999)
    airlight = small.reshape(-1, 3)[top].mean(0).clip(0.5, 1.0)
    if amount < 0:
        return img + (airlight - img) * (-amount * 0.5)
    trans_small = 1 - 0.9 * min_filter((small / airlight).min(-1), 7)
    trans = resize(trans_small.astype(np.float32), w, h)
    trans = guided_filter(img, trans, max(4, int(max(h, w) * 0.01)), 1e-3)
    trans = np.clip(trans, 0.2, 1)[..., None]
    clear = np.clip((img - airlight) / trans + airlight, 0, 1)
    before, after = srgb_to_linear(img).mean(), srgb_to_linear(clear).mean()
    clear = linear_to_srgb(srgb_to_linear(clear) * np.sqrt(before / max(after, 1e-6)))
    return img + (clear - img) * amount


def heal(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    hole = 1 - min_filter(1 - (mask > 0.3).astype(np.float32), 2)
    u8 = to_u8(img)
    if migan_available():
        fixed = _migan(u8, hole)
    elif cv2 is not None and hasattr(cv2, "xphoto"):
        fixed = np.zeros_like(u8)
        cv2.xphoto.inpaint(u8, (1 - hole).astype(np.uint8), fixed, cv2.xphoto.INPAINT_FSR_FAST)
    else:
        raise RuntimeError("heal needs opencv (Mac tier)")
    soft = gaussian(hole, 2)[..., None]
    return img * (1 - soft) + fixed.astype(np.float32) / 255 * soft


def _migan(u8: np.ndarray, hole: np.ndarray) -> np.ndarray:
    import onnxruntime as ort

    session = ort.InferenceSession(str(MIGAN), providers=["CPUExecutionProvider"])
    known = ((1 - hole) * 255).astype(np.uint8)
    out = session.run(None, {"image": u8.transpose(2, 0, 1)[None], "mask": known[None, None]})[0]
    return out[0].transpose(1, 2, 0)


PRESETS = {
    "instagram": {"aspect": (4, 5)},
    "story": {"aspect": (9, 16)},
    "linkedin": {"aspect": (1, 1)},
    "original": {"aspect": None},
}


def parse_aspect(a):
    if a is None or isinstance(a, (list, tuple)):
        return a
    w, h = str(a).replace("x", ":").split(":")
    return float(w), float(h)


def crop_rect(W: int, H: int, spec: dict | None, preset_aspect) -> tuple[int, int, int, int] | None:
    spec = spec or {}
    if box := spec.get("box"):
        x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in box)
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"crop box {box} is empty inside the photo; use [x0, y0, x1, y1] with x1 > x0 and y1 > y0")
        return int(x0 * W), int(y0 * H), max(1, int((x1 - x0) * W)), max(1, int((y1 - y0) * H))
    aspect = parse_aspect(spec.get("aspect")) or preset_aspect
    if not aspect:
        return None
    ar = aspect[0] / aspect[1]
    cw, ch = (W, W / ar) if W / H < ar else (H * ar, H)
    zoom = min(max(spec.get("scale", 1.0), 0.1), 1.0)
    cw, ch = cw * zoom, ch * zoom
    fx, fy = spec.get("focus", (0.5, 0.5))
    ax, ay = spec.get("focus_at", (0.5, 0.5))
    x = min(max(fx * W - ax * cw, 0), W - cw)
    y = min(max(fy * H - ay * ch, 0), H - ch)
    return int(round(x)), int(round(y)), int(round(cw)), int(round(ch))
