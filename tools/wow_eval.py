from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache" / "feedready" / "wow-eval"
COMMONS = Path.home() / ".cache" / "feedready" / "corpus" / "commons"
EDGE = 1440


def _run_dir(run: str) -> Path:
    d = CACHE / run
    if not d.exists():
        raise SystemExit(f"no such run: {run} (expected {d})")
    return d


def cmd_new(args):
    d = CACHE / args.run
    if d.exists():
        raise SystemExit(f"run already exists: {d}")
    photos = sorted(p.name for p in COMMONS.glob("*.jpg")) if COMMONS.exists() else []
    if not photos:
        raise SystemExit(f"no corpus photos in {COMMONS}; run tests/selftest.py --fetch-corpus first")
    (d / "arms").mkdir(parents=True)
    (d / "recipes").mkdir()
    (d / "blind").mkdir()
    briefs = {name: "" for name in photos}
    (d / "briefs.json").write_text(json.dumps(briefs, indent=2) + "\n")
    (d / "key.json").write_text("{}\n")
    print(json.dumps({"run": str(d), "photos": len(photos)}, indent=2))
    print("next: fill briefs.json (destination + vibe per photo), freeze each arm, author recipes, then render")


def cmd_freeze(args):
    d = _run_dir(args.run)
    src = Path(args.src).resolve()
    if not (src / "SKILL.md").exists() and not (src / "skills" / "feedready" / "SKILL.md").exists():
        raise SystemExit(f"{src} is not a skill directory (no SKILL.md)")
    if (src / "SKILL.md").exists():
        skill = src
    else:
        skill = src / "skills" / "feedready"
    arm = d / "arms" / args.arm
    if arm.exists():
        shutil.rmtree(arm)
    arm.mkdir(parents=True)
    for item in ("SKILL.md", "reference", "scripts", "run.sh", "setup.sh"):
        s = skill / item
        if s.exists():
            (shutil.copytree if s.is_dir() else shutil.copy2)(s, arm / item)
    rev = ""
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=skill, capture_output=True,
                             text=True).stdout.strip()
    except OSError:
        pass
    manifest = {"arm": args.arm, "source": str(skill), "git": rev, "frozen": time.strftime("%Y-%m-%d %H:%M")}
    mf = d / "arms" / "manifest.json"
    index = json.loads(mf.read_text()) if mf.exists() else {}
    index[args.arm] = manifest
    mf.write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def _candidates(d: Path, arm: str, briefs: dict) -> list[tuple[str, str, Path]]:
    out = []
    for photo in briefs:
        for recipe in sorted((d / "recipes" / arm).glob(f"{Path(photo).stem}*.json")):
            out.append((arm, photo, recipe))
    return out


def cmd_render(args):
    d = _run_dir(args.run)
    briefs = json.loads((d / "briefs.json").read_text())
    missing = [p for p, b in briefs.items() if not b.strip()]
    if missing:
        raise SystemExit(f"briefs.json still has empty briefs: {missing}")
    arms = sorted(p.name for p in (d / "arms").iterdir() if p.is_dir())
    if len(arms) < 2:
        raise SystemExit("freeze at least two arms before rendering")
    todo = []
    for arm in arms:
        cands = _candidates(d, arm, briefs)
        per_photo = {photo for _, photo, _ in cands}
        gap = sorted(set(briefs) - per_photo)
        if gap:
            raise SystemExit(f"arm '{arm}' has no recipe for: {gap}")
        todo += cands
    for f in (d / "blind").glob("*.jpg"):
        f.unlink()
    key = {}
    for arm, photo, recipe in todo:
        cid = hashlib.sha1(f"{arm}/{photo}/{recipe.name}".encode()).hexdigest()[:12]
        key[cid] = {"arm": arm, "photo": photo, "recipe": recipe.name}
        out = d / "blind" / f"{cid}.jpg"
        res = subprocess.run([sys.executable, __file__, "render-one",
                              str(d / "arms" / arm / "scripts"), str(COMMONS / photo), str(recipe), str(out),
                              "--scratch", str(d / "scratch" / f"{cid}.jpg")],
                             capture_output=True, text=True)
        if res.returncode:
            raise SystemExit(f"render failed for {arm}/{photo}/{recipe.name}:\n{res.stderr or res.stdout}")
    (d / "key.json").write_text(json.dumps(key, indent=2, sort_keys=True) + "\n")
    order = list(key)
    random.Random(len(key)).shuffle(order)
    (d / "blind" / "view-order.txt").write_text("\n".join(f"{i}. blind/{cid}.jpg" for i, cid in enumerate(order, 1)) + "\n")
    scaffold = {"photos": []}
    by_photo = {}
    for cid, meta in key.items():
        by_photo.setdefault(meta["photo"], []).append(cid)
    for photo in sorted(by_photo):
        scaffold["photos"].append({"photo": photo,
                                   "candidates": [{"id": cid, "wow": False, "damage": False, "note": ""}
                                                   for cid in sorted(by_photo[photo])],
                                   "choice": ""})
    (d / "ratings.json").write_text(json.dumps(scaffold, indent=2) + "\n")
    print(json.dumps({"blind": str(d / "blind"), "candidates": len(key),
                      "next": "rate blind/view-order.txt by eye, fill ratings.json, then report"}, indent=2))


def cmd_render_one(args):
    sys.path.insert(0, str(Path(args.arm).resolve()))
    import feedready as fr
    import masks as maskmod
    import render as r
    from detect import Scene

    scratch = Path(args.scratch)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.photo, scratch)
    work, working, img = fr.prepare(scratch)
    scene = Scene(work, working, img)
    recipe = json.loads(Path(args.recipe).read_text())
    steps, _ = r.resolve(recipe)
    built = [maskmod.build(step.get("mask"), scene) for step in steps]
    icc = fr.wide_profile(working)
    small, small_masks = r.downscale(img, built, EDGE)
    source = None
    if fr.tier() == "mac":
        stage = work / "stage"
        stage.mkdir(exist_ok=True)
        source = stage / f"base-{small.shape[1]}x{small.shape[0]}.png"
        if not source.exists():
            fr.save_png16(small, source, icc)
    r.render(small, steps, small_masks, recipe, Path(args.out), stage=work / "stage", tag="wow",
             engine=fr.tier() == "mac", icc=icc, source=source)
    shutil.rmtree(work, ignore_errors=True)


def cmd_report(args):
    d = _run_dir(args.run)
    key = json.loads((d / "key.json").read_text())
    ratings = json.loads((d / "ratings.json").read_text())
    per_arm = {}
    picks = {}
    unrated = 0
    for entry in ratings["photos"]:
        chosen = entry.get("choice", "")
        if not chosen:
            unrated += 1
        elif chosen not in key:
            raise SystemExit(f"choice '{chosen}' is not a blind id (photo {entry['photo']})")
        else:
            picks[key[chosen]["arm"]] = picks.get(key[chosen]["arm"], 0) + 1
        for cand in entry["candidates"]:
            meta = key.get(cand["id"])
            if not meta:
                raise SystemExit(f"unknown candidate id {cand['id']}")
            arm = per_arm.setdefault(meta["arm"], {"candidates": 0, "wow": 0, "damage": 0})
            arm["candidates"] += 1
            arm["wow"] += bool(cand.get("wow"))
            arm["damage"] += bool(cand.get("damage"))
    for arm, stat in sorted(per_arm.items()):
        n = stat["candidates"]
        print(f"{arm:12s} candidates {n:3d}  wow {stat['wow'] / n:5.1%}  picks {picks.get(arm, 0):2d}  damage {stat['damage']}")
    if unrated:
        print(f"unrated photos: {unrated} (skipped from picks)")
    if args.baseline not in per_arm or args.candidate not in per_arm:
        raise SystemExit(f"need arms '{args.baseline}' and '{args.candidate}' in the ratings")
    b, c = per_arm[args.baseline], per_arm[args.candidate]
    nb, nc = b["candidates"], c["candidates"]
    gate = {
        "pick rate not lost": (picks.get(args.candidate, 0) / nc) >= (picks.get(args.baseline, 0) / nb),
        "wow rate up": (c["wow"] / nc) > (b["wow"] / nb),
        "no damage": c["damage"] == 0,
    }
    verdict = "GATE PASSED" if all(gate.values()) else "GATE FAILED"
    print(json.dumps(gate, indent=2))
    print(verdict)
    sys.exit(0 if all(gate.values()) else 1)


def main():
    ap = argparse.ArgumentParser(description="feedready wow eval: blind A/B gate for the suggestion pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="scaffold a run over the commons corpus")
    p.add_argument("run")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("freeze", help="snapshot a skill directory as an arm")
    p.add_argument("run")
    p.add_argument("arm")
    p.add_argument("src")
    p.set_defaults(fn=cmd_freeze)
    p = sub.add_parser("render", help="render every arm's recipes into blind candidate jpgs")
    p.add_argument("run")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("render-one", help=argparse.SUPPRESS)
    p.add_argument("arm")
    p.add_argument("photo")
    p.add_argument("recipe")
    p.add_argument("out")
    p.add_argument("--scratch", default="~/.cache/feedready/wow-eval/scratch/unique.jpg")
    p.set_defaults(fn=cmd_render_one)
    p = sub.add_parser("report", help="score ratings.json per arm and apply the gate")
    p.add_argument("run")
    p.add_argument("--baseline", default="baseline")
    p.add_argument("--candidate", default="candidate")
    p.set_defaults(fn=cmd_report)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
