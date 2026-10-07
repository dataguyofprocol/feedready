from __future__ import annotations

import numpy as np

from imaging import cv2, gaussian, luma, rgb_to_hsv, skin_mask, srgb_to_linear

LEVELS = ((0.006, "none"), (0.02, "subtle"), (0.05, "clear"))


def level(delta: float) -> str:
    for limit, name in LEVELS:
        if delta < limit:
            return name
    return "strong"


def impact(before: np.ndarray, after: np.ndarray, mask: np.ndarray | None) -> dict:
    d = np.abs(after - before).mean(-1)
    w = np.ones(d.shape, np.float32) if mask is None else mask
    reach = float(w.mean())
    inside = float((d * w).sum() / max(w.sum(), 1e-6))
    return {"delta": round(inside, 4), "reach": round(reach, 3), "level": level(inside),
            "rank_score": inside * np.sqrt(max(reach, 1e-4))}


def _lin_mean(img, w):
    return float((luma(srgb_to_linear(img)) * w).sum() / max(w.sum(), 1e-6))


def _stops(img, a, b):
    return float(np.log2(max(_lin_mean(img, a), 1e-5) / max(_lin_mean(img, b), 1e-5)))


def _box(shape, box):
    H, W = shape[:2]
    m = np.zeros((H, W), np.float32)
    x0, y0, x1, y1 = box
    m[max(0, int(y0 * H)):int(y1 * H), max(0, int(x0 * W)):int(x1 * W)] = 1
    return m


def _skin(img, sel):
    h, s, _ = rgb_to_hsv(img)
    rad = np.deg2rad(h[sel])
    hue = float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())))
    return {"hue": round(hue, 1), "sat": round(float(s[sel].mean()), 3)}


def _local(img, sigma):
    lum = luma(img)
    return float(np.abs(lum - gaussian(lum, sigma)).mean())


def _halo(before, after, person):
    if cv2 is None or person is None or person.mean() < 0.02:
        return None
    m = (person > 0.5).astype(np.uint8)
    S = min(m.shape)
    k1, k2 = max(2, int(0.005 * S)), max(6, int(0.03 * S))
    near = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k1 + 1, 2 * k1 + 1)))
    wide = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k2 + 1, 2 * k2 + 1)))
    ring, far = ((near - m) > 0).astype(np.float32), ((wide - near) > 0).astype(np.float32)
    if ring.sum() < 50 or far.sum() < 50:
        return None
    return _stops(after, ring, far) - _stops(before, ring, far)


def distinctness(images: list[np.ndarray]) -> list[dict]:
    out = []
    small = [cv2.resize(im, (96, 96), interpolation=cv2.INTER_AREA) if cv2 is not None else im[::max(1, im.shape[0] // 96), ::max(1, im.shape[1] // 96)][:96, :96]
             for im in images]
    for i in range(len(small)):
        for j in range(i + 1, len(small)):
            a, b = small[i], small[j]
            h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
            out.append({"pair": [i, j], "delta": round(float(np.abs(a[:h, :w] - b[:h, :w]).mean()), 4)})
    return out


def run(before: np.ndarray, after: np.ndarray, faces: list[list[float]], person: np.ndarray | None,
        vignette: float, steps: list[dict], impacts: list[dict]) -> dict:
    issues, skipped = [], []

    def add(severity, issue, evidence, hint):
        issues.append({"severity": severity, "issue": issue, "evidence": evidence, "hint": hint})

    lum_b, lum_a = luma(before), luma(after)
    clip_b = float((before.max(-1) >= 0.995).mean() * 100)
    clip_a = float((after.max(-1) >= 0.995).mean() * 100)
    if clip_a > 0.5 and clip_a > clip_b + 0.2:
        ys, xs = np.nonzero(after.max(-1) >= 0.995)
        H, W = after.shape[:2]
        where = [round(float(xs.mean()) / W, 2), round(float(ys.mean()) / H, 2)]
        add("fix", f"highlights are blowing out ({clip_a:.1f}% of the frame is pure white, was {clip_b:.1f}%)",
            {"clipped_pct": round(clip_a, 2), "centred_near": where},
            "pull highlights or whites on the step that brightened that area, or mask it out")
    crush_b = float((lum_b <= 0.01).mean() * 100)
    crush_a = float((lum_a <= 0.01).mean() * 100)
    if crush_a > 1.5 and crush_a > crush_b + 1:
        add("consider", f"shadows are crushing to black ({crush_a:.1f}% of the frame)",
            {"crushed_pct": round(crush_a, 2)}, "ease blacks or contrast unless the deep shadows are the look")

    H, W = after.shape[:2]
    subject = None
    skin = skin_mask(before, faces[0]) if faces else None
    if faces and skin is None:
        skipped.append("face checks: the face is covered or too dark to read as skin, so judge it by eye")
    if skin is not None:
        x0, y0, x1, y1 = faces[0]
        subject = skin.astype(np.float32)
        bg = (1 - person) if person is not None else 1 - _box(after.shape, [x0 - (x1 - x0), y0 - 0.1, x1 + (x1 - x0), 1])
        if bg.mean() > 0.05:
            stops = _stops(after, subject, bg)
            if stops < -0.3:
                add("fix", f"the face is {-stops:.1f} stops darker than the background, so the eye lands on the background first",
                    {"face_vs_background_stops": round(stops, 2)},
                    "lift the face (face mask, exposure +0.2 to +0.4) and/or dim the background (person mask inverted)")
        face_luma = float(lum_a[skin].mean())
        if face_luma < 0.3:
            add("fix", f"the face is dark (luma {face_luma:.2f})", {"face_luma": round(face_luma, 3)},
                "lift the face with a face or radial mask")
        elif face_luma > 0.78:
            add("fix", f"the face is washed out (luma {face_luma:.2f})", {"face_luma": round(face_luma, 3)},
                "bring exposure or highlights down on the face")
        sb, sa = _skin(before, skin), _skin(after, skin)
        if sa["sat"] > 0.5 and sa["sat"] > sb["sat"] * 1.3:
            add("fix", f"skin is getting orange (saturation {sb['sat']:.2f} → {sa['sat']:.2f})",
                {"skin_before": sb, "skin_after": sa}, "cut vibrance/saturation, or hsl orange sat -10 to -20")
        drift = (sa["hue"] - sb["hue"] + 180) % 360 - 180
        if abs(drift) > 6 and not 4 <= sa["hue"] <= 42:
            toward = "yellow/green" if drift > 0 else "red/magenta"
            add("fix", f"skin hue drifted {abs(drift):.0f}° toward {toward}", {"skin_before": sb, "skin_after": sa},
                "ease the temp/tint or hsl move that shifted it, or exclude the face from the grade")
    if subject is None and person is not None and person.mean() > 0.02:
        subject = person

    halo = _halo(before, after, person)
    if halo is not None and abs(halo) > 0.08:
        kind = "bright" if halo > 0 else "dark"
        add("fix" if abs(halo) > 0.15 else "consider", f"a {kind} halo rings the subject ({halo:+.2f} stops at the edge compared with the original)",
            {"edge_ring_stops_change": round(halo, 2)},
            "the background move stops short of the outline: no feather on the person mask, grow -0.002 before "
            "invert, or ease the background exposure" if halo > 0 else
            "the background move bites into the outline: use a smaller negative grow, or ease the background exposure")

    if subject is not None and vignette >= 0:
        band = max(2, int(0.08 * min(H, W)))
        edge = np.zeros((H, W), np.float32)
        edge[:band], edge[-band:], edge[:, :band], edge[:, -band:] = 1, 1, 1, 1
        stops = _stops(after, edge, subject)
        if stops > 0.5:
            add("consider", f"the frame edges are {stops:.1f} stops brighter than the subject and pull the eye out",
                {"edges_vs_subject_stops": round(stops, 2)}, "a -10 to -20 vignette, or burn the brightest edge")

    _, s_b, _ = rgb_to_hsv(before)
    _, s_a, _ = rgb_to_hsv(after)
    if s_a.mean() > 0.45 and s_a.mean() > s_b.mean() * 1.4:
        add("consider", f"colours are loud (mean saturation {s_b.mean():.2f} → {s_a.mean():.2f})",
            {"saturation": [round(float(s_b.mean()), 3), round(float(s_a.mean()), 3)]}, "trade saturation for vibrance, or cut 30%")

    sigma = 0.02 * min(H, W)
    lc = _local(after, sigma) / max(_local(before, sigma), 1e-5)
    if lc > 1.6:
        add("consider", f"local contrast is up {lc:.1f}x; it starts to read as HDR",
            {"local_contrast_ratio": round(lc, 2)}, "ease clarity/dehaze, or mask them off skin and sky")

    dark = lum_b < 0.25
    if dark.mean() > 0.05:
        fine_b = float(np.abs(lum_b - gaussian(lum_b, 1.2))[dark].mean())
        fine_a = float(np.abs(lum_a - gaussian(lum_a, 1.2))[dark].mean())
        if fine_a > 1.8 * max(fine_b, 1e-4) and fine_a > 0.006:
            add("consider", "lifted shadows are showing noise", {"shadow_detail_ratio": round(fine_a / max(fine_b, 1e-4), 2)},
                "ease shadows/exposure in the dark areas, or skip texture/sharpen there")

    for step, imp in zip(steps, impacts):
        if imp["level"] == "none" and not step.get("adjust", {}).get("heal"):
            add("consider", f"step '{step.get('name', '')}' makes no visible difference", {"delta": imp["delta"]},
                "drop it, or push it until it earns its place")

    total = float(np.abs(after - before).mean())
    if total < 0.006:
        add("consider", "the whole edit is barely visible", {"mean_change": round(total, 4)},
            "fine if the brief was 'keep it natural'; otherwise commit to the look")

    return {"verdict": "needs work" if any(i["severity"] == "fix" for i in issues) else "clean", "issues": issues,
            "skipped": skipped}
