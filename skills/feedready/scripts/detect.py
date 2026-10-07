from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np

from imaging import guided_filter, load_mask, min_filter, resize

CACHE = Path.home() / ".cache" / "feedready"
ENGINE = CACHE / "bin" / "feedready-engine"
ENGINE_SOURCE = Path(__file__).resolve().parents[1] / "swift" / "feedready_engine.swift"
SEGFORMER = CACHE / "models" / "segformer_b0_ade_q.onnx"
SEGFORMER_LABELS = CACHE / "models" / "segformer_config.json"
SEGFORMER_URL = "https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512/resolve/main"
EDGETAM_ENCODER = CACHE / "models" / "edgetam" / "vision_encoder.onnx"
EDGETAM_DECODER = CACHE / "models" / "edgetam" / "prompt_encoder_mask_decoder.onnx"
MIGAN = CACHE / "models" / "migan_pipeline_v2.onnx"
LOW_IOU = 0.7

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
}


class MissingCapability(RuntimeError):
    pass


def engine_available() -> bool:
    return ENGINE.exists()


def engine_stale() -> bool:
    stamp = ENGINE.with_name(ENGINE.name + ".sha256")
    if not engine_available() or not ENGINE_SOURCE.exists():
        return False
    built = stamp.read_text().strip() if stamp.exists() else ""
    return built != hashlib.sha256(ENGINE_SOURCE.read_bytes()).hexdigest()


def run_engine(*args: str) -> str:
    if not engine_available():
        raise MissingCapability("needs Apple Vision (Mac tier only; on a Mac run setup.sh)")
    res = subprocess.run([str(ENGINE), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"feedready-engine {args[0]} failed: {res.stderr.strip()}")
    return res.stdout


class Scene:
    def __init__(self, work: Path, working_png: Path, img: np.ndarray):
        self.work = work
        self.working_png = working_png
        self.img = img
        self._vision = None
        self._seg = None
        self._edgetam = None
        self.notes: list[str] = []

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

    def segmentation(self):
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

    def object_mask(self, box=None, points=(), exclude=()) -> tuple[np.ndarray, float]:
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
        r = max(1, min(max(3, int(max(h, w) * 0.006)), int(_width(m > 0.5) / 3)))
        m = guided_filter(self.img, m.astype(np.float32), r, 1e-4).clip(0, 1)
        if score < LOW_IOU:
            prompt = f"box {list(box)}" if box is not None else f"points {[list(p) for p in points]}"
            note = f"object mask for {prompt} is low-confidence (iou {score:.2f}): check it on the contact sheet"
            if note not in self.notes:
                self.notes.append(note)
        return m.astype(np.float32), score

    def _edgetam_embeddings(self):
        if self._edgetam is None:
            if not edgetam_available():
                raise MissingCapability("object masks need onnxruntime + EdgeTAM (41 MB): run `setup.sh --models`")
            import onnxruntime as ort

            providers = ["CPUExecutionProvider"]
            encoder = ort.InferenceSession(str(EDGETAM_ENCODER), providers=providers)
            decoder = ort.InferenceSession(str(EDGETAM_DECODER), providers=providers)
            x = resize(self.img, 1024, 1024)
            x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
            outs = encoder.run(None, {"pixel_values": x.transpose(2, 0, 1)[None].astype(np.float32)})
            names = [o.name for o in encoder.get_outputs()]
            self._edgetam = (decoder, dict(zip(names, outs)))
        return self._edgetam


def _width(shape: np.ndarray) -> float:
    boundary = shape & (min_filter(shape.astype(np.float32), 1) < 0.5)
    return 2 * float(shape.sum()) / max(1, int(boundary.sum()))


def _onnxruntime() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


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
            "scene masks (sky/mountain/water...) need onnxruntime + SegFormer-B0 (4.4 MB): run `setup.sh --segformer`"
        )
    import onnxruntime as ort

    labels_map = json.loads(SEGFORMER_LABELS.read_text())["id2label"]
    labels = [labels_map[str(i)] for i in range(len(labels_map))]
    x = resize(img, 512, 512)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    session = ort.InferenceSession(str(SEGFORMER), providers=["CPUExecutionProvider"])
    logits = session.run(None, {"pixel_values": x})[0][0]
    e = np.exp(logits - logits.max(0))
    return (e / e.sum(0)).astype(np.float32), labels
