"""Scene understanding: Apple Vision (via feedready-engine), SegFormer ADE20K and
EdgeTAM promptable object masks.

Results are cached in the per-image work directory, so `inspect`, `masks` and
`apply` pay for detection once.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from imaging import guided_filter, load_mask, resize

CACHE = Path.home() / ".cache" / "feedready"
ENGINE = CACHE / "bin" / "feedready-engine"
SEGFORMER = CACHE / "models" / "segformer_b0_ade_q.onnx"
SEGFORMER_LABELS = CACHE / "models" / "segformer_config.json"
SEGFORMER_URL = "https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512/resolve/main"
EDGETAM_ENCODER = CACHE / "models" / "edgetam" / "vision_encoder.onnx"
EDGETAM_DECODER = CACHE / "models" / "edgetam" / "prompt_encoder_mask_decoder.onnx"
MIGAN = CACHE / "models" / "migan_pipeline_v2.onnx"
LOW_IOU = 0.7

# Friendly names Claude may use -> ADE20K labels (summed).
SEG_ALIASES = {
    "sky": ["sky"],
    "mountain": ["mountain", "hill"],
    "mountains": ["mountain", "hill"],
    "tree": ["tree", "palm"],
    "trees": ["tree", "palm"],
    "vegetation": ["tree", "grass", "plant", "palm", "flower", "field"],
    "water": ["water", "sea", "river", "lake", "waterfall"],
    "ground": ["earth", "ground", "field", "sand", "road", "path", "dirt track", "floor", "grass"],
    "building": ["building", "house", "skyscraper", "tower"],
    "rock": ["rock"],
    "snow": ["snow"],
}


class MissingCapability(RuntimeError):
    """A mask needs a component this machine/tier lacks (model, engine, OpenCV)."""


def engine_available() -> bool:
    return ENGINE.exists()


def run_engine(*args: str) -> str:
    if not engine_available():
        raise MissingCapability("needs Apple Vision (Mac tier only; on a Mac run setup.sh)")
    res = subprocess.run([str(ENGINE), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"feedready-engine {args[0]} failed: {res.stderr.strip()}")
    return res.stdout


class Scene:
    """Lazy, cached detections for one working image."""

    def __init__(self, work: Path, working_png: Path, img: np.ndarray):
        self.work = work
        self.working_png = working_png
        self.img = img
        self._vision = None
        self._seg = None
        self._edgetam = None
        self.notes: list[str] = []

    # --- Vision ---
    def vision(self) -> dict:
        if self._vision is None:
            out = self.work / "vision"
            if not (out / "vision.json").exists():
                out.mkdir(exist_ok=True)
                run_engine("vision", str(self.working_png), str(out))
            self._vision = json.loads((out / "vision.json").read_text())
        return self._vision

    def vision_mask(self, name: str) -> np.ndarray:
        self.vision()
        path = self.work / "vision" / f"{name}.png"
        if not path.exists():
            raise MissingCapability(f"Vision found no {name} in this photo")
        m = load_mask(path)
        h, w = self.img.shape[:2]
        return m if m.shape == (h, w) else resize(m, w, h)

    def faces(self) -> list[dict]:
        return self.vision().get("faces", [])

    # --- SegFormer ---
    def segmentation(self):
        """(probabilities CxHxW at <=1024px, labels list)."""
        if self._seg is None:
            cache = self.work / "segformer.npz"
            if cache.exists():
                z = np.load(cache, allow_pickle=True)
                self._seg = (z["probs"].astype(np.float32), list(z["labels"]))
            else:
                self._seg = _run_segformer(self.img)
                np.savez_compressed(cache, probs=self._seg[0].astype(np.float16), labels=np.array(self._seg[1]))
        return self._seg

    def segment_mask(self, cls: str, refine: bool = True) -> np.ndarray:
        probs, labels = self.segmentation()
        names = SEG_ALIASES.get(cls.lower(), [cls.lower()])
        idx = [i for i, label in enumerate(labels) if label.split(",")[0].strip() in names or label in names]
        if not idx:
            raise ValueError(f"unknown scene class '{cls}'. Try one of: {', '.join(sorted(SEG_ALIASES))}")
        m = probs[idx].sum(0).clip(0, 1)
        h, w = self.img.shape[:2]
        m = resize(m, w, h)
        if refine:
            # Snap the coarse 128px logits to real edges in the photo.
            m = guided_filter(self.img, m, max(4, int(max(h, w) * 0.008)), 1e-4).clip(0, 1)
        return m

    def segment_summary(self, min_share: float = 0.01) -> list[dict]:
        probs, labels = self.segmentation()
        lab = probs.argmax(0)
        total = lab.size
        out = []
        for i in np.unique(lab):
            share = float((lab == i).sum()) / total
            if share < min_share:
                continue
            ys, xs = np.nonzero(lab == i)
            H, W = lab.shape
            out.append({
                "class": labels[i].split(",")[0].strip(),
                "share": round(share, 3),
                "box": [round(xs.min() / W, 3), round(ys.min() / H, 3), round(xs.max() / W, 3), round(ys.max() / H, 3)],
            })
        return sorted(out, key=lambda d: -d["share"])

    # --- EdgeTAM ---
    def object_mask(self, box=None, points=(), exclude=()) -> tuple[np.ndarray, float]:
        """Mask of the object a box and/or clicks point at (normalized coords); also its iou score."""
        if box is None and not points:
            raise ValueError("object mask needs a box or at least one point")
        decoder, embeddings = self._edgetam_embeddings()
        clicks = [*points, *exclude]
        feeds = {
            "input_points": np.array(clicks, np.float32).reshape(1, 1, -1, 2) * 1024,
            "input_labels": np.array([1] * len(points) + [0] * len(exclude), np.int64).reshape(1, 1, -1),
            "input_boxes": np.array([] if box is None else box, np.float32).reshape(1, -1, 4) * 1024,
            **embeddings,
        }
        iou, logits = decoder.run(["iou_scores", "pred_masks"], feeds)
        best = int(iou[0, 0].argmax())
        score = float(iou[0, 0, best])
        h, w = self.img.shape[:2]
        logit = resize(np.ascontiguousarray(logits[0, 0, best]), w, h)
        m = 1 / (1 + np.exp(-np.clip(logit, -30, 30)))
        m = guided_filter(self.img, m.astype(np.float32), max(3, int(max(h, w) * 0.006)), 1e-4).clip(0, 1)
        if score < LOW_IOU:
            prompt = f"box {list(box)}" if box is not None else f"points {[list(p) for p in points]}"
            self.notes.append(f"object mask for {prompt} is low-confidence (iou {score:.2f}): check it on the contact sheet")
        return m.astype(np.float32), score

    def _edgetam_embeddings(self):
        if self._edgetam is None:
            if not edgetam_available():
                raise MissingCapability("object masks need onnxruntime + EdgeTAM (41 MB): run `setup.sh --models`")
            import onnxruntime as ort

            providers = ["CPUExecutionProvider"]  # CoreML splits the decoder and crashes on empty point tensors
            encoder = ort.InferenceSession(str(EDGETAM_ENCODER), providers=providers)
            decoder = ort.InferenceSession(str(EDGETAM_DECODER), providers=providers)
            # Stretched to 1024x1024, not padded, so the 256px mask maps straight back onto the frame.
            x = resize(self.img, 1024, 1024)
            x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
            outs = encoder.run(None, {"pixel_values": x.transpose(2, 0, 1)[None].astype(np.float32)})
            names = [o.name for o in encoder.get_outputs()]
            self._edgetam = (decoder, dict(zip(names, outs)))
        return self._edgetam


def _onnxruntime() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def segformer_available() -> bool:
    return _onnxruntime() and SEGFORMER.exists() and SEGFORMER_LABELS.exists()


def edgetam_available() -> bool:
    files = [f for m in (EDGETAM_ENCODER, EDGETAM_DECODER) for f in (m, m.with_name(m.name + "_data"))]
    return _onnxruntime() and all(f.exists() for f in files)


def migan_available() -> bool:
    return _onnxruntime() and MIGAN.exists()


def _run_segformer(img: np.ndarray):
    if not segformer_available():
        raise MissingCapability(
            "scene masks (sky/mountain/water...) need onnxruntime + SegFormer-B0 (4.4 MB): run `feedready.py setup --segformer`"
        )
    import onnxruntime as ort

    labels_map = json.loads(SEGFORMER_LABELS.read_text())["id2label"]
    labels = [labels_map[str(i)] for i in range(len(labels_map))]
    x = resize(img, 512, 512)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    session = ort.InferenceSession(str(SEGFORMER), providers=["CPUExecutionProvider"])
    logits = session.run(None, {"pixel_values": x})[0][0]
    h, w = img.shape[:2]
    scale = min(1.0, 1024 / max(h, w))
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    logits = np.stack([resize(np.ascontiguousarray(c), tw, th) for c in logits])
    e = np.exp(logits - logits.max(0))
    return (e / e.sum(0)).astype(np.float32), labels
