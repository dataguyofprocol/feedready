from __future__ import annotations

import json
from pathlib import Path

import lib

LABELS = json.loads((Path(__file__).resolve().parent / "labels.json").read_text())
KODAK = LABELS["kodak"]


def inspect(photo: Path) -> dict:
    import feedready

    args = type("Args", (), {"image": str(photo)})()
    return feedready.cmd_inspect(args)


def check_photo(rel: str, label: dict, report: dict):
    findings = report["diagnostics"]["findings"]
    found = {f["check"] for f in findings}
    by_check = {f["check"]: f for f in findings}
    lib.check(f"suggest {rel} genre", report["profile"]["genre"] == label["genre"],
              f"{report['profile']['genre']} (want {label['genre']})")
    if "faces" in label:
        n = report["profile"]["signals"]["faces"]
        lib.check(f"suggest {rel} face count", n == label["faces"], f"{n} (want {label['faces']})")
    missing = set(label.get("requires", [])) - found
    forbidden = set(label.get("forbids", [])) & found
    lib.check(f"suggest {rel} findings", not missing and not forbidden,
              f"missing {sorted(missing)} forbidden {sorted(forbidden)}")
    for check_name, signs in label.get("signs", {}).items():
        f = by_check.get(check_name)
        adj = (f.get("step") or {}).get("adjust", {}) if f else {}
        bad = [k for k, want in signs.items() if not adj.get(k, 0) * want > 0]
        lib.check(f"suggest {rel} {check_name} direction", f is not None and not bad, json.dumps(adj))
    for text in label.get("forbid_findings", []):
        lib.check(f"suggest {rel} never reports '{text}'",
                  text not in json.dumps([f["finding"] for f in findings]))
    opp_label = label.get("opportunities")
    if opp_label:
        found_opp = {o["check"] for o in report.get("opportunities", [])}
        missing_opp = set(opp_label.get("requires", [])) - found_opp
        lib.check(f"suggest {rel} opportunities", not missing_opp, f"missing {sorted(missing_opp)}")
        if "light" in opp_label:
            got = report["profile"].get("light", {}).get("quality")
            lib.check(f"suggest {rel} light quality", got == opp_label["light"],
                      f"{got} (want {opp_label['light']})")
        if "pair" in opp_label:
            got = next((o["evidence"].get("names") for o in report.get("opportunities", [])
                        if o["check"] == "colour_pairs"), None)
            lib.check(f"suggest {rel} colour pair", got == opp_label["pair"],
                      f"{got} (want {opp_label['pair']})")
    rec_label = label.get("recrops")
    if rec_label:
        got = report.get("recrops", [])
        lib.check(f"suggest {rel} recrop count", len(got) >= rec_label.get("min", 1), f"{len(got)}")
        if "any_aspects" in rec_label:
            aspects = {r["aspect"] for r in got}
            lib.check(f"suggest {rel} recrop aspects", set(rec_label["any_aspects"]) & aspects,
                      f"{sorted(aspects)} (want any of {rec_label['any_aspects']})")
        if "face_share" in rec_label:
            lo, hi = rec_label["face_share"]
            ok = any(lo <= r["evidence"].get("face_height_share", 0) <= hi for r in got)
            lib.check(f"suggest {rel} recrop face share", ok)


def kodak_gates():
    for photo in lib.corpus_photos(("kodak",)):
        report = inspect(photo)
        findings = report["diagnostics"]["findings"]
        texts = json.dumps([f["finding"] for f in findings])
        cast = next((f for f in findings if f["check"] == "color_cast"), None)
        adj = (cast.get("step") or {}).get("adjust", {}) if cast else {}
        band = KODAK["cast_band"]
        over = [k for k in band if abs(adj.get(k, 0)) > band[k]]
        genre = report["profile"]["genre"]
        want = KODAK["genres"].get(photo.name)
        lib.check(f"suggest {photo.name} stays a clean reference",
                  "underexposed overall" not in texts and not over and genre == want,
                  f"genre {genre} (want {want}), cast {json.dumps(adj)}")


def private_consistency():
    for photo in lib.corpus_photos(("private",)):
        report = inspect(photo)
        findings = report["diagnostics"]["findings"]
        texts = json.dumps([f["finding"] for f in findings])
        touched = set()
        for recipe_path in sorted(photo.parent.glob(f"{photo.stem}.v*.json")):
            for step in json.loads(recipe_path.read_text()).get("steps", []):
                touched |= set(step.get("adjust", {}))
        if ("underexposed overall" in texts or "clipped to white" in texts) and not touched & {"exposure", "highlights"}:
            print(f"    warn: {photo.name} is underexposed or clipped but no saved version lifts exposure/highlights")


def run():
    if not lib.corpus_photos():
        lib.skip("suggest (run tests/selftest.py --fetch-corpus to download the corpus)")
        return
    if not lib.mac_tier():
        lib.skip("suggest (the diagnosis pipeline needs the Mac tier's Vision and SegFormer)")
        return
    for rel, label in LABELS.items():
        if rel == "kodak":
            continue
        photo = lib.CORPUS / rel
        if not photo.exists():
            lib.check(f"suggest {rel} is in the corpus", False, f"{photo} missing")
            continue
        check_photo(rel, label, inspect(photo))
    kodak_gates()
    private_consistency()
