import functools, math, os, shutil, subprocess
from PIL import Image, ImageDraw, ImageFont

WORK = os.path.expanduser("~/.cache/feedready/work/1-012c6c15")
ASSETS = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.expanduser("~/.cache/feedready/hero")
FRAMES = os.path.join(TMP, "frames")
S = 4
OUT = 2
W, H = 880, 520
FPS = 24
BG = (24, 22, 21)
INK = (246, 241, 234)
MUTED = (160, 152, 144)
ORANGE = (242, 100, 60)
RED = (232, 72, 72)
GREEN = (88, 196, 120)
FONTS = os.path.expanduser("~/Library/Fonts")


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size * S)


SERIF = lambda s: font("InstrumentSerif-Regular.ttf", s)
SANS = lambda s: font("Geist-Regular.ttf", s)
SANSM = lambda s: font("Geist-Medium.ttf", s)
SANSB = lambda s: font("Geist-SemiBold.ttf", s)


def load(p):
    return Image.open(p).convert("RGB")


before = load(f"{WORK}/versions/before-0-160-1066-1332.jpg")
v3 = load(f"{WORK}/versions/v3.jpg")
v4 = load(f"{WORK}/versions/v4.jpg")
board = load(f"{WORK}/board.jpg")
TILES = [board.crop((531, 10, 1044, 649)), board.crop((1054, 10, 1566, 649)), board.crop((1576, 10, 2088, 649))]
TILE_NAMES = [("A", "Clean"), ("B", "Cinematic"), ("C", "Mono editorial")]

os.makedirs(TMP, exist_ok=True)
subprocess.run(["rsvg-convert", "-w", str(150 * S), f"{ASSETS}/art/mascot.svg", "-o", f"{TMP}/mascot.png"], check=True)
MASCOT = Image.open(f"{TMP}/mascot.png").convert("RGBA")

PX, PY, PW, PH = 36, 36, 358, 448
RX = 432


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ramp(t, a, b):
    return ease((t - a) / (b - a)) if b > a else float(t >= a)


def canvas():
    return Image.new("RGB", (W * S, H * S), BG)


@functools.lru_cache(maxsize=None)
def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r * S, fill=255)
    return m


def rounded(img, r):
    return rounded_mask(img.size, r)


_sized = {}


def sized(img, w, h):
    key = (id(img), w, h)
    if key not in _sized:
        _sized[key] = img.resize((w, h), Image.LANCZOS)
    return _sized[key]


def paste_photo(c, img, box=(PX, PY, PW, PH), alpha=1.0, r=14):
    x, y, w, h = box
    im = sized(img, int(w * S), int(h * S))
    m = rounded(im, r)
    if alpha < 1:
        m = m.point(lambda v: int(v * alpha))
    c.paste(im, (int(x * S), int(y * S)), m)


def overlay(c):
    return Image.new("RGBA", c.size, (0, 0, 0, 0))


def comp(c, o):
    c.paste(Image.alpha_composite(c.convert("RGBA"), o).convert("RGB"))


def wrap(d, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) <= width * S:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def text(d, xy, s, f, fill, width=None, lh=1.2, alpha=1.0):
    x, y = xy
    lines = wrap(d, s, f, width) if width else [s]
    fill = tuple(fill[:3]) + (int(255 * alpha),)
    for i, ln in enumerate(lines):
        d.text((x * S, y * S + i * f.size * lh), ln, font=f, fill=fill)
    return y + len(lines) * f.size * lh / S


def label(d, step, name, alpha=1.0):
    d.text((RX * S, 44 * S), f"{step}  ·  {name}", font=SANSM(13), fill=ORANGE + (int(255 * alpha),))


def bubble(o, xy, s, who, t, width=300):
    if t <= 0:
        return 0
    d = ImageDraw.Draw(o)
    f = SANS(17)
    lines = wrap(d, s, f, width - 32)
    tw = max(d.textlength(l, font=f) for l in lines) / S
    bw, bh = tw + 32, len(lines) * 17 * 1.3 + 22
    x, y = xy
    if who == "you":
        x = x + width - bw
    k = ease(t)
    dy = (1 - k) * 10
    a = int(255 * k)
    fill = (58, 54, 51, a) if who == "claude" else (242, 100, 60, a)
    d.rounded_rectangle((x * S, (y + dy) * S, (x + bw) * S, (y + dy + bh) * S), 16 * S, fill=fill)
    tag = SANSM(11)
    d.text(((x + 16) * S, (y + dy - 16) * S), "you" if who == "you" else "claude", font=tag, fill=MUTED + (a,))
    for i, ln in enumerate(lines):
        d.text(((x + 16) * S, (y + dy + 11) * S + i * f.size * 1.3), ln, font=f, fill=(255, 255, 255, a))
    return bh


def footer(o, alpha=1.0):
    d = ImageDraw.Draw(o)
    m = MASCOT.resize((26 * S, 26 * S), Image.LANCZOS)
    if alpha < 1:
        m.putalpha(m.getchannel("A").point(lambda v: int(v * alpha)))
    o.alpha_composite(m, ((W - 132) * S, (H - 42) * S))
    d.text(((W - 100) * S, (H - 37) * S), "feedready", font=SANSM(14), fill=MUTED + (int(255 * alpha),))


def dot(d, cx, cy, n, a, col=ORANGE):
    r = 13
    d.ellipse(((cx - r - 4) * S, (cy - r - 4) * S, (cx + r + 4) * S, (cy + r + 4) * S), fill=col[:3] + (int(70 * a),))
    d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=col[:3] + (int(255 * a),))
    f = SANSB(14)
    tw = d.textlength(str(n), font=f) / S
    d.text(((cx - tw / 2) * S, (cy - 9.5) * S), str(n), font=f, fill=(255, 255, 255, int(255 * a)))


def check(d, cx, cy, ok, a):
    col = (GREEN if ok else RED) + (int(255 * a),)
    r = 11
    d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=col)
    w = (255, 255, 255, int(255 * a))
    if ok:
        d.line([((cx - 5) * S, cy * S), ((cx - 1) * S, (cy + 4) * S), ((cx + 6) * S, (cy - 5) * S)], fill=w, width=3 * S, joint="curve")
    else:
        d.line([((cx - 4) * S, (cy - 4) * S), ((cx + 4) * S, (cy + 4) * S)], fill=w, width=3 * S)
        d.line([((cx + 4) * S, (cy - 4) * S), ((cx - 4) * S, (cy + 4) * S)], fill=w, width=3 * S)


def dashed_rect(d, box, col, a, t):
    x0, y0, x1, y1 = box
    per = 2 * ((x1 - x0) + (y1 - y0))
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    drawn, limit = 0.0, per * ease(t)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        seg = math.hypot(bx - ax, by - ay)
        n = int(seg // 8)
        for i in range(n):
            if drawn + i * 8 > limit:
                return
            if i % 2 == 0:
                sx, sy = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
                ex, ey = ax + (bx - ax) * (i + 1) / n, ay + (by - ay) * (i + 1) / n
                d.line([(sx * S, sy * S), (ex * S, ey * S)], fill=col + (int(255 * a),), width=3 * S)
        drawn += seg


def scene_hand(t, dur):
    c = canvas()
    paste_photo(c, before, alpha=ramp(t, 0, 0.4))
    o = overlay(c)
    d = ImageDraw.Draw(o)
    a = ramp(t, 0.1, 0.5)
    text(d, (RX, 70), "Hand Claude a photo.", SERIF(44), INK, width=420, alpha=a)
    text(d, (RX, 128), "Say where it's going. That's the whole brief.", SANS(18), MUTED, width=400, alpha=a)
    bubble(o, (RX, 210), "make this insta ready", "you", ramp(t, 0.7, 1.1), width=400)
    footer(o)
    comp(c, o)
    return c


FINDINGS = [
    ((0.55, 0.40), "You're 3.9 stops darker than the sky"),
    ((0.24, 0.13), "10.5% of the sky is pure white"),
    ((0.44, 0.72), "A bright logo on the glove pulls the eye"),
]


def scene_read(t, dur):
    c = canvas()
    paste_photo(c, before)
    o = overlay(c)
    d = ImageDraw.Draw(o)
    sweep = ramp(t, 0.1, 1.1)
    if 0 < sweep < 1:
        y = PY + PH * sweep
        for i in range(40):
            a = int(90 * (1 - i / 40))
            d.line([(PX * S, (y - i) * S), ((PX + PW) * S, (y - i) * S)], fill=ORANGE + (a // 2,), width=S)
        d.line([(PX * S, y * S), ((PX + PW) * S, y * S)], fill=ORANGE + (255,), width=2 * S)
        for gx in range(1, 8):
            d.line([((PX + PW * gx / 8) * S, PY * S), ((PX + PW * gx / 8) * S, y * S)], fill=(255, 255, 255, 40), width=S)
        for gy in range(1, 10):
            yy = PY + PH * gy / 10
            if yy < y:
                d.line([(PX * S, yy * S), ((PX + PW) * S, yy * S)], fill=(255, 255, 255, 40), width=S)
    label(d, "1", "READS THE PHOTO")
    text(d, (RX, 70), "It measures what's holding it back.", SERIF(40), INK, width=420)
    y = 186
    for i, ((fx, fy), s) in enumerate(FINDINGS):
        a = ramp(t, 1.2 + i * 0.75, 1.5 + i * 0.75)
        if a <= 0:
            continue
        dot(d, PX + PW * fx, PY + PH * fy, i + 1, a)
        dot(d, RX + 14, y + 12, i + 1, a)
        text(d, (RX + 40, y + 1 + (1 - a) * 6), s, SANS(18), INK, width=370, alpha=a)
        y += 58
    footer(o)
    comp(c, o)
    return c


def scene_directions(t, dur):
    c = canvas()
    tw, th, gap = 250, 312, 20
    x0 = (W - (3 * tw + 2 * gap)) / 2
    o = overlay(c)
    d = ImageDraw.Draw(o)
    out_c = ramp(t, 1.7, 2.1)
    pick = ramp(t, 2.8, 3.1)
    for i, tile in enumerate(TILES):
        a = ramp(t, 0.1 + i * 0.2, 0.5 + i * 0.2)
        if i == 2:
            a *= 1 - 0.7 * out_c
        x = x0 + i * (tw + gap)
        paste_photo(c, tile, (x, 28, tw, th), alpha=a, r=12)
        k, nm = TILE_NAMES[i]
        d.text((x * S, (28 + th + 10) * S), k, font=SANSB(15), fill=ORANGE + (int(255 * a),))
        d.text(((x + 16) * S, (28 + th + 10) * S), nm, font=SANS(15), fill=INK + (int(255 * a),))
        if i == 1 and pick > 0:
            d.rounded_rectangle(((x - 5) * S, 23 * S, (x + tw + 5) * S, (28 + th + 5) * S), 16 * S, outline=ORANGE + (int(255 * pick),), width=3 * S)
        if i == 2 and out_c > 0:
            d.line([((x + 20) * S, (28 + th / 2) * S), ((x + 20 + (tw - 40) * out_c) * S, (28 + th / 2) * S)], fill=(255, 255, 255, int(200 * out_c)), width=3 * S)
    d.text((x0 * S, 400 * S), "2  ·  SHOWS YOU DIRECTIONS", font=SANSM(13), fill=ORANGE + (255,))
    text(d, (x0, 422), "Three looks, rendered. Not described.", SERIF(30), INK, width=330, lh=1.1)
    bubble(o, (450, 398), "C is out. what do you suggest?", "you", ramp(t, 1.5, 1.9), width=W - x0 - 450)
    bubble(o, (450, 456), "B's dusk mood, with A's lift on you.", "claude", ramp(t, 2.6, 3.0), width=W - x0 - 450)
    comp(c, o)
    return c


PANTS = (0.30, 0.70, 0.60, 0.995)


def scene_review(t, dur):
    c = canvas()
    swap = ramp(t, 2.4, 2.9)
    paste_photo(c, v3)
    if swap > 0:
        paste_photo(c, v4, alpha=swap)
    o = overlay(c)
    d = ImageDraw.Draw(o)
    tag = "v4" if swap > 0.5 else "v3"
    d.rounded_rectangle(((PX + 14) * S, (PY + 14) * S, (PX + 58) * S, (PY + 40) * S), 8 * S, fill=(0, 0, 0, 150))
    d.text(((PX + 25) * S, (PY + 18) * S), tag, font=SANSB(15), fill=(255, 255, 255, 255))
    box = (PX + PW * PANTS[0], PY + PH * PANTS[1], PX + PW * PANTS[2], PY + PH * PANTS[3] - 4)
    flag = ramp(t, 0.6, 1.4)
    if flag > 0:
        col = tuple(int(RED[i] + (GREEN[i] - RED[i]) * swap) for i in range(3))
        dashed_rect(d, box, col, 1.0, flag)
    label(d, "3", "EDITS IN ROUNDS")
    text(d, (RX, 70), "It checks its own work before you see it.", SERIF(40), INK, width=420)
    a1 = ramp(t, 1.2, 1.6)
    if a1 > 0:
        check(d, RX + 11, 222, False, a1)
        text(d, (RX + 32, 210), "v3: the black pants went muddy brown.", SANS(18), INK, width=380, alpha=a1 * (1 - 0.5 * swap))
    a2 = ramp(t, 2.8, 3.2)
    if a2 > 0:
        check(d, RX + 11, 292, True, a2)
        text(d, (RX + 32, 280), "v4: the lift fades down the legs.", SANS(18), INK, width=380, alpha=a2)
    a3 = ramp(t, 3.4, 3.8)
    if a3 > 0:
        text(d, (RX, 360), "You only ever see v4.", SANSM(18), ORANGE, alpha=a3)
    footer(o)
    comp(c, o)
    return c


def scene_ship(t, dur):
    c = canvas()
    k = t / dur
    pos = 0.88 - 0.7 * ease(k / 0.45) if k < 0.45 else 0.18 + 0.37 * ease((k - 0.45) / 0.4)
    paste_photo(c, v4)
    left = sized(before, int(PW * S), int(PH * S))
    cut = int(PW * S * pos)
    piece = left.crop((0, 0, cut, left.size[1]))
    m = rounded(left, 14).crop((0, 0, cut, left.size[1]))
    c.paste(piece, (PX * S, PY * S), m)
    o = overlay(c)
    d = ImageDraw.Draw(o)
    lx = (PX + PW * pos) * S
    d.line([(lx, PY * S), (lx, (PY + PH) * S)], fill=(255, 255, 255, 255), width=3 * S)
    cy = (PY + PH / 2) * S
    d.ellipse((lx - 16 * S, cy - 16 * S, lx + 16 * S, cy + 16 * S), fill=(255, 255, 255, 255))
    d.polygon([(lx - 9 * S, cy), (lx - 3 * S, cy - 6 * S), (lx - 3 * S, cy + 6 * S)], fill=BG + (255,))
    d.polygon([(lx + 9 * S, cy), (lx + 3 * S, cy - 6 * S), (lx + 3 * S, cy + 6 * S)], fill=BG + (255,))
    for s_, x in (("before", PX + 12), ("after", PX + PW - 62)):
        d.rounded_rectangle((x * S, (PY + PH - 38) * S, (x + 54) * S, (PY + PH - 12) * S), 8 * S, fill=(0, 0, 0, 150))
        tw = d.textlength(s_, font=SANSM(13)) / S
        d.text(((x + 27 - tw / 2) * S, (PY + PH - 34) * S), s_, font=SANSM(13), fill=(255, 255, 255, 255))
    label(d, "4", "SHIPS IT")
    text(d, (RX, 70), "Ready for the feed.", SERIF(44), INK, width=420)
    bubble(o, (RX, 150), "ship it", "you", ramp(t, 0.2, 0.6), width=400)
    y = 230
    for i, s_ in enumerate(["Full resolution, cropped 4:5", "Display P3 kept for iPhone shots", "Metadata stripped, so no GPS"]):
        a = ramp(t, 1.0 + i * 0.4, 1.4 + i * 0.4)
        if a > 0:
            check(d, RX + 11, y + 12, True, a)
            text(d, (RX + 32, y), s_, SANS(18), INK, alpha=a)
        y += 40
    footer(o)
    comp(c, o)
    return c


def scene_end(t, dur):
    c = canvas()
    o = overlay(c)
    d = ImageDraw.Draw(o)
    a = ramp(t, 0.0, 0.5)
    bob = math.sin(t * 5) * 3 * a
    m = MASCOT.copy()
    m.putalpha(m.getchannel("A").point(lambda v: int(v * a)))
    o.alpha_composite(m, (int((W / 2 - 75) * S), int((70 + bob) * S)))
    f = SERIF(56)
    s_ = "feedready"
    tw = d.textlength(s_, font=f) / S
    d.text(((W / 2 - tw / 2) * S, 240 * S), s_, font=f, fill=INK + (int(255 * a),))
    f2 = SANS(19)
    for i, ln in enumerate(["Hand Claude a phone photo.", "Get back one that's ready for the feed."]):
        tw = d.textlength(ln, font=f2) / S
        d.text(((W / 2 - tw / 2) * S, (318 + i * 28) * S), ln, font=f2, fill=MUTED + (int(255 * ramp(t, 0.3, 0.8)),))
    comp(c, o)
    return c


SCENES = [(scene_hand, 2.4), (scene_read, 4.4), (scene_directions, 4.6), (scene_review, 4.8), (scene_ship, 4.6), (scene_end, 2.8)]
XF = 0.35


def render():
    shutil.rmtree(FRAMES, ignore_errors=True)
    os.makedirs(FRAMES)
    n = 0
    prev_tail = None
    xf = int(XF * FPS)
    for fn, dur in SCENES:
        for i in range(int(dur * FPS)):
            img = fn(i / FPS, dur)
            if prev_tail is not None and i < xf:
                img = Image.blend(prev_tail, img, (i + 1) / (xf + 1))
            img.resize((W * OUT, H * OUT), Image.LANCZOS).save(f"{FRAMES}/{n:04d}.png", compress_level=1)
            n += 1
        prev_tail = fn(dur, dur)
    return n


def encode_webp(n, out, opts):
    frames = [f"{FRAMES}/{i:04d}.png" for i in range(n)]
    subprocess.run(["img2webp", "-loop", "0"] + opts + ["-d", str(round(1000 / FPS))] + frames + ["-o", out], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


WEBP = ["-lossy", "-q", "85", "-m", "4", "-kmax", "4", "-sharp_yuv"]


def main():
    n = render()
    encode_webp(n, f"{ASSETS}/hero.webp", WEBP)
    pal = f"fps=12,scale={W}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", f"{FRAMES}/%04d.png", "-vf", pal, "-loop", "0", f"{ASSETS}/hero.gif"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", f"{FRAMES}/%04d.png", "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "16", f"{TMP}/hero.mp4"], check=True)
    shutil.rmtree(FRAMES)
    print(n, "frames", f"{ASSETS}/hero.webp", f"{ASSETS}/hero.gif", f"{TMP}/hero.mp4")


if __name__ == "__main__":
    main()
