from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image, JpegImagePlugin

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "feedready" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import detect
import imaging
from imaging import gaussian, icc_profile, is_p3, load_rgb, luma, rgb_to_hsv, save_png16, skin_mask, srgb_to_linear

CACHE = Path.home() / ".cache" / "feedready"
CORPUS = CACHE / "corpus"
EVAL = CACHE / "eval"
GOLDEN = Path(__file__).resolve().parent / "golden"
P3_ICC = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
FAILS: list[str] = []
REGEN = False
_TMP = None

COLORCHECKER = [
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
]

SHARMA = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
]


def check(name, ok, detail=""):
    print(f"  {'ok ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


def skip(name, why=""):
    print(f"  skip {name}{f' ({why})' if why else ''}")


def tmp() -> Path:
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="feedready-test-"))
    return _TMP


@contextmanager
def isolated_work():
    old = os.environ.get("FEEDREADY_WORK")
    os.environ["FEEDREADY_WORK"] = str(tmp() / "work")
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("FEEDREADY_WORK", None)
        else:
            os.environ["FEEDREADY_WORK"] = old


def card() -> np.ndarray:
    rng = np.random.default_rng(0)
    h, w = 400, 600
    x = np.linspace(0, 1, w, dtype=np.float32)
    img = np.repeat(np.repeat(x[None, :, None], h, 0), 3, 2) * 0.9 + 0.05
    colours = [(0.8, 0.2, 0.2), (0.9, 0.6, 0.2), (0.2, 0.7, 0.3), (0.2, 0.4, 0.85), (0.6, 0.3, 0.7), (0.5, 0.5, 0.5)]
    for i, c in enumerate(colours):
        img[250:330, 20 + i * 95:100 + i * 95] = c
    texture = gaussian(rng.normal(0, 0.06, (h, w)).astype(np.float32), 1.5)
    img[20:120] += texture[20:120, :, None]
    return img.clip(0, 1)


def hazy_card() -> np.ndarray:
    return card() * 0.55 + 0.4


def checker() -> np.ndarray:
    rng = np.random.default_rng(7)
    img = np.full((400, 720, 3), 0.18, np.float32)
    for i, rgb in enumerate(COLORCHECKER):
        row, col = divmod(i, 6)
        img[20 + row * 88:20 + row * 88 + 72, 16 + col * 116:16 + col * 116 + 104] = np.array(rgb, np.float32) / 255
    img += gaussian(rng.normal(0, 0.015, img.shape[:2]).astype(np.float32), 1)[..., None]
    return img.clip(0, 1)


def metrics(img):
    _, s, _ = rgb_to_hsv(img)
    lum = luma(img)
    lin = srgb_to_linear(img)
    return {
        "mean": float(lum.mean()),
        "dark": float(lum[:, :120].mean()),
        "bright": float(lum[:, -120:].mean()),
        "sat": float(s[250:330].mean()),
        "blue_sat": float(s[250:330, 305:385].mean()),
        "rb": float(lin[..., 0].mean() / lin[..., 2].mean()),
        "green": float(lin[..., 1].mean() / lin.mean()),
        "local": float(np.abs(lum[20:120] - gaussian(lum[20:120], 12)).mean()),
        "fine": float(np.abs(lum[20:120] - gaussian(lum[20:120], 1.5)).mean()),
        "std": float(lum.std()),
    }


EXPECT = {
    "exposure": (1.0, lambda b, a: a["mean"] > b["mean"] + 0.05),
    "contrast": (60, lambda b, a: a["std"] > b["std"] * 1.03),
    "highlights": (-80, lambda b, a: a["bright"] < b["bright"] - 0.01),
    "shadows": (80, lambda b, a: a["dark"] > b["dark"] + 0.01),
    "whites": (80, lambda b, a: a["bright"] > b["bright"] + 0.005),
    "blacks": (-80, lambda b, a: a["dark"] < b["dark"] - 0.005),
    "temp": (60, lambda b, a: a["rb"] > b["rb"] * 1.1),
    "tint": (60, lambda b, a: a["green"] < b["green"] * 0.98),
    "vibrance": (80, lambda b, a: a["sat"] > b["sat"] + 0.02),
    "saturation": (-60, lambda b, a: a["sat"] < b["sat"] - 0.05),
    "clarity": (80, lambda b, a: a["local"] > b["local"] * 1.1),
    "texture": (80, lambda b, a: a["fine"] > b["fine"] * 1.1),
    "sharpen": (120, lambda b, a: a["fine"] > b["fine"] * 1.05),
}


def mac_tier() -> bool:
    import feedready

    return feedready.tier() == "mac"


@contextmanager
def basic_tier():
    import feedready

    saved_engine, saved_tier = detect.ENGINE, feedready.tier
    detect.ENGINE, feedready.tier = Path("/nonexistent"), (lambda: "basic")
    try:
        yield
    finally:
        detect.ENGINE, feedready.tier = saved_engine, saved_tier


def cli_stdout(cmd, *argv):
    res = subprocess.run([sys.executable, str(SCRIPTS / "feedready.py"), cmd, *argv],
                         capture_output=True, text=True,
                         env=dict(os.environ, FEEDREADY_WORK=str(tmp() / "work")))
    if res.returncode:
        raise RuntimeError(res.stderr or res.stdout)
    return json.loads(res.stdout)


def cli_error(cmd, *argv):
    res = subprocess.run([sys.executable, str(SCRIPTS / "feedready.py"), cmd, *argv],
                         capture_output=True, text=True)
    for stream in (res.stdout, res.stderr):
        try:
            parsed = json.loads(stream)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"stdout": res.stdout, "stderr": res.stderr}


def apply_cli(recipe, src, out):
    res = subprocess.run([sys.executable, str(SCRIPTS / "feedready.py"), "apply", json.dumps(recipe), str(src), "-o", str(out)],
                         capture_output=True, text=True,
                         env=dict(os.environ, FEEDREADY_WORK=str(tmp() / "work")))
    if res.returncode:
        raise RuntimeError(res.stderr or res.stdout)
    return load_rgb(out)


def apply_np(recipe, src, out):
    import feedready

    with basic_tier(), isolated_work():
        args = type("Args", (), {})()
        args.recipe, args.image, args.output = json.dumps(recipe), str(src), str(out)
        feedready.cmd_apply(args)
    return load_rgb(out)


def apply_recipe(renderer, recipe, src, out):
    return apply_cli(recipe, src, out) if renderer == "core-image" else apply_np(recipe, src, out)


def cli(renderer, cmd, **kw):
    if renderer == "core-image":
        argv = {"preview": lambda: [kw["recipe"], kw["image"], "--note", kw.get("note", "")],
                "board": lambda: [kw["image"], *kw["recipes"]],
                "apply": lambda: [kw["recipe"], kw["image"], "-o", kw["output"]]}[cmd]()
        return cli_stdout(cmd, *argv)
    import feedready

    with basic_tier(), isolated_work():
        args = type("Args", (), {})()
        args.__dict__.update({"note": "", **kw})
        return {"preview": feedready.cmd_preview, "board": feedready.cmd_board, "apply": feedready.cmd_apply}[cmd](args)


def work_dir_for(src: Path) -> Path:
    import hashlib

    h = hashlib.sha1()
    with open(src, "rb") as f:
        h.update(f.read(1 << 20))
    h.update(str(src.stat().st_size).encode())
    h.update(b"2")
    return tmp() / "work" / f"{src.stem}-{h.hexdigest()[:8]}"


def _srgb_to_xyz(img):
    lin = srgb_to_linear(img.astype(np.float64))
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    return lin @ m.T


def _xyz_to_lab(xyz):
    t = xyz / np.array([0.95047, 1.0, 1.08883])
    d = 6 / 29
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4 / 29)
    return np.stack([-16 + 116 * f[..., 1], 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def to_lab(img):
    return _xyz_to_lab(_srgb_to_xyz(img))


def de2000_lab(lab1, lab2):
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    ap1, ap2 = (1 + G) * a1, (1 + G) * a2
    Cp1, Cp2 = np.hypot(ap1, b1), np.hypot(ap2, b2)
    hp1 = np.degrees(np.arctan2(b1, ap1)) % 360
    hp2 = np.degrees(np.arctan2(b2, ap2)) % 360
    hp1, hp2 = np.where(Cp1 == 0, 0, hp1), np.where(Cp2 == 0, 0, hp2)
    dLp = L2 - L1
    dCp = Cp2 - Cp1
    dhp = hp2 - hp1
    dhp = np.where(dhp > 180, dhp - 360, np.where(dhp < -180, dhp + 360, dhp))
    dhp = np.where(Cp1 * Cp2 == 0, 0.0, dhp)
    dHp = 2 * np.sqrt(Cp1 * Cp2) * np.sin(np.radians(dhp) / 2)
    Lb, Cpb = (L1 + L2) / 2, (Cp1 + Cp2) / 2
    hs = hp1 + hp2
    hb = np.where(np.abs(hp1 - hp2) > 180, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2), hs / 2)
    hb = np.where(Cp1 * Cp2 == 0, hs, hb)
    T = (1 - 0.17 * np.cos(np.radians(hb - 30)) + 0.24 * np.cos(np.radians(2 * hb))
         + 0.32 * np.cos(np.radians(3 * hb + 6)) - 0.20 * np.cos(np.radians(4 * hb - 63)))
    dtheta = 30 * np.exp(-(((hb - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpb ** 7 / (Cpb ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    Sc = 1 + 0.045 * Cpb
    Sh = 1 + 0.015 * Cpb * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    dl, dc, dh = dLp / Sl, dCp / Sc, dHp / Sh
    return np.sqrt(dl * dl + dc * dc + dh * dh + Rt * dc * dh)


def delta_e2000(a, b):
    return de2000_lab(to_lab(a), to_lab(b))


def de2000_stats(a, b):
    d = delta_e2000(a, b)
    return {"mean": float(d.mean()), "p999": float(np.percentile(d, 99.9)), "max": float(d.max())}


def psnr(a, b):
    mse = float(((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean())
    return float(10 * np.log10(1 / max(mse, 1e-12)))


def pixel_gate(a, b, tol=2 / 255, frac=0.999):
    d = np.abs(a.astype(np.float64) - b.astype(np.float64)).max(-1)
    return float((d <= tol).mean()), float(d.max())


def _dct(n):
    k, x = np.arange(n)[:, None], np.arange(n)[None, :]
    t = np.cos(np.pi * (2 * x + 1) * k / (2 * n)) * np.sqrt(2 / n)
    t[0] /= np.sqrt(2)
    return t


_DCT32 = _dct(32)


def phash(img) -> int:
    g = imaging.resize(luma(img), 32, 32).astype(np.float64)
    d = _DCT32 @ g @ _DCT32.T
    block = d[1:9, 1:9]
    return int("".join("1" if v else "0" for v in (block > np.median(block)).flat), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def save_golden(name, img, meta):
    GOLDEN.mkdir(exist_ok=True)
    Image.fromarray(imaging.to_u8(img)).save(GOLDEN / f"{name}.png")
    index_path = GOLDEN / "goldens.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    index[name] = meta
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True))


def load_golden(name):
    return np.asarray(Image.open(GOLDEN / f"{name}.png"), dtype=np.float32) / 255.0


def corpus_photos(subdirs=("kodak", "commons")):
    out = []
    for sub in subdirs:
        d = CORPUS / sub
        if d.exists():
            out += sorted(p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg") and p.stem != "CREDITS")
    return out
