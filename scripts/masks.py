"""Mask specs -> float masks.

Coordinates are normalized to the working image, origin top-left. Radii and
feathers are fractions of the image's SHORT side, so circles stay round.
See reference/recipe.md for the full spec.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from detect import MissingCapability, Scene
from imaging import cv2, gaussian, guided_filter, luma, resize, rgb_to_hsv, smoothstep

COMBINATORS = ("union", "intersect", "subtract")


def build(spec: dict | None, scene: Scene) -> np.ndarray | None:
    """Evaluate a mask spec; None means the whole image."""
    if spec is None or spec.get("type") == "all":
        return None
    m = _base(spec, scene)
    return _modifiers(m, spec, scene)


def _base(spec: dict, scene: Scene) -> np.ndarray:
    img = scene.img
    H, W = img.shape[:2]
    S = min(H, W)
    op = spec.get("op")
    if op in COMBINATORS:
        parts = [build(s, scene) for s in spec["masks"]]
        parts = [np.ones((H, W), np.float32) if p is None else p for p in parts]
        out = parts[0]
        for p in parts[1:]:
            out = np.maximum(out, p) if op == "union" else np.minimum(out, p) if op == "intersect" else out * (1 - p)
        return out

    kind = spec.get("type")
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    if kind == "radial":
        cx, cy = spec["center"]
        r = spec.get("radius", 0.2)
        rx, ry = (r, r) if np.isscalar(r) else r
        ang = np.deg2rad(spec.get("angle", 0))
        dx, dy = xx - cx * W, yy - cy * H
        u = (dx * np.cos(ang) + dy * np.sin(ang)) / (rx * S)
        v = (-dx * np.sin(ang) + dy * np.cos(ang)) / (ry * S)
        d = np.sqrt(u * u + v * v)
        f = spec.get("falloff", 0.5)
        return (1 - smoothstep(1 - f, 1, d)).astype(np.float32)

    if kind == "linear":
        (x0, y0), (x1, y1) = spec["start"], spec["end"]
        vx, vy = (x1 - x0) * W, (y1 - y0) * H
        t = ((xx - x0 * W) * vx + (yy - y0 * H) * vy) / max(vx * vx + vy * vy, 1e-6)
        return (1 - smoothstep(0, 1, t)).astype(np.float32)

    if kind in ("polygon", "brush"):
        canvas = Image.new("L", (W, H), 0)
        draw = ImageDraw.Draw(canvas)
        if kind == "polygon":
            draw.polygon([(x * W, y * H) for x, y in spec["points"]], fill=255)
        else:
            for dot in spec["dots"]:
                x, y = dot[0] * W, dot[1] * H
                r = (dot[2] if len(dot) > 2 else spec.get("size", 0.02)) * S
                draw.ellipse([x - r, y - r, x + r, y + r], fill=255)
        m = np.asarray(canvas, np.float32) / 255
        default_soft = 0.004 if kind == "polygon" else 0.006
        return gaussian(m, spec.get("soft", default_soft) * S)

    if kind == "luminance":
        return _band(luma(img), spec.get("min", 0), spec.get("max", 1), spec.get("soft", 0.08))

    if kind == "color":
        h, s, _ = rgb_to_hsv(img)
        d = np.abs((h - spec["hue"] + 180) % 360 - 180)
        rng, soft = spec.get("range", 25), spec.get("soft", 15)
        m = 1 - smoothstep(rng, rng + soft, d)
        return (m * smoothstep(spec.get("min_sat", 0.08), spec.get("min_sat", 0.08) + 0.08, s)).astype(np.float32)

    if kind in ("person", "subject"):
        return scene.vision_mask(kind)
    if kind == "background":
        return 1 - scene.vision_mask("subject")

    if kind == "face":
        return _face(spec, scene)

    if kind == "segment":
        classes = spec["class"] if isinstance(spec["class"], list) else [spec["class"]]
        out = np.zeros((H, W), np.float32)
        for c in classes:
            out = np.maximum(out, scene.segment_mask(c, refine=spec.get("edge_refine", True)))
        return out

    if kind == "sky":
        try:
            return scene.segment_mask("sky")
        except MissingCapability:
            return _sky_heuristic(img)

    raise ValueError(f"unknown mask type '{kind}'")


def _band(x, lo, hi, soft):
    up = smoothstep(lo - soft, lo + soft, x) if lo > 0 else np.ones_like(x)
    down = 1 - smoothstep(hi - soft, hi + soft, x) if hi < 1 else np.ones_like(x)
    return (up * down).astype(np.float32)


def _face(spec: dict, scene: Scene) -> np.ndarray:
    faces = scene.faces()
    i = spec.get("index", 0)
    if i >= len(faces):
        raise MissingCapability("Vision found no face; place a radial mask from the grid instead")
    f = faces[i]
    x0, y0, x1, y1 = f["box"]
    H, W = scene.img.shape[:2]
    S = min(H, W)
    bw, bh = (x1 - x0) * W, (y1 - y0) * H
    part = spec.get("part", "face")
    scale = spec.get("scale", 1.0)
    if part == "eyes":
        lp, rp = f.get("left_pupil"), f.get("right_pupil")
        ipd = abs(lp[0] - rp[0]) * W if lp and rp else 0
        if ipd > 0.25 * bw:
            cx, cy = (lp[0] + rp[0]) / 2, (lp[1] + rp[1]) / 2
            rx, ry = ipd * 1.0, ipd * 0.55
        else:  # profile / covered face: pupils unreliable, use the upper band of the face box
            cx, cy = (x0 + x1) / 2, y0 + (y1 - y0) * 0.3
            rx, ry = bw * 0.6, bh * 0.3
    else:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = bw * 0.65, bh * 0.75
    return _base({"type": "radial", "center": [cx, cy], "radius": [rx * scale / S, ry * scale / S],
                  "falloff": spec.get("falloff", 0.6)}, scene)


def _sky_heuristic(img: np.ndarray) -> np.ndarray:
    """Bright, low-saturation, smooth pixels connected to the top edge (no model)."""
    _, s, v = rgb_to_hsv(img)
    texture = np.abs(luma(img) - gaussian(luma(img), 3))
    cand = (v > 0.55) & (s < 0.35) & (texture < 0.03)
    connected = np.cumprod(cand, axis=0).astype(np.float32)  # sky until the first non-sky pixel per column
    return gaussian(connected, 2)


def _modifiers(m: np.ndarray, spec: dict, scene: Scene) -> np.ndarray:
    H, W = m.shape
    S = min(H, W)
    if g := spec.get("grow"):  # +/- fraction of short side
        r = max(1, int(abs(g) * S))
        if cv2 is not None:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            m = cv2.dilate(m, k) if g > 0 else cv2.erode(m, k)
        else:
            blurred = gaussian(m, r)
            m = smoothstep(0.1, 0.5, blurred) if g > 0 else smoothstep(0.5, 0.9, blurred)
    refine = spec.get("refine")
    if refine == "grabcut":
        m = _grabcut(m, scene.img)
    if refine in ("edges", "grabcut"):
        m = guided_filter(scene.img, m.astype(np.float32), max(3, int(S * 0.006)), 1e-4)
    if f := spec.get("feather"):
        m = gaussian(m, f * S)
    m = np.clip(m, 0, 1)
    if spec.get("invert"):
        m = 1 - m
    return (m * spec.get("strength", 1.0)).astype(np.float32)


def _grabcut(m: np.ndarray, img: np.ndarray) -> np.ndarray:
    """Snap a rough mask to object boundaries with OpenCV GrabCut."""
    if cv2 is None:
        raise MissingCapability("refine: grabcut needs opencv (Mac tier)")
    H, W = m.shape
    scale = min(1.0, 1024 / max(H, W))
    w, h = max(1, int(W * scale)), max(1, int(H * scale))
    small = resize(m, w, h)
    bgr = cv2.cvtColor((resize(img, w, h).clip(0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    gc = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    gc[small > 0.5] = cv2.GC_PR_FGD
    k = max(3, int(min(w, h) * 0.03))
    gc[cv2.erode((small > 0.5).astype(np.uint8), np.ones((k, k), np.uint8)) > 0] = cv2.GC_FGD
    gc[cv2.dilate((small > 0.5).astype(np.uint8), np.ones((k * 2, k * 2), np.uint8)) == 0] = cv2.GC_BGD
    if not (gc == cv2.GC_FGD).any() or not (gc == cv2.GC_BGD).any():
        return m
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    out = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.float32)
    return resize(out, W, H)
