"""Measured findings that ground edit suggestions.

Each check reads the Scene and returns findings shaped as
  {"check", "finding", "evidence", "step" | "crop"}
where `step` is a ready recipe step (reference/recipe.md). Claude ranks and
phrases them; the numbers and coordinates come from here, not from eyeballing.
"""

from __future__ import annotations

import numpy as np

from detect import MissingCapability, Scene, segformer_available
from imaging import cv2, gaussian, luma, min_filter, resize, rgb_to_hsv, srgb_to_linear

SCENERY = ("mountain", "building", "tree", "water", "ground", "rock")


def _mean_lin(img, w):
    lin = luma(srgb_to_linear(img))
    return float((lin * w).sum() / max(w.sum(), 1e-6))


def _stops(img, a, b):
    return float(np.log2(max(_mean_lin(img, a), 1e-5) / max(_mean_lin(img, b), 1e-5)))


def exposure(scene: Scene):
    img = scene.img
    lum = luma(img)
    p01, p99 = np.percentile(lum, [1, 99])
    clipped = float((img.max(-1) >= 0.995).mean())
    ev = {"mean_luma": round(float(lum.mean()), 3), "p01": round(float(p01), 3), "p99": round(float(p99), 3),
          "clipped_pct": round(clipped * 100, 2)}
    out = []
    if clipped > 0.005:
        out.append({"finding": f"{clipped * 100:.1f}% of pixels are clipped to white", "evidence": ev,
                    "step": {"name": "recover highlights", "adjust": {"highlights": -40}}})
    if lum.mean() < 0.28:
        lift = float(np.clip(np.log2(0.18 / max(_mean_lin(img, np.ones_like(lum)), 1e-4)) * 0.5, 0.2, 1.0))
        out.append({"finding": "the photo is underexposed overall", "evidence": ev,
                    "step": {"name": "brighten", "adjust": {"exposure": round(lift, 1)}}})
    if p99 < 0.75 and clipped < 0.001:
        out.append({"finding": f"no true whites; the brightest 1% sits at {p99:.2f}", "evidence": ev,
                    "step": {"name": "set whites", "adjust": {"whites": 20}}})
    if p01 > 0.12:
        out.append({"finding": f"blacks are washed out; the darkest 1% sits at {p01:.2f}", "evidence": ev,
                    "step": {"name": "set blacks", "adjust": {"blacks": -20}}})
    return out


def _person(scene: Scene):
    """Vision person mask, or None when Vision is unavailable or finds nobody."""
    try:
        m = scene.vision_mask("person")
    except MissingCapability:
        return None
    return m if m.mean() >= 0.01 else None


def subject_balance(scene: Scene):
    person = _person(scene)
    if person is None:
        return []
    stops = _stops(scene.img, person, 1 - person)
    if stops > -1.0:
        return []
    return [{
        "finding": f"the person is {-stops:.1f} stops darker than the background (skip if the silhouette is the look)",
        "evidence": {"person_vs_background_stops": round(stops, 2)},
        "step": {"name": "lift the subject", "mask": {"type": "person"},
                 "adjust": {"exposure": round(min(0.7, -stops * 0.2), 1), "shadows": 20}},
    }]


def face(scene: Scene):
    faces = scene.faces()
    if not faces:
        return []
    H, W = scene.img.shape[:2]
    x0, y0, x1, y1 = faces[0]["box"]
    region = scene.img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
    face_luma = float(luma(region).mean()) if region.size else 1.0
    if face_luma >= 0.32:
        return []
    return [{
        "finding": f"the face is dark (luma {face_luma:.2f}); eye contact won't land",
        "evidence": {"face_luma": round(face_luma, 3), "face_box": faces[0]["box"],
                     "confidence": round(faces[0].get("confidence", 0), 2)},
        "step": {"name": "lift the face", "mask": {"type": "face", "part": "face"}, "adjust": {"exposure": 0.4}},
    }]


def color_cast(scene: Scene):
    img = scene.img
    _, s, v = rgb_to_hsv(img)
    neutral = (s < 0.15) & (v > 0.25) & (v < 0.9)
    if neutral.mean() < 0.02:
        return []
    r, g, b = srgb_to_linear(img[neutral]).mean(0)
    warm = float(np.log2(r / b))
    green = float(np.log2(g / np.sqrt(r * b)))
    # Half of the full neutralisation (develop.wb_gains scales), so the mood survives.
    temp = int(round(-50 * warm / 0.70))
    tint = int(round(50 * green / 0.30))
    if abs(temp) < 8 and abs(tint) < 8:
        return []
    leans = []
    if abs(temp) >= 8:
        leans.append("warm (yellow)" if warm > 0 else "cool (blue)")
    if abs(tint) >= 8:
        leans.append("green" if green > 0 else "magenta")
    adjust = {k: val for k, val in (("temp", temp), ("tint", tint)) if abs(val) >= 8}
    return [{
        "finding": f"neutral greys lean {' and '.join(leans)}; keep it if the cast is the grade",
        "evidence": {"log2_r_over_b": round(warm, 3), "log2_g_excess": round(green, 3),
                     "neutral_share": round(float(neutral.mean()), 3)},
        "step": {"name": "neutralise cast (half strength)", "adjust": adjust},
    }]


def haze(scene: Scene):
    if not segformer_available():
        raise MissingCapability("needs SegFormer")
    small = resize(scene.img, 512, int(512 * scene.img.shape[0] / scene.img.shape[1]))
    dark = min_filter(small.min(-1), 7)
    out = []
    for cls in SCENERY:
        try:
            m = resize(scene.segment_mask(cls, refine=False), small.shape[1], small.shape[0])
        except ValueError:
            continue
        if m.mean() < 0.05:
            continue
        dc = float((dark * m).sum() / m.sum())
        if dc < 0.18:
            continue
        amount = int(np.clip(round((dc - 0.12) * 100), 10, 30))
        out.append({
            "finding": f"the {cls} looks hazy and low-contrast (dark channel {dc:.2f})",
            "evidence": {"dark_channel": round(dc, 3), "share": round(float(m.mean()), 3)},
            "step": {"name": f"{cls}: dehaze + clarity",
                     "mask": {"op": "subtract", "masks": [{"type": "segment", "class": cls}, {"type": "person", "grow": 0.01},
                                                         {"type": "segment", "class": "sky"}]},
                     "adjust": {"dehaze": amount, "clarity": 15}},
        })
    return out


def sky(scene: Scene):
    if not segformer_available():
        raise MissingCapability("needs SegFormer")
    m = scene.segment_mask("sky", refine=False) > 0.5
    if m.mean() < 0.05:
        return []
    px = scene.img[m]
    clipped = float((px.max(-1) >= 0.995).mean())
    mean = float(luma(px).mean())
    ev = {"sky_share": round(float(m.mean()), 3), "sky_luma": round(mean, 3), "sky_clipped_pct": round(clipped * 100, 2)}
    if clipped > 0.01:
        return [{"finding": f"{clipped * 100:.1f}% of the sky is blown out", "evidence": ev,
                 "step": {"name": "recover sky", "mask": {"type": "sky"}, "adjust": {"highlights": -50}}}]
    if mean > 0.8:
        return [{"finding": f"the sky is bright and flat (luma {mean:.2f}); it will read as white on a phone", "evidence": ev,
                 "step": {"name": "bring back sky tone", "mask": {"type": "sky"}, "adjust": {"highlights": -25}}}]
    return []


def distractions(scene: Scene):
    """Small bright spots on dark surroundings (reflective strips, logos, specks)."""
    if cv2 is None:
        raise MissingCapability("needs OpenCV")
    img = scene.img
    H, W = img.shape[:2]
    S = min(H, W)
    lum = luma(img)
    surround = gaussian(lum, 0.02 * S)
    cand = (lum > 0.4) & (lum - surround > 0.25) & (surround < 0.3)
    for f in scene.faces() if scene_has_vision(scene) else []:
        x0, y0, x1, y1 = f["box"]
        cand[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = False
    if (person := _person(scene)) is not None:
        # Rim light along the subject's outline belongs to the subject, not a distraction.
        person = (person > 0.5).astype(np.uint8)
        band = max(3, int(0.015 * S))
        outline = cv2.dilate(person, np.ones((band, band), np.uint8)) - cv2.erode(person, np.ones((band, band), np.uint8))
        cand &= outline == 0
    n, labels, stats, cents = cv2.connectedComponentsWithStats(cand.astype(np.uint8), connectivity=8)
    pad = max(5, int(0.05 * S))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))
    spots = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if not 2e-5 * H * W <= area <= 3e-3 * H * W:
            continue
        x, y, w, h = (stats[i, k] for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        ys, xs = slice(max(0, y - pad), y + h + pad), slice(max(0, x - pad), x + w + pad)
        blob = (labels[ys, xs] == i).astype(np.uint8)
        around = (cv2.dilate(blob, kernel) > 0) & (blob == 0)
        # A stray spot sits alone on a dark area; pieces of a bright pattern (a printed fleece) have bright neighbours.
        if (lum[ys, xs][around] > 0.35).mean() > 0.04:
            continue
        contrast = float((lum - surround)[labels == i].mean())
        spots.append((contrast * np.sqrt(area), cents[i], np.hypot(w, h) / 2))
    if not spots:
        return []
    spots.sort(key=lambda t: -t[0])
    dots = [[round(float(c[0]) / W, 3), round(float(c[1]) / H, 3), round(max(0.008, float(r) * 1.2 / S), 3)] for _, c, r in spots[:5]]
    return [{
        "finding": f"{len(dots)} small bright spot(s) on dark areas pull the eye",
        "evidence": {"spots": dots},
        "step": {"name": "tone down bright spots",
                 "mask": {"op": "intersect", "masks": [{"type": "brush", "dots": dots},
                                                      {"type": "luminance", "min": 0.35, "soft": 0.08}]},
                 "adjust": {"exposure": -0.7, "highlights": -40}},
    }]


def crop(scene: Scene):
    """Headroom and a destination crop anchored on the face or subject top."""
    H, W = scene.img.shape[:2]
    box = None
    anchor = None
    if scene_has_vision(scene):
        faces = scene.faces()
        if faces:
            x0, y0, x1, y1 = faces[0]["box"]
            anchor = [round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)]
        if (person := _person(scene)) is not None:
            ys, xs = np.nonzero(person > 0.5)
            box = [xs.min() / W, ys.min() / H, xs.max() / W, ys.max() / H]
        elif scene.vision().get("salient_boxes"):
            box = scene.vision()["salient_boxes"][0]
    if box is None:
        return []
    anchor = anchor or [round((box[0] + box[2]) / 2, 3), round(box[1] + 0.05 * (box[3] - box[1]), 3)]
    headroom = box[1]
    return [{
        "finding": f"{headroom * 100:.0f}% of the frame is empty above the subject" if headroom > 0.2
        else "subject framing is tight; crop mainly for the destination aspect",
        "evidence": {"subject_box": [round(v, 3) for v in box], "anchor": anchor, "headroom": round(headroom, 3)},
        "crop": {"instagram": {"aspect": "4:5", "focus": anchor, "focus_at": [0.5, 0.36]},
                 "linkedin": {"aspect": "1:1", "focus": anchor, "focus_at": [0.5, 0.42], "scale": 0.7}},
    }]


def scene_has_vision(scene: Scene) -> bool:
    try:
        scene.vision()
        return True
    except MissingCapability:
        return False


CHECKS = [exposure, subject_balance, face, color_cast, haze, sky, distractions, crop]


def run(scene: Scene) -> dict:
    findings, skipped = [], []
    for check in CHECKS:
        try:
            for f in check(scene):
                findings.append({"check": check.__name__, **f})
        except MissingCapability as e:
            skipped.append(f"{check.__name__}: {e}")
    return {"findings": findings, "skipped": skipped}
