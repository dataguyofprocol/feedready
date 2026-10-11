from __future__ import annotations

import numpy as np

from detect import MissingCapability, Scene, segformer_available
from develop import HSL_BANDS
from imaging import cv2, gaussian, luma, min_filter, resize, rgb_to_hsv, skin_mask, srgb_to_linear

SCENERY = ("mountain", "building", "tree", "water", "ground", "rock")


def _mean_lin(img, w):
    lin = luma(srgb_to_linear(img))
    return float((lin * w).sum() / max(w.sum(), 1e-6))


def _stops(img, a, b):
    return float(np.log2(max(_mean_lin(img, a), 1e-5) / max(_mean_lin(img, b), 1e-5)))


def _tiles(a, th=8, tw=8):
    gh, gw = a.shape[0] // th, a.shape[1] // tw
    return a[: gh * th, : gw * tw].reshape(th, gh, tw, gw).mean((1, 3))


def _small(img, w=256):
    return resize(img, w, max(1, round(w * img.shape[0] / img.shape[1])))


def _region_name(idx, shape):
    v = "upper" if idx[0] < shape[0] / 3 else "lower" if idx[0] > 2 * shape[0] / 3 else "middle"
    h = "left" if idx[1] < shape[1] / 3 else "right" if idx[1] > 2 * shape[1] / 3 else ""
    return f"{v} {h}".strip() if h else v


def _band_name(hue):
    return min(HSL_BANDS, key=lambda b: min(abs(hue - HSL_BANDS[b]), 360 - abs(hue - HSL_BANDS[b])))


def _warmth(lin, m):
    return float(np.log2(max(lin[..., 0][m].mean(), 1e-4) / max(lin[..., 2][m].mean(), 1e-4)))


def _light_stats(img):
    small = _small(img)
    lum = luma(small)
    t = _tiles(lum)
    p90, p10 = np.percentile(t, [90, 10])
    spread = float(np.log2(max(p90, 0.02) / max(p10, 0.02)))
    mean = float(t.mean())
    direction, best = "even", 0.0
    for side, val in (("top", t[:2].mean()), ("bottom", t[-2:].mean()),
                      ("left", t[:, :2].mean()), ("right", t[:, -2:].mean())):
        if val - mean > best:
            direction, best = side, float(val - mean)
    if best < 0.08:
        direction = "even"
    lin = srgb_to_linear(small)
    hi = lum >= np.percentile(lum, 80)
    lo = lum <= np.percentile(lum, 20)
    warm_split = round(_warmth(lin, hi) - _warmth(lin, lo), 2)
    quality = "hard" if spread >= 2.0 else "soft" if spread <= 0.9 else "balanced"
    return {"quality": quality, "direction": direction, "tile_spread_stops": round(spread, 2),
            "warm_split": warm_split}


def exposure(scene: Scene):
    img = scene.img
    lum = luma(img)
    p01, p99 = np.percentile(lum, [1, 99])
    clipped = float((img.max(-1) >= 0.995).mean())
    ev = {"mean_luma": round(float(lum.mean()), 3), "p01": round(float(p01), 3), "p99": round(float(p99), 3),
          "clipped_pct": round(clipped * 100, 2)}
    out = []
    if clipped > 0.005:
        amount = -int(np.clip(25 + clipped * 800, 25, 70))
        out.append({"finding": f"{clipped * 100:.1f}% of pixels are clipped to white", "evidence": ev,
                    "step": {"name": "recover highlights", "adjust": {"highlights": amount}}})
    if lum.mean() < 0.28:
        lift = float(np.clip(np.log2(0.18 / max(_mean_lin(img, np.ones_like(lum)), 1e-4)) * 0.5, 0.2, 1.0))
        out.append({"finding": "the photo is underexposed overall", "evidence": ev,
                    "step": {"name": "brighten", "adjust": {"exposure": round(lift, 1)}}})
    if p99 < 0.75 and clipped < 0.001:
        amount = int(np.clip(round((0.92 - p99) * 120), 10, 40))
        out.append({"finding": f"no true whites; the brightest 1% sits at {p99:.2f}", "evidence": ev,
                    "step": {"name": "set whites", "adjust": {"whites": amount}}})
    if p01 > 0.12:
        amount = -int(np.clip(round((p01 - 0.03) * 150), 10, 40))
        out.append({"finding": f"blacks are washed out; the darkest 1% sits at {p01:.2f}", "evidence": ev,
                    "step": {"name": "set blacks", "adjust": {"blacks": amount}}})
    return out


def person_mask(scene: Scene):
    try:
        m = scene.vision_mask("person")
    except MissingCapability:
        return None
    return m if m.mean() >= 0.01 else None


def _faces(scene: Scene) -> list[dict]:
    try:
        return scene.faces()
    except MissingCapability:
        return []


def _skin_hue(img, box):
    sel = skin_mask(img, box)
    if sel is None:
        return None
    h, _, _ = rgb_to_hsv(img)
    rad = np.deg2rad(h[sel])
    return float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())))


OUTDOOR = {"sky", "mountain", "hill", "tree", "grass", "water", "sea", "river", "lake", "field", "sand", "plant",
           "rock", "palm", "earth", "snow", "flower", "land"}
URBAN = {"building", "skyscraper", "house", "road", "tower", "bridge", "sidewalk", "street"}
INDOOR = {"wall", "ceiling", "floor", "table", "chair", "bed", "cabinet", "door", "windowpane", "sofa", "shelf",
          "desk", "plate", "food", "counter", "kitchen"}


def profile(scene: Scene) -> dict:
    img = scene.img
    faces = _faces(scene)
    person = person_mask(scene)
    face_share = max(((f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]) for f in faces), default=0.0)
    person_share = float(person.mean()) if person is not None else 0.0
    shares = {}
    if segformer_available():
        for c in scene.segment_summary():
            shares[c["class"]] = shares.get(c["class"], 0) + c["share"]
    outdoor = sum(v for k, v in shares.items() if k in OUTDOOR)
    urban = sum(v for k, v in shares.items() if k in URBAN)
    indoor = sum(v for k, v in shares.items() if k in INDOOR)
    lum = luma(img)
    night = float(lum.mean()) < 0.18 and float(np.percentile(lum, 99.5)) > 0.8
    light_stats = _light_stats(img)
    if len(faces) >= 3:
        genre, hero = "group", "faces"
    elif faces and (face_share > 0.03 or person_share > 0.2):
        genre, hero = "portrait", "face"
    elif person_share > 0.03 or faces:
        genre, hero = "person in scene", "person"
    elif night:
        genre, hero = "night", "scene"
    elif urban > 0.25 and urban >= outdoor * 0.6:
        genre, hero = "city", "scene"
    elif outdoor > 0.4:
        genre, hero = "landscape", "scene"
    elif indoor > 0.3 or shares:
        genre, hero = "still life / interior", "subject"
    else:
        genre, hero = "unknown", "subject"
    return {
        "genre": genre,
        "hero": hero,
        "light": {"quality": light_stats["quality"], "direction": light_stats["direction"]},
        "setting": "night" if night else "indoor" if indoor > outdoor + urban else "outdoor" if shares else "unknown",
        "signals": {"faces": len(faces), "face_share": round(face_share, 3),
                    "face_readable": bool(faces) and skin_mask(img, faces[0]["box"]) is not None, "person_share": round(person_share, 3),
                    "outdoor_share": round(outdoor, 3), "urban_share": round(urban, 3), "indoor_share": round(indoor, 3),
                    "mean_luma": round(float(lum.mean()), 3)},
    }


def subject_balance(scene: Scene):
    person = person_mask(scene)
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


def separation(scene: Scene):
    faces = _faces(scene)
    person = person_mask(scene)
    if not faces or person is None:
        return []
    if _stops(scene.img, person, 1 - person) <= -1.0:
        return []
    skin = skin_mask(scene.img, faces[0]["box"])
    if skin is None:
        return []
    stops = _stops(scene.img, skin.astype(np.float32), 1 - person)
    if stops >= -0.4:
        return []
    amount = round(float(np.clip(-stops * 0.3, 0.15, 0.5)), 2)
    return [{
        "finding": f"the background is {-stops:.1f} stops brighter than the face, so the eye goes to the background first",
        "evidence": {"face_vs_background_stops": round(stops, 2)},
        "step": {"name": "dim the background", "mask": {"type": "person", "invert": True, "grow": -0.002},
                 "adjust": {"exposure": -amount, "highlights": -20}},
    }]


def face(scene: Scene):
    faces = scene.faces()
    if not faces:
        return []
    skin = skin_mask(scene.img, faces[0]["box"])
    if skin is None:
        return []
    face_luma = float(luma(scene.img)[skin].mean())
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
    temp = int(round(-50 * warm / 0.70))
    tint = int(round(50 * green / 0.30))
    if abs(temp) < 8 and abs(tint) < 8:
        return []
    leans = []
    if abs(temp) >= 8:
        leans.append("warm (yellow)" if warm > 0 else "cool (blue)")
    if abs(tint) >= 8:
        leans.append("green" if green > 0 else "magenta")
    evidence = {"log2_r_over_b": round(warm, 3), "log2_g_excess": round(green, 3),
                "neutral_share": round(float(neutral.mean()), 3)}
    note = "keep it if the cast is the grade"
    floor = 8
    faces = _faces(scene)
    if faces and (hue := _skin_hue(img, faces[0]["box"])) is not None:
        evidence["skin_hue"] = round(hue, 1)
        if 8 <= hue <= 38:
            temp, tint, floor = int(temp / 2), int(tint / 2), 5
            note = "skin already reads natural, so only a light touch; skip it if the warmth is the mood"
    adjust = {k: val for k, val in (("temp", temp), ("tint", tint)) if abs(val) >= floor}
    if not adjust:
        return []
    return [{
        "finding": f"neutral greys lean {' and '.join(leans)}; {note}",
        "evidence": evidence,
        "step": {"name": "neutralise cast (half strength)", "adjust": adjust},
    }]


def haze(scene: Scene):
    if not segformer_available():
        raise MissingCapability("needs SegFormer")
    small = resize(scene.img, 512, int(512 * scene.img.shape[0] / scene.img.shape[1]))
    dark = min_filter(small.min(-1), 7)
    person = [{"type": "person", "grow": 0.01}] if person_mask(scene) is not None else []
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
                     "mask": {"op": "subtract", "masks": [{"type": "segment", "class": cls}, *person,
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
    if (person := person_mask(scene)) is not None:
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
    H, W = scene.img.shape[:2]
    box = None
    anchor = None
    if scene_has_vision(scene):
        faces = scene.faces()
        if faces:
            x0, y0, x1, y1 = faces[0]["box"]
            anchor = [round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)]
        if (person := person_mask(scene)) is not None:
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


def light(scene: Scene):
    st = _light_stats(scene.img)
    where = f", brightest at the {st['direction']}" if st["direction"] != "even" else ""
    if st["quality"] == "hard":
        finding = f"hard light — {st['tile_spread_stops']:.1f} stops between bright and dark patches{where}; the shadows give this photo its shape"
        hint = "grade for shape: hold the blacks, recover only the hero's highlights, never fully fill the shadows"
    elif st["quality"] == "soft":
        finding = f"soft, flat light — only {st['tile_spread_stops']:.1f} stops of range{where}; the photo has to win on colour and tone, not contrast"
        hint = "win with colour: separate the subject's hues from the background's, or go clean and airy; shape with a vignette rather than contrast"
    else:
        finding = f"balanced light ({st['tile_spread_stops']:.1f} stops of range{where})"
        hint = "a gentle S-curve and one region move on the hero is all the light work this needs"
    if st["warm_split"] >= 0.5:
        finding += "; highlights run warm against cool shade — a golden-hour signature"
        hint += "; keep the split: warm highlights, cool shadows"
    elif st["warm_split"] <= -0.5:
        finding += "; highlights run cooler than the shade"
        hint += "; keep the whites clean and cool rather than warming the whole frame"
    return [{"finding": finding, "evidence": st, "move_hint": hint}]


def eye_path(scene: Scene):
    small = _small(scene.img)
    lum = luma(small)
    _, s, _ = rgb_to_hsv(small)
    lc = np.abs(lum - gaussian(lum, 6))
    score = None
    for m, w in ((lum, 0.5), (lc, 0.3), (s, 0.2)):
        t = _tiles(m)
        part = w * np.clip(t / max(float(t.max()), 1e-6), 0, 1)
        score = part if score is None else score + part
    faces = scene.faces() if scene_has_vision(scene) else []
    if faces:
        x0, y0, x1, y1 = faces[0]["box"]
        hero = (int(np.clip((y0 + y1) / 2 * score.shape[0], 0, score.shape[0] - 1)),
                int(np.clip((x0 + x1) / 2 * score.shape[1], 0, score.shape[1] - 1)))
    else:
        hero = np.unravel_index(int(np.argmax(score)), score.shape)
        hero = (int(hero[0]), int(hero[1]))
    hero_score = float(score[hero])
    if hero_score <= 0:
        return []
    rival, ratio = None, 0.0
    for idx in np.argsort(score, None)[::-1][:64]:
        i, j = np.unravel_index(int(idx), score.shape)
        if max(abs(i - hero[0]), abs(j - hero[1])) <= 1:
            continue
        rival, ratio = (int(i), int(j)), float(score[i, j]) / hero_score
        break
    if rival is None:
        return []
    ev = {"hero_tile": list(hero), "rival_tile": list(rival), "rival_ratio": round(ratio, 2)}
    if ratio >= 1.0:
        return [{"finding": f"the {_region_name(rival, score.shape)} of the frame out-pulls the hero ({ratio:.0%} of its eye weight) — the eye lands there first",
                 "evidence": ev,
                 "move_hint": "choose the story: dim and desaturate the rival region, or crop closer and make it the photo"}]
    if ratio <= 0.6:
        return [{"finding": f"the hero already owns the eye (nearest rival at {ratio:.0%}); the edges are untreated",
                 "evidence": ev,
                 "move_hint": "seal it: a vignette at -12 to -18, or a soft linear burn from the busiest edge"}]
    return []


def colour_pairs(scene: Scene):
    small = _small(scene.img)
    h, s, v = rgb_to_hsv(small)
    use = (s > 0.15) & (v > 0.12)
    if use.sum() < 30:
        return []
    hue = np.clip(h[use], 0, 359.999).astype(int)
    w = (s[use] * v[use]).astype(np.float64)
    hist = np.zeros(36)
    np.add.at(hist, hue // 10, w)
    hist += np.roll(hist, 1) * 0.25 + np.roll(hist, -1) * 0.25
    total = float(hist.sum())

    def share(m):
        return float(sum(hist[(m + d) % 36] for d in (-2, -1, 0, 1, 2)) / max(total, 1e-9))

    m1 = int(np.argmax(hist))
    suppressed = hist.copy()
    suppressed[[(m1 + d) % 36 for d in (-2, -1, 0, 1, 2)]] = 0
    m2 = int(np.argmax(suppressed))
    dist = min(abs(m1 - m2), 36 - abs(m1 - m2)) * 10
    if use.mean() >= 0.05 and 140 <= dist <= 180 and share(m1) >= 0.2 and share(m2) >= 0.12:
        n1, n2 = _band_name(m1 * 10 + 5), _band_name(m2 * 10 + 5)
        art = "an" if n1[0] in "aeiou" else "a"
        return [{"finding": f"{art} {n1}-on-{n2} complementary pair is already in the frame — the contrast posters are built on",
                 "evidence": {"names": [n1, n2], "hues": [m1 * 10 + 5, m2 * 10 + 5],
                              "shares": [round(share(m1), 2), round(share(m2), 2)], "separation_deg": dist},
                 "move_hint": f"push the split: saturate the {n1} side, mute or cool the {n2} side — hsl bands, not global vibrance"}]
    if float(s.mean()) < 0.22:
        n = float(use.size)
        for m in range(36):
            near = np.abs(((h * 360) - (m * 10 + 5) + 180) % 360 - 180) <= 15
            cluster = use & near
            csum = float(cluster.sum())
            if not 30 <= csum <= 0.12 * n:
                continue
            if float(s[cluster].mean()) <= 0.45:
                continue
            ys, xs = np.nonzero(cluster)
            name = _band_name(m * 10 + 5)
            pos = _region_name((int(np.median(ys)), int(np.median(xs))), use.shape)
            return [{"finding": f"a single {name} accent in a quiet frame, {pos} — the one colour the eye finds",
                     "evidence": {"accent": name, "hue": m * 10 + 5, "share": round(csum / n, 3),
                                  "accent_sat": round(float(s[cluster].mean()), 2), "mean_sat": round(float(s.mean()), 2)},
                     "move_hint": f"build the grade around it: mute everything else a touch and let the {name} carry the colour"}]
    return []


def separation_potential(scene: Scene):
    person = person_mask(scene)
    if person is None:
        return []
    stops = _stops(scene.img, person, 1 - person)
    if stops >= 0.8:
        return [{"finding": f"the person carries {stops:.1f} stops more light than the surroundings — the separation is already there",
                 "evidence": {"person_vs_background_stops": round(stops, 2)},
                 "move_hint": "lean in: dim the background another 0.2–0.4 EV and the subject pops off the frame"}]
    if stops <= -1.5:
        return [{"finding": f"the person sits {stops:.1f} stops below the background — a silhouette waiting to be committed to",
                 "evidence": {"person_vs_background_stops": round(stops, 2)},
                 "move_hint": "commit to the silhouette: grade the bright background, let the figure stay dark, don't lift it halfway"}]
    return []


CHECKS = [exposure, subject_balance, separation, face, color_cast, haze, sky, distractions, crop]

OPPORTUNITIES = [light, eye_path, colour_pairs, separation_potential]


def run(scene: Scene) -> dict:
    findings, skipped = [], []
    for check in CHECKS:
        try:
            for f in check(scene):
                findings.append({"check": check.__name__, **f})
        except MissingCapability as e:
            skipped.append(f"{check.__name__}: {e}")
    return {"findings": findings, "skipped": skipped}


def run_opportunities(scene: Scene) -> dict:
    found, skipped = [], []
    for check in OPPORTUNITIES:
        try:
            for o in check(scene):
                found.append({"check": check.__name__, **o})
        except MissingCapability as e:
            skipped.append(f"{check.__name__}: {e}")
    return {"opportunities": found, "skipped": skipped}
