from __future__ import annotations

import numpy as np

from detect import MissingCapability
from imaging import gaussian, luma, resize, rgb_to_hsv, tiles

ASPECTS = (("1:1", 1.0), ("4:5", 0.8), ("9:16", 0.5625), ("16:9", 1.7778))
MIN_LONG_EDGE = 384
MAX_OUT = 3
MIN_IOU_KEPT = 0.55
MAX_IOU_DEFAULT = 0.85


def _eye_map(img):
    small = resize(img, 256, max(1, round(256 * img.shape[0] / img.shape[1])))
    lum = luma(small)
    _, s, _ = rgb_to_hsv(small)
    lc = np.abs(lum - gaussian(lum, 6))
    score = None
    for m, w in ((lum, 0.5), (lc, 0.3), (s, 0.2)):
        t = tiles(m)
        part = w * np.clip(t / max(float(t.max()), 1e-6), 0, 1)
        score = part if score is None else score + part
    return score


def _anchors(scene, score):
    try:
        vision = scene.vision()
    except MissingCapability:
        vision = {}
    out = []
    for f in vision.get("faces", [])[:3]:
        out.append(([(f["box"][0] + f["box"][2]) / 2, (f["box"][1] + f["box"][3]) / 2], "face", 1.4))
    for b in vision.get("salient_boxes", [])[:2]:
        out.append(([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], "subject", 1.0))
    for idx in np.argsort(score, None)[::-1][:8]:
        r, c = np.unravel_index(int(idx), score.shape)
        p = [(c + 0.5) / score.shape[1], (r + 0.5) / score.shape[0]]
        if all(abs(p[0] - q[0][0]) + abs(p[1] - q[0][1]) > 0.2 for q in out):
            out.append((p, "detail", 0.8))
    for x in (1 / 3, 2 / 3):
        for y in (1 / 3, 2 / 3):
            out.append(([x, y], "thirds", 0.4))
    dedup = []
    for a in sorted(out, key=lambda t: -t[2]):
        if all(abs(a[0][0] - b[0][0]) + abs(a[0][1] - b[0][1]) > 0.06 for b in dedup):
            dedup.append(a)
    return dedup[:8]


def _person_box(scene):
    if scene.work is None:
        return None
    try:
        m = scene.vision_mask("person")
    except MissingCapability:
        return None
    if m.mean() < 0.01:
        return None
    ys, xs = np.nonzero(m > 0.5)
    h, w = m.shape
    return [float(xs.min() / w), float(ys.min() / h), float(xs.max() / w), float(ys.max() / h)]


def _box(aspect, cx, cy, scale, W, H):
    r = aspect * H / W
    bw, bh = (1.0, 1.0 / r) if r >= 1 else (r, 1.0)
    bw *= scale
    bh *= scale
    x0 = min(max(cx - bw / 2, 0.0), 1.0 - bw)
    y0 = min(max(cy - bh / 2, 0.0), 1.0 - bh)
    return [round(x0, 4), round(y0, 4), round(x0 + bw, 4), round(y0 + bh, 4)]


def _iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / max(union, 1e-9)


def _eye_terms(score, box):
    r0, c0 = int(box[1] * score.shape[0]), int(box[0] * score.shape[1])
    r1, c1 = int(np.ceil(box[3] * score.shape[0])), int(np.ceil(box[2] * score.shape[1]))
    r0, c0, r1, c1 = max(r0, 0), max(c0, 0), min(r1, score.shape[0]), min(c1, score.shape[1])
    if r1 <= r0 or c1 <= c0:
        return 0.0, 0.0
    inside = score[r0:r1, c0:c1]
    keep = float(inside.sum() / max(score.sum(), 1e-6))
    density = float(inside.mean() / max(score.mean(), 1e-6))
    return keep, density


def _hero_terms(box, faces, person_box):
    score, ev = 0.0, {}
    if faces:
        fx0, fy0, fx1, fy1 = faces[0]["box"]
        inside = fx0 >= box[0] and fy0 >= box[1] and fx1 <= box[2] and fy1 <= box[3]
        share = (fy1 - fy0) / (box[3] - box[1])
        ev["face_height_share"] = round(float(share), 2)
        if not inside:
            score -= 1.5
        else:
            score += 0.9 if 0.2 <= share <= 0.65 else 0.2
            if share > 0.8:
                score -= 0.5
            headroom = (fy0 - box[1]) / (box[3] - box[1])
            score += 0.3 if headroom >= 0.04 else -0.4
            cx = (fx0 + fx1) / 2
            third_x = box[0] + np.array([1 / 3, 2 / 3]) * (box[2] - box[0])
            if float(np.min(np.abs(cx - third_x))) < 0.09 * (box[2] - box[0]):
                score += 0.3
    if person_box:
        px0, py0, px1, py1 = person_box
        pin = px0 >= box[0] - 0.01 and py0 >= box[1] - 0.01 and px1 <= box[2] + 0.01 and py1 <= box[3] + 0.01
        pout = px1 < box[0] or py1 < box[1] or px0 > box[2] or py0 > box[3]
        if not pin and not pout:
            score -= 0.3
            ev["cuts_person"] = True
        elif pin and py1 - py0 > 0.2 * (box[3] - box[1]):
            score += 0.25
    return score, ev


def _why(aspect, kind, ev):
    share = ev.get("face_height_share")
    if share is not None and 0.2 <= share <= 0.65:
        return f"a {aspect} on the face — the portrait inside this frame"
    if kind == "detail":
        return f"a {aspect} on the busiest region — denser with detail than the frame it came from"
    if aspect in ("9:16", "16:9"):
        return f"a {aspect} out of this frame — a different photo for a different surface"
    return f"a tighter {aspect} — the same moment with less around it"


def mine(scene) -> list[dict]:
    img = scene.img
    H, W = img.shape[:2]
    score = _eye_map(img)
    try:
        faces = scene.faces()[:3]
    except MissingCapability:
        faces = []
    person_box = _person_box(scene)
    anchors = _anchors(scene, score)
    raw = []
    for aspect, a in ASPECTS:
        default = _box(a, 0.5, 0.5, 1.0, W, H)
        for (cx, cy), kind, prior in anchors:
            for scale in ((1.0, 0.8) if kind == "thirds" else (1.0, 0.8, 0.5)):
                box = _box(a, cx, cy, scale, W, H)
                if max((box[2] - box[0]) * W, (box[3] - box[1]) * H) < MIN_LONG_EDGE:
                    continue
                if _iou(box, default) > MAX_IOU_DEFAULT:
                    continue
                keep, density = _eye_terms(score, box)
                if keep < 0.25:
                    continue
                hero, ev = _hero_terms(box, faces, person_box)
                total = 2.2 * keep + 1.2 * min(density, 2.5) + 0.2 * prior + hero
                raw.append((round(total, 3), aspect, box, kind,
                            {**ev, "eye_keep": round(keep, 2), "eye_density": round(density, 2)}))
    raw.sort(key=lambda t: (-t[0], t[1], t[2]))
    out = []
    for total, aspect, box, kind, ev in raw:
        if any(_iou(box, kept["box"]) > MIN_IOU_KEPT for kept in out):
            continue
        out.append({"aspect": aspect, "box": box, "score": total, "anchor": kind, "evidence": ev,
                    "crop": {"box": box}, "why": _why(aspect, kind, ev)})
        if len(out) >= MAX_OUT:
            break
    return out
