from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


def load_rgb(path) -> np.ndarray:
    if cv2 is not None and str(path).lower().endswith(".png") and _plain_png(path):
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is not None:
            scale = 65535.0 if raw.dtype == np.uint16 else 255.0
            if raw.ndim == 2:
                raw = np.stack([raw] * 3, -1)
            return (cv2.cvtColor(raw[..., :3], cv2.COLOR_BGR2RGB).astype(np.float32) / scale).clip(0, 1)
    im = ImageOps.exif_transpose(Image.open(path))
    icc = im.info.get("icc_profile")
    im = im.convert("RGB")
    if icc:
        try:
            from io import BytesIO

            from PIL import ImageCms

            src = ImageCms.ImageCmsProfile(BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except Exception:
            pass
    return np.asarray(im, dtype=np.float32) / 255.0


def _plain_png(path) -> bool:
    with Image.open(path) as im:
        if im.getexif().get(0x0112, 1) != 1:
            return False
        icc = im.info.get("icc_profile")
    if not icc:
        return True
    try:
        from io import BytesIO

        from PIL import ImageCms

        return "srgb" in ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(icc))).lower()
    except Exception:
        return False


def load_mask(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def save_png16(img: np.ndarray, path) -> None:
    data = (img.clip(0, 1) * 65535 + 0.5).astype(np.uint16)
    if cv2 is not None:
        cv2.imwrite(str(path), cv2.cvtColor(data, cv2.COLOR_RGB2BGR))
    else:
        Image.fromarray((img.clip(0, 1) * 255 + 0.5).astype(np.uint8)).save(path)


def save_mask(mask: np.ndarray, path) -> None:
    Image.fromarray((mask.clip(0, 1) * 255 + 0.5).astype(np.uint8), "L").save(path)


def save_jpeg(img: np.ndarray, path, quality: int = 100) -> None:
    Image.fromarray((img.clip(0, 1) * 255 + 0.5).astype(np.uint8)).save(path, quality=quality, subsampling=0)


def to_u8(img: np.ndarray) -> np.ndarray:
    return (img.clip(0, 1) * 255 + 0.5).astype(np.uint8)


def resize(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    if cv2 is not None:
        interp = cv2.INTER_AREA if w < arr.shape[1] else cv2.INTER_LINEAR
        return cv2.resize(arr, (w, h), interpolation=interp)
    mode = "F"
    if arr.ndim == 2:
        return np.asarray(Image.fromarray(arr, mode).resize((w, h), Image.BILINEAR))
    return np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(arr[..., c]), mode).resize((w, h), Image.BILINEAR)) for c in range(arr.shape[2])], -1)


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def rgb_to_hsv(img: np.ndarray):
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    mx, mn = img.max(-1), img.min(-1)
    d = mx - mn
    safe = np.where(d == 0, 1, d)
    h = np.select(
        [mx == r, mx == g],
        [((g - b) / safe) % 6, (b - r) / safe + 2],
        (r - g) / safe + 4,
    ) * 60.0
    h = np.where(d == 0, 0, h)
    s = np.where(mx == 0, 0, d / np.where(mx == 0, 1, mx))
    return h.astype(np.float32), s.astype(np.float32), mx.astype(np.float32)


def hsv_to_rgb(h, s, v) -> np.ndarray:
    h = (h % 360) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,), np.float32)
    for k, (a, b, c) in enumerate(choices):
        sel = i == k
        out[sel] = np.stack([a[sel], b[sel], c[sel]], -1)
    return out


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / np.maximum(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def box_blur(a: np.ndarray, r: int) -> np.ndarray:
    if r < 1:
        return a
    if cv2 is not None:
        return cv2.blur(a, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)

    def along(x, axis):
        n = x.shape[axis]
        c = np.cumsum(x, axis=axis, dtype=np.float64)
        c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
        idx = np.arange(n)
        hi = np.minimum(idx + r + 1, n)
        lo = np.maximum(idx - r, 0)
        out = (np.take(c, hi, axis=axis) - np.take(c, lo, axis=axis))
        shape = [1] * x.ndim
        shape[axis] = n
        return (out / (hi - lo).reshape(shape)).astype(np.float32)

    return along(along(a, 0), 1)


def gaussian(a: np.ndarray, sigma: float) -> np.ndarray:
    if sigma < 0.5:
        return a
    if cv2 is not None:
        return cv2.GaussianBlur(a, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    r = max(1, int(round(sigma * 0.9)))
    for _ in range(3):
        a = box_blur(a, r)
    return a


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    if cv2 is not None and hasattr(cv2, "ximgproc"):
        g = guide.astype(np.float32)
        return cv2.ximgproc.guidedFilter(g, src.astype(np.float32), r, eps)
    g = luma(guide) if guide.ndim == 3 else guide
    mean_g, mean_s = box_blur(g, r), box_blur(src, r)
    cov = box_blur(g * src, r) - mean_g * mean_s
    var = box_blur(g * g, r) - mean_g * mean_g
    a = cov / (var + eps)
    b = mean_s - a * mean_g
    return box_blur(a, r) * g + box_blur(b, r)


def min_filter(a: np.ndarray, r: int) -> np.ndarray:
    if cv2 is not None:
        return cv2.erode(a, np.ones((2 * r + 1, 2 * r + 1), np.uint8), borderType=cv2.BORDER_REFLECT)
    p = np.pad(a, r, mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(p, 2 * r + 1, axis=0).min(-1)
    return np.lib.stride_tricks.sliding_window_view(v, 2 * r + 1, axis=1).min(-1)
