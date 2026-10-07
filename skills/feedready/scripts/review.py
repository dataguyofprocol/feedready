from __future__ import annotations

import base64
import html
import json
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from imaging import cv2, to_u8

INK = (24, 24, 27)
MUTED = (160, 160, 170)
COLORS = [(255, 94, 58), (52, 199, 89), (10, 132, 255), (255, 204, 0), (191, 90, 242), (100, 210, 255),
          (255, 55, 95), (172, 142, 104)]
LEVEL_FILL = {"none": 0.04, "subtle": 0.25, "clear": 0.6, "strong": 1.0}


def font(size: int):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def thumb(img: np.ndarray, long_edge: int) -> Image.Image:
    im = Image.fromarray(to_u8(img))
    im.thumbnail((long_edge, long_edge), Image.LANCZOS)
    return im


def color(i: int):
    return COLORS[i % len(COLORS)]


def grid_image(img: np.ndarray, faces: list[dict], path: Path, icc: bytes | None = None) -> None:
    im = thumb(img, 1400).convert("RGB")
    W, H = im.size
    draw = ImageDraw.Draw(im, "RGBA")
    f = font(max(12, W // 60))
    for i in range(1, 10):
        x, y = W * i / 10, H * i / 10
        width = 2 if i == 5 else 1
        draw.line([(x, 0), (x, H)], fill=(255, 255, 0, 150), width=width)
        draw.line([(0, y), (W, y)], fill=(255, 255, 0, 150), width=width)
        draw.text((x + 3, 3), f".{i}", fill=(255, 255, 0, 255), font=f, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        draw.text((3, y + 2), f".{i}", fill=(255, 255, 0, 255), font=f, stroke_width=2, stroke_fill=(0, 0, 0, 255))
    for face in faces:
        x0, y0, x1, y1 = face["box"]
        draw.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=(0, 255, 255, 255), width=2)
    im.save(path, quality=90, icc_profile=icc)


def mask_sheet(img: np.ndarray, steps: list[dict], built: list, path: Path, icc: bytes | None = None) -> None:
    tiles = []
    f = font(22)
    for i, (step, m) in enumerate(zip(steps, built)):
        base = img.copy()
        if m is not None:
            base = base * (1 - 0.6 * m[..., None]) + np.array([1.0, 0.1, 0.1]) * 0.6 * m[..., None]
        tile = thumb(base, 520)
        ImageDraw.Draw(tile).text((8, 6), f"{i + 1}. {step.get('name', '')}"[:40], fill="white", font=f,
                                  stroke_width=3, stroke_fill="black")
        tiles.append(tile)
    cols = min(3, len(tiles))
    rows = -(-len(tiles) // cols)
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw + (cols - 1) * 6, rows * th + (rows - 1) * 6), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (tw + 6), (i // cols) * (th + 6)))
    sheet.save(path, quality=88, icc_profile=icc)


def pair(left: np.ndarray, right: np.ndarray, labels: tuple[str, str], path: Path, icc: bytes | None = None,
         height: int = 900) -> None:
    a, b = thumb(left, 4000), thumb(right, 4000)
    a = a.resize((int(a.width * height / a.height), height), Image.LANCZOS)
    b = b.resize((int(b.width * height / b.height), height), Image.LANCZOS)
    sheet = Image.new("RGB", (a.width + b.width + 8, height), "white")
    sheet.paste(a, (0, 0))
    sheet.paste(b, (a.width + 8, 0))
    draw = ImageDraw.Draw(sheet)
    f = font(26)
    for x, label in ((10, labels[0]), (a.width + 18, labels[1])):
        draw.text((x, 8), label, fill="white", font=f, stroke_width=3, stroke_fill="black")
    sheet.save(path, quality=90, icc_profile=icc)


def describe(adjust: dict, look: str | None = None, amount: float | None = None) -> str:
    parts = []
    if look:
        parts.append(f"look {look}" + (f" {amount:g}%" if amount not in (None, 100) else ""))
    for k, v in adjust.items():
        if k == "hsl":
            parts.append("hsl " + " ".join(sorted(v)))
        elif k == "curve":
            parts.append("curve")
        elif isinstance(v, bool):
            parts.append(k)
        elif isinstance(v, (int, float)):
            parts.append(f"{k} {v:+g}")
    return ", ".join(parts) or "no change"


def _anchor(m: np.ndarray) -> tuple[int, int] | None:
    if cv2 is None:
        ys, xs = np.nonzero(m)
        return (int(xs.mean()), int(ys.mean())) if len(xs) else None
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n < 2:
        return None
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    region = np.pad((labels == big).astype(np.uint8), 1)
    dist = cv2.distanceTransform(region, cv2.DIST_L2, 5)[1:-1, 1:-1]
    y, x = np.unravel_index(int(dist.argmax()), dist.shape)
    return int(x), int(y)


def edit_map(img: np.ndarray, steps: list[dict], built: list, path: Path, icc: bytes | None = None,
             long_edge: int = 1000) -> None:
    base = thumb(img, long_edge).convert("RGBA")
    W, H = base.size
    over = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    f, small = font(22), font(17)
    placed, whole = [], []
    for i, m in enumerate(built):
        col = color(i)
        if m is None or float(m.mean()) > 0.92:
            whole.append(i)
            continue
        small_m = Image.fromarray(to_u8(m)).resize((W, H), Image.BILINEAR)
        binary = (np.asarray(small_m) > 100).astype(np.uint8)
        if not binary.any():
            continue
        tint = np.zeros((H, W, 4), np.uint8)
        tint[..., :3] = col
        tint[..., 3] = (np.asarray(small_m).astype(np.float32) * 0.22).astype(np.uint8)
        over = Image.alpha_composite(over, Image.fromarray(tint, "RGBA"))
        draw = ImageDraw.Draw(over)
        if cv2 is not None:
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                if cv2.contourArea(c) < 30:
                    continue
                pts = [tuple(int(v) for v in p[0]) for p in c]
                draw.line(pts + [pts[0]], fill=col + (255,), width=3)
        if (pt := _anchor(binary)) is None:
            continue
        x, y = pt
        for px, py in placed:
            if abs(px - x) < 40 and abs(py - y) < 40:
                y += 44
        placed.append((x, y))
        draw.ellipse([x - 18, y - 18, x + 18, y + 18], fill=col + (255,), outline=(0, 0, 0, 255), width=2)
        draw.text((x, y), str(i + 1), fill="black", font=f, anchor="mm")
    if whole:
        text = "whole photo: " + "  ".join(f"{i + 1}. {steps[i].get('name', '')}" for i in whole)
        tw = int(draw.textlength(text, font=small))
        draw.rounded_rectangle([10, H - 44, 30 + tw, H - 10], 8, fill=(0, 0, 0, 180))
        draw.text((20, H - 27), text, fill="white", font=small, anchor="lm")
    Image.alpha_composite(base, over).convert("RGB").save(path, quality=90, icc_profile=icc)


def _lens(m: np.ndarray | None, W: int, H: int) -> tuple[int, int, int, int]:
    if m is None or float(m.mean()) > 0.5:
        return 0, 0, W, H
    ys, xs = np.nonzero(m > 0.3)
    if not len(xs):
        return 0, 0, W, H
    pad = int(0.08 * min(H, W))
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    x1, y1 = min(W, xs.max() + pad), min(H, ys.max() + pad)
    side = max(x1 - x0, y1 - y0, int(0.25 * min(H, W)))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    x0, y0 = max(0, min(W - side, cx - side // 2)), max(0, min(H - side, cy - side // 2))
    return x0, y0, min(W, x0 + side), min(H, y0 + side)


def cards(before: np.ndarray, singles: list[dict], path: Path, icc: bytes | None = None, tile: int = 330) -> None:
    H, W = before.shape[:2]
    f, small = font(21), font(16)
    text_w = 420
    rows = []
    for c in sorted(singles, key=lambda c: -c["rank_score"]):
        x0, y0, x1, y1 = _lens(c["mask"], W, H)
        a = Image.fromarray(to_u8(before[y0:y1, x0:x1]))
        b = Image.fromarray(to_u8(c["after"][y0:y1, x0:x1]))
        a.thumbnail((tile, tile), Image.LANCZOS)
        b.thumbnail((tile, tile), Image.LANCZOS)
        row_h = max(a.height, 150) + 16
        row = Image.new("RGB", (a.width + b.width + 24 + text_w, row_h), INK)
        row.paste(a, (8, 8))
        row.paste(b, (16 + a.width, 8))
        d = ImageDraw.Draw(row)
        for x, label in ((12, "before"), (20 + a.width, "after")):
            d.text((x, 12), label, fill="white", font=small, stroke_width=2, stroke_fill="black")
        col = color(c["index"])
        tx = a.width + b.width + 34
        d.ellipse([tx, 10, tx + 34, 44], fill=col)
        d.text((tx + 17, 27), str(c["index"] + 1), fill="black", font=f, anchor="mm")
        d.text((tx + 46, 14), c["name"][:30], fill="white", font=f)
        y = 44
        if why := c.get("why"):
            for line in _wrap(d, why, small, text_w - 60)[:3]:
                d.text((tx + 46, y), line, fill=(220, 220, 228), font=small)
                y += 20
        d.text((tx + 46, y + 4), c["summary"][:52], fill=MUTED, font=small)
        d.text((tx + 46, y + 30), f"impact: {c['level']}", fill=col, font=small)
        d.rectangle([tx + 46, y + 54, tx + 46 + 220, y + 62], fill=(50, 50, 56))
        d.rectangle([tx + 46, y + 54, tx + 46 + int(220 * LEVEL_FILL[c["level"]]), y + 62], fill=col)
        rows.append(row)
    width = max(r.width for r in rows)
    sheet = Image.new("RGB", (width, sum(r.height for r in rows)), INK)
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(path, quality=90, icc_profile=icc)


def _wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def board(tiles: list[tuple[str, str, np.ndarray]], path: Path, icc: bytes | None = None, edge: int = 640) -> None:
    ims = [thumb(img, edge) for _, _, img in tiles]
    portrait = sum(im.height > im.width * 1.15 for im in ims) > len(ims) / 2
    n = len(ims)
    cols = n if n <= 3 or (portrait and n <= 4) else 2 if n == 4 else 4 if portrait else 3
    cw, ch = max(im.width for im in ims), max(im.height for im in ims)
    caption = 74
    rows = -(-len(ims) // cols)
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * 10, rows * (ch + caption) + (rows + 1) * 10), INK)
    d = ImageDraw.Draw(sheet)
    big, small = font(26), font(16)
    for i, ((title, sub, _), im) in enumerate(zip(tiles, ims)):
        x = 10 + (i % cols) * (cw + 10)
        y = 10 + (i // cols) * (ch + caption + 10)
        sheet.paste(im, (x + (cw - im.width) // 2, y + (ch - im.height) // 2))
        d.text((x + 4, y + ch + 10), title[:34], fill="white", font=big)
        for j, line in enumerate(_wrap(d, sub, small, cw - 8)[:2]):
            d.text((x + 4, y + ch + 42 + j * 18), line, fill=MUTED, font=small)
    sheet.save(path, quality=88, icc_profile=icc)


def _data_uri(path: Path, edge: int = 1400) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((edge, edge), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=84)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def review_html(title: str, versions: list[dict], path: Path) -> None:
    befores, entries = {}, []
    for v in versions:
        key = str(v["before"])
        if key not in befores:
            befores[key] = _data_uri(v["before"])
        entries.append({"n": v["n"], "note": v.get("note", ""), "after": _data_uri(v["after"]), "before": key})
    data = json.dumps({"befores": befores, "versions": entries})
    path.write_text(PAGE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data.replace("</", "<\\/")))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#141416;--panel:#1d1d21;--ink:#f2f2f5;--muted:#9a9aa6;--line:#2c2c33;--accent:#ff9f43}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
h1{font-size:18px;font-weight:600;margin:0}
.hint{color:var(--muted);font-size:13px}
.stage{position:relative;margin:0 auto;user-select:none;touch-action:none;cursor:ew-resize;background:#000;border-radius:10px;overflow:hidden;max-height:78vh;width:fit-content;max-width:100%}
.stage img{display:block;max-width:100%;max-height:78vh}
.stage img.before{position:absolute;inset:0;width:100%;height:100%;clip-path:inset(0 calc(100% - var(--x)) 0 0)}
.handle{position:absolute;top:0;bottom:0;left:var(--x);width:2px;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.4);transform:translateX(-1px)}
.handle::after{content:"";position:absolute;top:50%;left:50%;width:30px;height:30px;margin:-15px 0 0 -15px;border-radius:50%;background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.5)}
.tag{position:absolute;top:10px;padding:3px 9px;border-radius:6px;background:rgba(0,0,0,.6);font-size:12px;letter-spacing:.04em;text-transform:uppercase}
.tag.l{left:10px}.tag.r{right:10px}
.note{margin:14px auto 0;max-width:760px;color:var(--ink);text-align:center;min-height:1.4em}
nav{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:14px}
nav button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:6px 14px;font:inherit;cursor:pointer}
nav button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
</style></head><body><main>
<header><h1>__TITLE__</h1><span class="hint">Drag to compare &middot; &larr; &rarr; move the split &middot; 1&ndash;9 pick a version &middot; hold B for before</span></header>
<div class="stage" id="stage" style="--x:50%">
<img class="after" id="after" alt="after"><img class="before" id="before" alt="before">
<div class="handle"></div><span class="tag l">before</span><span class="tag r" id="rtag">after</span>
</div>
<p class="note" id="note"></p>
<nav id="nav"></nav>
</main>
<script>
const D=__DATA__;
const stage=document.getElementById("stage"),after=document.getElementById("after"),before=document.getElementById("before");
const note=document.getElementById("note"),nav=document.getElementById("nav"),rtag=document.getElementById("rtag");
let x=50,cur=D.versions.length-1;
function setX(v){x=Math.max(0,Math.min(100,v));stage.style.setProperty("--x",x+"%")}
function show(i){cur=i;const v=D.versions[i];after.src=v.after;before.src=D.befores[v.before];note.textContent=v.note||"";rtag.textContent="v"+v.n;
[...nav.children].forEach((b,j)=>b.setAttribute("aria-pressed",j===i))}
D.versions.forEach((v,i)=>{const b=document.createElement("button");b.textContent="v"+v.n;b.onclick=()=>show(i);nav.appendChild(b)});
function fromEvent(e){const r=stage.getBoundingClientRect();setX((e.clientX-r.left)/r.width*100)}
let drag=false;
stage.addEventListener("pointerdown",e=>{drag=true;stage.setPointerCapture(e.pointerId);fromEvent(e)});
stage.addEventListener("pointermove",e=>{if(drag)fromEvent(e)});
stage.addEventListener("pointerup",()=>{drag=false});
let held=null;
addEventListener("keydown",e=>{if(e.key==="ArrowLeft")setX(x-5);else if(e.key==="ArrowRight")setX(x+5);
else if((e.key==="b"||e.key==="B")&&held===null){held=x;setX(100)}
else if(/^[1-9]$/.test(e.key)&&+e.key<=D.versions.length)show(+e.key-1)});
addEventListener("keyup",e=>{if((e.key==="b"||e.key==="B")&&held!==null){setX(held);held=null}});
show(cur);
</script></body></html>
"""
