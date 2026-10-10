from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np

import lib
import critique
import feedready
import imaging
import render

SRC_EDGE = 1400
RECIPES = {
    "clean-natural": {"preset": "instagram", "steps": [{"name": "natural", "look": "natural"}], "vignette": -10},
    "moody-depth": {"steps": [{"name": "moody", "look": "moody", "amount": 80},
                              {"name": "open shadows", "adjust": {"shadows": 25, "clarity": 10}}]},
}
FINGERPRINTS = lib.EVAL / "fingerprints.json"
HISTORY = lib.EVAL / "history.jsonl"


def small_src(photo: Path) -> Path:
    src_dir = lib.EVAL / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    dest = src_dir / f"{photo.stem}.png"
    if not dest.exists():
        img = imaging.load_rgb(photo)
        scale = SRC_EDGE / max(img.shape[:2])
        if scale < 1:
            img = imaging.resize(img, round(img.shape[1] * scale), round(img.shape[0] * scale))
        imaging.save_png16(img, dest)
    return dest


def scorecard(photo: Path, recipe_name: str, recipe: dict) -> dict:
    src = small_src(photo)
    out = lib.tmp() / f"eval-{photo.stem}-{recipe_name}.jpg"
    after = lib.apply_np(recipe, src, out)
    before = imaging.load_rgb(src)
    crop, _ = render.output_geometry(recipe, before.shape[1], before.shape[0])
    before = render.frame(before, crop)
    impacts = [critique.impact(before, after, None) for _ in recipe["steps"]]
    verdict = critique.run(before, after, [], None, recipe.get("vignette", 0), recipe["steps"], impacts)
    return {
        "stats": feedready.stats(after),
        "verdict": verdict["verdict"],
        "issues": len(verdict["issues"]),
        "fix_issues": sum(1 for i in verdict["issues"] if i["severity"] == "fix"),
        "levels": [i["level"] for i in impacts],
        "phash": lib.phash(after),
        "mean_de": round(lib.de2000_stats(before, after)["mean"], 3),
    }


def git_commit():
    try:
        return subprocess.run(["git", "-C", str(lib.ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def trend(current: dict):
    if not HISTORY.exists():
        return
    last = None
    for line in HISTORY.read_text().splitlines():
        if line.strip():
            last = json.loads(line)
    if not last:
        return
    drift = []
    for key, entry in current.items():
        prev = last.get("worst", {}).get(key)
        if prev is not None and abs(entry["stats"]["mean_luma"] - prev) > 0.005:
            drift.append(f"{key}: mean_luma {prev} -> {entry['stats']['mean_luma']}")
    if drift:
        print("  trend since last run (warnings only):")
        for d in drift:
            print(f"    {d}")


def run():
    if imaging.cv2 is None:
        lib.skip("eval (fingerprints recorded with the cv2 branches; install opencv to compare)")
        return
    photos = lib.corpus_photos() + lib.corpus_photos(("private",))
    if not photos:
        lib.skip("eval (run tests/selftest.py --fetch-corpus to download the corpus)")
        return
    fingerprints = json.loads(FINGERPRINTS.read_text()) if FINGERPRINTS.exists() else {}
    current = {}
    for photo in photos:
        for recipe_name, recipe in RECIPES.items():
            key = f"{photo.parent.name}/{photo.stem}|{recipe_name}"
            card = scorecard(photo, recipe_name, recipe)
            current[key] = card
            if lib.REGEN:
                fingerprints[key] = {"stats": card["stats"], "verdict": card["verdict"], "levels": card["levels"],
                                     "phash": card["phash"], "mean_de": card["mean_de"]}
                continue
            want = fingerprints.get(key)
            if want is None:
                lib.check(f"eval fingerprint {key} exists", False, "run with --regen to record")
                continue
            lumas = abs(card["stats"]["mean_luma"] - want["stats"]["mean_luma"])
            p01 = abs(card["stats"]["p01_p99_luma"][0] - want["stats"]["p01_p99_luma"][0])
            p99 = abs(card["stats"]["p01_p99_luma"][1] - want["stats"]["p01_p99_luma"][1])
            ham = lib.hamming(card["phash"], want["phash"])
            de = abs(card["mean_de"] - want["mean_de"])
            lib.check(f"eval {key}",
                      card["verdict"] == want["verdict"] and card["levels"] == want["levels"]
                      and lumas <= 0.005 and p01 <= 0.01 and p99 <= 0.01 and ham <= 4 and de <= 0.5,
                      f"verdict {card['verdict']}=={want['verdict']}, levels {card['levels']}, "
                      f"luma +{lumas:.4f}, phash {ham}/64, dE {card['mean_de']}")
    if lib.REGEN:
        lib.EVAL.mkdir(parents=True, exist_ok=True)
        FINGERPRINTS.write_text(json.dumps(fingerprints, indent=1, sort_keys=True))
        print(f"  regen {len(current)} fingerprints")
    lib.EVAL.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": git_commit(), "n": len(current),
                            "worst": {k: v["stats"]["mean_luma"] for k, v in current.items()},
                            "verdicts": {k: v["verdict"] for k, v in current.items()}}) + "\n")
    trend(current)
