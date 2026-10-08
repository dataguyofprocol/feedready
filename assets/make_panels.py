import json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ASSETS, "..", "skills", "feedready", "scripts"))
from review import LEVEL_FILL, color
from pathlib import Path
from detect import Scene
from imaging import load_rgb
import masks as mask_engine

SESSION = os.path.expanduser("~/.cache/feedready/work/1-012c6c15")
WORK = f"{SESSION}/versions"
FONTS = os.path.expanduser("~/Library/Fonts")
TOP = [(5, "strong"), (1, "clear"), (7, "strong")]
CARD_Y = [8, 354, 700]
CROP = (0, 200, 1333, 1866)
REGIONS = [
    (1, "Sky", "SegFormer sky class", "highlights −50, whites −15 pull the blown white back"),
    (2, "Snow peaks", "mountain class, minus you and the sky", "clarity +25, dehaze +15 for bite"),
    (7, "You", "Vision person mask", "lifted out of the shadow, fading down the legs"),
    (8, "Eyes", "a radial, placed off the inspect grid", "exposure +0.4 so they land"),
    (3, "Glove logo", "a brush, bright pixels only", "exposure −0.8 so it stops pulling the eye"),
    (6, "Valley", "a gradient, minus you", "exposure −0.4 frames you from below"),
    (0, "Reflective strip", "a brush", "healed away, filled from around it"),
]
S, OUT = 4, 2
W = 880
BG = (24, 22, 21)
INK = (246, 241, 234)
MUTED = (160, 152, 144)
SOFT = (205, 198, 190)
TRACK = (52, 48, 45)
ORANGE = (242, 100, 60)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), int(size * S))


def wrap(d, text, f, width):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=f) <= width * S:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def rounded(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r * S, fill=255)
    return m


def paste(c, im, x, y, w, h, r=10):
    im = im.resize((int(w * S), int(h * S)), Image.LANCZOS)
    c.paste(im, (int(x * S), int(y * S)), rounded(im.size, r))


def panel(h):
    c = Image.new("RGBA", (W * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(c).rounded_rectangle((0, 0, W * S - 1, h * S - 1), 22 * S, fill=BG + (255,))
    return c


def save(c, h, name):
    c.resize((W * OUT, h * OUT), Image.LANCZOS).save(f"{ASSETS}/{name}", quality=92, method=6)
    print(f"{ASSETS}/{name}")


def chip(d, x, y, s):
    f = font("Geist-Medium.ttf", 11)
    tw = d.textlength(s, font=f) / S
    d.rounded_rectangle((x * S, y * S, (x + tw + 14) * S, (y + 20) * S), 6 * S, fill=(0, 0, 0, 150))
    d.text(((x + 7) * S, (y + 3.5) * S), s, font=f, fill=(255, 255, 255, 255))


def dot(d, x, y, n, col, r=11):
    f = font("Geist-SemiBold.ttf", 12.5)
    d.ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=col + (255,), outline=(0, 0, 0, 255), width=int(1.5 * S))
    s = str(n)
    tw = d.textlength(s, font=f) / S
    d.text(((x - tw / 2) * S, (y - 8) * S), s, font=f, fill=(0, 0, 0, 255))


def summary(step):
    if "look" in step:
        return f"look: {step['look']} {step.get('amount', 100)}%"
    return ", ".join(f"{k} {v:+g}" if not isinstance(v, bool) else k for k, v in step.get("adjust", {}).items())


def region_masks():
    working = Path(SESSION) / "working.png"
    scene = Scene(Path(SESSION), working, load_rgb(working))
    steps = json.load(open(f"{WORK}/v4.json"))["steps"]
    out = {}
    for idx, *_ in REGIONS:
        spec = {"type": "person"} if idx == 7 else steps[idx]["mask"]
        m = np.clip(mask_engine.build(spec, scene), 0, 1)
        out[idx] = Image.fromarray((m * 255).astype(np.uint8)).crop(CROP)
    return out


def anchor(m):
    a = np.asarray(m, dtype=np.float32) / 255
    ys, xs = np.nonzero(a > 0.5)
    if not len(xs):
        ys, xs = np.nonzero(a > a.max() * 0.5)
    i = np.argmin((xs - xs.mean()) ** 2 + (ys - ys.mean()) ** 2)
    return xs[i] / a.shape[1], ys[i] / a.shape[0]


def sees():
    h = 560
    c = panel(h)
    before = Image.open(f"{WORK}/before-0-160-1066-1332.jpg").convert("RGB")
    top = 64
    ph = h - top - 28
    pw = ph * 1066 / 1332
    px = 28
    size = (int(pw * S), int(ph * S))
    photo = before.resize(size, Image.LANCZOS).convert("RGBA")
    tint = Image.new("RGBA", size, (0, 0, 0, 0))
    lines = Image.new("RGBA", size, (0, 0, 0, 0))
    anchors = []
    built = region_masks()
    for idx, *_ in REGIONS:
        m = built[idx].resize(size, Image.LANCZOS)
        col = color(idx)
        a = np.asarray(m, dtype=np.float32) / 255
        layer = np.zeros(size[::-1] + (4,), np.uint8)
        layer[..., :3] = col
        layer[..., 3] = (a * 110).astype(np.uint8)
        tint = Image.alpha_composite(tint, Image.fromarray(layer))
        hard = m.point(lambda v: 255 if v > 127 else 0)
        edge = np.asarray(hard.filter(ImageFilter.MaxFilter(9)), np.int16) - np.asarray(hard.filter(ImageFilter.MinFilter(9)), np.int16)
        el = np.zeros(size[::-1] + (4,), np.uint8)
        el[..., :3] = col
        el[..., 3] = np.where(edge > 0, 230, 0)
        lines = Image.alpha_composite(lines, Image.fromarray(el))
        anchors.append((idx, anchor(m)))
    photo = Image.alpha_composite(Image.alpha_composite(photo, tint), lines)
    c.paste(photo, (int(px * S), int(top * S)), rounded(size, 14))
    o = Image.new("RGBA", c.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(o)
    hf = font("Geist-Medium.ttf", 12.5)
    d.text((px * S, 32 * S), "WHAT CLAUDE SEES IN THIS PHOTO", font=hf, fill=ORANGE + (255,))
    placed = []
    for idx, (ax, ay) in anchors:
        x, y = px + ax * pw, top + ay * ph
        for qx, qy in placed:
            if abs(qx - x) < 24 and abs(qy - y) < 24:
                y += 26
        placed.append((x, y))
        dot(d, x, y, idx + 1, color(idx))
    rx = px + pw + 32
    width = W - 28 - rx
    d.text((rx * S, 32 * S), "EACH PART, HANDLED ITS OWN WAY", font=hf, fill=MUTED + (255,))
    name_f, how_f, what_f = font("Geist-Medium.ttf", 16.5), font("Geist-Regular.ttf", 12.5), font("Geist-Regular.ttf", 14)
    row_h = ph / len(REGIONS)
    for r, (idx, name, how, what) in enumerate(REGIONS):
        y = top + r * row_h + 2
        dot(d, rx + 11, y + 11, idx + 1, color(idx))
        d.text(((rx + 32) * S, (y + 1) * S), name, font=name_f, fill=INK + (255,))
        nw = d.textlength(name, font=name_f) / S
        d.text(((rx + 32 + nw + 10) * S, (y + 4.5) * S), how, font=how_f, fill=MUTED + (255,))
        d.text(((rx + 32) * S, (y + 25) * S), what, font=what_f, fill=SOFT + (255,))
        assert d.textlength(how, font=how_f) / S + nw + 42 <= width, name
        assert d.textlength(what, font=what_f) / S + 32 <= width, name
    save(Image.alpha_composite(c, o), h, "sees.webp")


def work():
    h = 540
    c = panel(h)
    steps = json.load(open(f"{WORK}/v4.json"))["steps"]
    cards = Image.open(f"{WORK}/v4-cards.jpg").convert("RGB")
    o = Image.new("RGBA", c.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(o)
    hf = font("Geist-Medium.ttf", 12.5)
    d.text((28 * S, 32 * S), "EACH EDIT ALONE, RANKED BY HOW MUCH IT CHANGED THE PHOTO", font=hf, fill=ORANGE + (255,))
    top, tile, gap = 64, 160, 8
    th = tile * 308 / 330
    row_h = (h - top - 28 + 12) / 3
    tx = 28 + 2 * tile + gap + 28
    width = W - 28 - tx
    name_f, why_f, sum_f, lvl_f = font("Geist-Medium.ttf", 19), font("Geist-Regular.ttf", 15), font("GeistMono-Regular.ttf", 12.5), font("Geist-Medium.ttf", 13)
    for r, ((idx, level), cy) in enumerate(zip(TOP, CARD_Y)):
        y = top + r * row_h
        paste(c, cards.crop((8, cy + 30, 338, cy + 338)), 28, y, tile, th, 10)
        paste(c, cards.crop((346, cy + 30, 676, cy + 338)), 28 + tile + gap, y, tile, th, 10)
        chip(d, 34, y + th - 26, "before")
        chip(d, 34 + tile + gap, y + th - 26, "after")
        col = color(idx)
        step = steps[idx]
        dot(d, tx + 12, y + 13, idx + 1, col, 12)
        yy = y + 1
        for ln in wrap(d, step["name"], name_f, width - 34):
            d.text(((tx + 34) * S, yy * S), ln, font=name_f, fill=INK + (255,))
            yy += 25
        yy += 6
        for ln in wrap(d, step.get("why", ""), why_f, width)[:3]:
            d.text((tx * S, yy * S), ln, font=why_f, fill=SOFT + (255,))
            yy += 20
        yy += 6
        d.text((tx * S, yy * S), summary(step), font=sum_f, fill=MUTED + (255,))
        yy += 26
        lbl = f"impact: {level}"
        d.text((tx * S, yy * S), lbl, font=lvl_f, fill=col + (255,))
        lw = d.textlength(lbl, font=lvl_f) / S
        bx, bw, by = tx + lw + 12, 160, yy + 6
        d.rounded_rectangle((bx * S, by * S, (bx + bw) * S, (by + 6) * S), 3 * S, fill=TRACK + (255,))
        d.rounded_rectangle((bx * S, by * S, (bx + bw * LEVEL_FILL[level]) * S, (by + 6) * S), 3 * S, fill=col + (255,))
        assert yy + 18 <= y + row_h, (step["name"], yy + 18, y + row_h)
    save(Image.alpha_composite(c, o), h, "work.webp")


if __name__ == "__main__":
    sees()
    work()
