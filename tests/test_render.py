from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, JpegImagePlugin

import lib
import critique
import masks
from detect import Scene, edgetam_available, migan_available
from imaging import cv2, gaussian, icc_profile, is_p3, load_rgb, save_png16, srgb_to_linear


def renderers():
    from detect import engine_available

    return (["core-image"] if engine_available() else []) + ["numpy"]


def per_renderer(renderer, tmp, base, src):
    identity = lib.apply_recipe(renderer, {"steps": []}, src, tmp / f"id_{renderer}.png")
    err = float(np.abs(identity - base).max())
    lib.check("identity", err <= 1.5 / 255, f"max err {err * 255:.2f}/255")

    jpg = tmp / f"insta_{renderer}.jpg"
    full = lib.apply_recipe(renderer, {"preset": "instagram", "steps": []}, src, jpg)
    lib.check("preset crops at full resolution", full.shape[:2] == (400, 320), str(full.shape[:2]))
    sampling = JpegImagePlugin.get_sampling(Image.open(jpg))
    lib.check("jpeg keeps full colour resolution (4:4:4)", sampling == 0, f"sampling {sampling}")
    small = lib.apply_recipe(renderer, {"preset": "instagram", "max_edge": 200, "steps": []}, src,
                             tmp / f"small_{renderer}.png")
    lib.check("max_edge shrinks the long edge", small.shape[:2] == (200, 160), str(small.shape[:2]))
    big = lib.apply_recipe(renderer, {"max_edge": 5000, "steps": []}, src, tmp / f"big_{renderer}.png")
    lib.check("max_edge never enlarges", big.shape[:2] == (400, 600), str(big.shape[:2]))
    lib.check("srgb photo exports untagged as p3", not is_p3(icc_profile(jpg)))
    p3_roundtrip(renderer, tmp, base)

    before = lib.metrics(base)
    for slider, (value, ok) in lib.EXPECT.items():
        out = lib.apply_recipe(renderer, {"steps": [{"adjust": {slider: value}}]}, src,
                               tmp / f"{slider}_{renderer}.png")
        lib.check(f"{slider}={value}", ok(before, lib.metrics(out)))

    hazy = lib.hazy_card()
    save_png16(hazy, tmp / "hazy.png")
    out = lib.apply_recipe(renderer, {"steps": [{"adjust": {"dehaze": 60}}]}, tmp / "hazy.png",
                           tmp / f"dehaze_{renderer}.png")
    hb, ha = lib.metrics(hazy), lib.metrics(out)
    lib.check("dehaze=60 on hazy card", ha["std"] > hb["std"] * 1.15 and ha["mean"] > hb["mean"] - 0.2,
              f"std {hb['std']:.3f}->{ha['std']:.3f} mean {hb['mean']:.3f}->{ha['mean']:.3f}")

    out = lib.apply_recipe(renderer, {"steps": [{"adjust": {"hsl": {"blue": {"sat": -100}}}}]}, src,
                           tmp / f"hsl_{renderer}.png")
    a = lib.metrics(out)
    lib.check("hsl blue sat -100", a["blue_sat"] < before["blue_sat"] * 0.4 and abs(a["sat"] - before["sat"]) < 0.2)

    out = lib.apply_recipe(renderer, {"steps": [{"adjust": {"exposure": 1}, "mask": {"type": "radial",
                           "center": [-0.5, -0.5], "radius": 0.1}}]}, src, tmp / f"zero_{renderer}.png")
    lib.check("empty mask changes nothing", float(np.abs(out - base).max()) <= 1.5 / 255)

    out = lib.apply_recipe(renderer, {"steps": [{"look": "mono"}]}, src, tmp / f"mono_{renderer}.png")
    lib.check("mono look renders black and white", lib.metrics(out)["sat"] < 0.05,
              f"sat {lib.metrics(out)['sat']:.3f}")
    cli_loop(renderer, tmp, src)

    gray = np.full((64, 64, 3), 0.3, np.float32)
    save_png16(gray, tmp / "gray.png")
    out = lib.apply_recipe(renderer, {"steps": [{"adjust": {"exposure": 1}}]}, tmp / "gray.png",
                           tmp / f"gray_{renderer}.png")
    ratio = float(srgb_to_linear(out).mean() / srgb_to_linear(gray).mean())
    lib.check("exposure +1 doubles linear light", abs(ratio - 2) < 0.03, f"ratio {ratio:.3f}")


def p3_roundtrip(renderer, tmp, base):
    if not lib.P3_ICC.exists():
        lib.skip("display p3 (no system profile)")
        return
    img = base.copy()
    img[150:230, 20:200] = (1.0, 0.0, 0.0)
    img[150:230, 220:400] = (0.0, 1.0, 0.0)
    src = tmp / "p3.png"
    save_png16(img, src, lib.P3_ICC.read_bytes())
    out = tmp / f"p3_{renderer}.jpg"
    res = lib.apply_recipe(renderer, {"preset": "original", "steps": []}, src, out)
    lib.check("p3 photo exports tagged display p3", is_p3(icc_profile(out)))
    err = max(float(np.abs(res[190, 100] - (1, 0, 0)).max()), float(np.abs(res[190, 300] - (0, 1, 0)).max()))
    lib.check("p3 red and green survive outside srgb", err <= 4 / 255, f"max err {err * 255:.1f}/255")


def cli_loop(renderer, tmp, src):
    first = {"steps": [{"name": "warm grade", "look": "warm-golden", "amount": 80},
                       {"name": "nothing", "adjust": {"temp": 1}}]}
    r1 = lib.cli(renderer, "preview", recipe=json.dumps(first), image=str(src), note="first")
    n = int(r1["version"][1:])
    files = [r1[k] for k in ("preview", "compare", "map", "cards", "review")]
    lib.check("preview writes the version, compare, map, cards and review page", all(Path(f).exists() for f in files))
    levels = [i["level"] for i in r1["impact"]]
    lib.check("impact sees the look and rates the no-op as none", levels[0] != "none" and levels[1] == "none",
              str(levels))
    lib.check("critique flags the step that does nothing", any("'nothing'" in i["issue"] for i in r1["critique"]["issues"]),
              str([i["issue"] for i in r1["critique"]["issues"]]))
    second = {**first, "steps": first["steps"][:1] + [{"name": "brighter", "adjust": {"exposure": 0.3}}]}
    r2 = lib.cli(renderer, "preview", recipe=json.dumps(second), image=str(src), note="brighter")
    lib.check("the next preview is the next version with a diff against the last", r2["version"] == f"v{n + 1}"
              and r2["diff"] is not None and Path(r2["diff"]).exists(), f"{r1['version']} -> {r2['version']}")
    out = tmp / f"from_version_{renderer}.png"
    lib.cli(renderer, "apply", recipe=r2["version"], image=str(src), output=str(out))
    exported = load_rgb(out)
    lib.check("apply renders a saved version at full resolution", exported.shape[:2] == (400, 600),
              str(exported.shape[:2]))
    natural = json.dumps({"label": "N", "steps": [{"look": "natural"}]})
    mono = json.dumps({"label": "M", "steps": [{"look": "mono"}]})
    board = lib.cli(renderer, "board", image=str(src), recipes=[natural, natural, mono])
    lib.check("board flags look-alike directions and not distinct ones", Path(board["board"]).exists()
              and any("N and N" in t for t in board["too_similar"]) and not any("M" in t for t in board["too_similar"]),
              str(board["too_similar"]))

    lib.check("preview json contract", set(r1) == {"version", "preview", "compare", "diff", "map", "cards", "review",
                                                   "critique", "impact", "after", "warnings", "notes"},
              str(sorted(set(r1) ^ {"version", "preview", "compare", "diff", "map", "cards", "review",
                                    "critique", "impact", "after", "warnings", "notes"})))
    lib.check("board json contract", set(board) == {"board", "tiles", "too_similar", "differences"})
    lib.check("critique json contract", set(r1["critique"]) == {"verdict", "issues", "skipped"}
              and r1["critique"]["verdict"] in ("clean", "needs work"))


def looks_and_critique():
    import develop

    half = develop.step_adjust({"look": "moody", "amount": 50})
    lib.check("look amount scales the grade", abs(half["exposure"] + 0.125) < 1e-9
              and half["hsl"]["green"]["sat"] == -20)
    over = develop.step_adjust({"look": "moody", "adjust": {"exposure": 0.1, "hsl": {"green": {"lum": 5}}}})
    lib.check("adjust overrides the look and merges hsl bands", over["exposure"] == 0.1
              and over["hsl"]["green"] == {"hue": 15, "sat": -40, "lum": 5})
    zero = develop.step_adjust({"look": "film", "amount": 0})
    lib.check("amount 0 is a no-op curve", all(abs(x - y) < 1e-9 for x, y in zero["curve"]))
    try:
        develop.step_adjust({"look": "vaporwave"})
        lib.check("unknown look is rejected", False)
    except ValueError:
        lib.check("unknown look is rejected", True)

    h, w = 300, 300
    yy, xx = np.mgrid[0:h, 0:w]
    person = (np.hypot(xx - 150, yy - 150) < 60).astype(np.float32)
    before = np.full((h, w, 3), 0.6, np.float32)
    after = before * 0.5
    ring = (np.hypot(xx - 150, yy - 150) < 66) & (person == 0)
    after[ring] = 0.6
    after[person > 0] = 0.6
    clean = before * 0.5
    clean[person > 0] = 0.6
    lib.check("critique catches a bright halo around the subject",
              (critique._halo(before, after, person) or 0) > 0.2, f"{critique._halo(before, after, person):.2f}")
    lib.check("critique leaves a clean background move alone",
              abs(critique._halo(before, clean, person) or 0) < 0.1)

    box = [0.4, 0.3, 0.6, 0.5]
    skin = np.full((h, w, 3), 0.85, np.float32)
    skin[90:150, 120:180] = (0.45, 0.3, 0.22)
    covered = skin.copy()
    covered[90:150, 120:180] = (0.04, 0.04, 0.05)
    covered[90:96, 125:175] = (0.45, 0.3, 0.22)
    from imaging import skin_mask

    lib.check("skin_mask finds an uncovered face", skin_mask(skin, box) is not None)
    lib.check("skin_mask gives up on a covered face", skin_mask(covered, box) is None)
    res = critique.run(skin, skin, [box], None, 0, [], [])
    lib.check("critique flags a face darker than its background",
              any("darker than the background" in i["issue"] for i in res["issues"]),
              str([i["issue"] for i in res["issues"]]))
    res = critique.run(covered, covered, [box], None, 0, [], [])
    lib.check("critique skips face checks on a covered face instead of measuring fabric",
              res["skipped"] and not any("face" in i["issue"] for i in res["issues"]))


def diagnostics(tmp):
    import feedready

    def findings(name, img):
        path = tmp / f"{name}.png"
        save_png16(img, path)
        args = type("Args", (), {"image": str(path)})()
        found = {}
        for f in feedready.cmd_inspect(args)["diagnostics"]["findings"]:
            found.setdefault(f["check"], f)
        return found

    dark = np.full((400, 600, 3), 0.08, np.float32)
    dark[300:306, 450:470] = 0.9
    dark += np.random.default_rng(1).normal(0, 0.01, dark.shape).astype(np.float32)
    spots = findings("spot", dark.clip(0, 1)).get("distractions")
    lib.check("distractions finds the lone bright strip",
              spots is not None and spots["evidence"]["spots"][0][:2] == [0.766, 0.756], str(spots and spots["evidence"]))

    import develop

    gray = np.full((400, 600, 3), 0.5, np.float32)
    gray[200:] = 0.6
    warm = develop.np_apply_op(gray, {"op": "matrix", "r": 1.12, "g": 1.0, "b": 0.9})
    cast = findings("warm", warm).get("color_cast")
    lib.check("color_cast proposes cooling a warm cast", cast is not None and cast["step"]["adjust"].get("temp", 0) < -8,
              str(cast and cast["step"]))

    under = findings("under", lib.card() * 0.25).get("exposure")
    lib.check("exposure proposes brightening an underexposed photo",
              under is not None and under["step"]["adjust"].get("exposure", 0) > 0, str(under and under["step"]))

    clean = findings("clean", lib.card())
    lib.check("a well-exposed neutral card gets no exposure or cast findings",
              "exposure" not in clean and "color_cast" not in clean, str(sorted(clean)))


def object_mask():
    if not edgetam_available():
        lib.skip("object mask (EdgeTAM model not installed)")
        return

    def iou(m, truth):
        b = m > 0.5
        return float((b & truth).sum() / (b | truth).sum())

    img = 0.1 + np.random.default_rng(2).normal(0, 0.03, (400, 600, 3)).astype(np.float32)
    img[120:260, 200:380] = (0.9, 0.3, 0.1)
    truth = np.zeros((400, 600), bool)
    truth[120:260, 200:380] = True
    scene = Scene(None, None, img.clip(0, 1))
    m = masks.build({"type": "object", "box": [190 / 600, 110 / 400, 390 / 600, 270 / 400]}, scene)
    lib.check("object mask from a box finds the rectangle", iou(m, truth) >= 0.9, f"iou {iou(m, truth):.3f}")
    m = masks.build({"type": "object", "points": [[290 / 600, 190 / 400]]}, scene)
    lib.check("object mask from one click finds the rectangle", iou(m, truth) >= 0.8, f"iou {iou(m, truth):.3f}")

    h, w = 1350, 900
    img = 0.1 + np.random.default_rng(2).normal(0, 0.03, (h, w, 3)).astype(np.float32)
    img[700:706, 350:550] = (0.95, 0.9, 0.3)
    truth = np.zeros((h, w), bool)
    truth[700:706, 350:550] = True
    m = masks.build({"type": "object", "box": [340 / w, 690 / h, 560 / w, 716 / h]}, Scene(None, None, img.clip(0, 1)))
    lib.check("object mask keeps a thin strip at full strength", iou(m, truth) >= 0.5 and m.max() > 0.9,
              f"iou {iou(m, truth):.3f} max {m.max():.2f}")


def heal():
    import detect
    import develop

    h, w = 400, 600
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    clean = np.stack([0.3 + 0.3 * xx / w, 0.35 + 0.2 * yy / h, np.full((h, w), 0.45, np.float32)], -1)
    clean = (clean + gaussian(np.random.default_rng(3).normal(0, 0.02, (h, w, 3)).astype(np.float32), 1)).clip(0, 1)
    spotted = clean.copy()
    spotted[190:210, 290:310] = 0.98
    mask = np.zeros((h, w), np.float32)
    mask[186:214, 286:314] = 1
    backends = [("mi-gan", migan_available()), ("opencv fsr", cv2 is not None and hasattr(cv2, "xphoto"))]
    saved = detect.MIGAN
    for name, available in backends:
        if not available:
            lib.skip(f"heal ({name} not installed)")
            continue
        healed = develop.heal(spotted, mask)
        inside = float(np.abs(healed[190:210, 290:310] - clean[190:210, 290:310]).mean())
        outside = float(np.abs(healed[:150] - spotted[:150]).max())
        lib.check(f"heal ({name}) fills the blob from its surroundings", inside < 0.05, f"mean abs diff {inside:.3f}")
        lib.check(f"heal ({name}) leaves the rest untouched", outside <= 1.5 / 255,
                  f"max err {outside * 255:.2f}/255")
        detect.MIGAN = Path("/nonexistent")
    detect.MIGAN = saved


def doctor_and_masks(tmp, src):
    import feedready

    report = feedready.cmd_doctor(None)
    lib.check("doctor reports the tier and features",
              set(report) == {"tier", "python", "engine (Core Image + Vision)", "opencv", "segformer scene masks",
                              "object masks (EdgeTAM)", "heal model (MI-GAN)", "output_dir", "heic", "missing"},
              str(sorted(report)))
    lib.check("doctor tier matches the engine", report["tier"] == feedready.tier()
              and isinstance(report["missing"], list))

    recipe = json.dumps({"steps": [{"name": "whole", "adjust": {"exposure": 0.2}},
                                   {"name": "left", "mask": {"type": "linear", "start": [0, 0.5], "end": [0.5, 0.5]},
                                    "adjust": {"exposure": 0.2}}]})
    with lib.basic_tier():
        args = type("Args", (), {"recipe": recipe, "image": str(src)})()
        out = feedready.cmd_masks(args)
    lib.check("masks builds a contact sheet with coverage",
              set(out) == {"contact_sheet", "mask_coverage", "notes"} and out["mask_coverage"][0] is None
              and 0 < out["mask_coverage"][1] < 1 and Path(out["contact_sheet"]).exists(),
              str(out["mask_coverage"]))
    with lib.basic_tier():
        args = type("Args", (), {"recipe": json.dumps({"steps": []}), "image": str(src)})()
        lib.check("masks rejects a recipe with no steps",
                  feedready.cmd_masks(args) == {"error": "recipe has no steps"})


def error_paths(src):
    import feedready

    def apply_error(recipe, image=str(src)):
        with lib.basic_tier():
            args = type("Args", (), {"recipe": recipe if isinstance(recipe, str) else json.dumps(recipe),
                                     "image": image, "output": None})()
            try:
                feedready.cmd_apply(args)
                return {}
            except SystemExit as e:
                return json.loads(e.code)

    e = apply_error({"steps": [{"look": "vaporwave"}]})
    lib.check("unknown look fails with json", "unknown look" in e.get("error", ""), str(e))
    e = apply_error({"preset": "a4", "steps": []})
    lib.check("unknown preset fails with json", "unknown preset" in e.get("error", ""), str(e))
    e = apply_error({"steps": [{"adjust": {"heal": True}, "mask": {"type": "all"}}]})
    lib.check("heal without a mask fails with json", "heal needs a mask" in e.get("error", ""), str(e))
    e = apply_error({"max_edge": 10, "steps": []})
    lib.check("tiny max_edge fails with json", "max_edge" in e.get("error", ""), str(e))
    e = apply_error({"crop": {"box": [0.5, 0.2, 0.4, 0.8]}, "steps": []})
    lib.check("empty crop box fails with json", "crop box" in e.get("error", ""), str(e))
    e = apply_error({"steps": [{"mask": {"type": "torus"}, "adjust": {"exposure": 1}}]})
    lib.check("unknown mask type fails with tiered json",
              "unknown mask type" in e.get("error", "") and e.get("tier") == "basic", str(e))
    e = apply_error("v99")
    lib.check("unknown version fails with json", "no version v99" in e.get("error", ""), str(e))
    bad = lib.tmp() / "bad.json"
    bad.write_text("{oops")
    e = lib.cli_error("apply", str(bad), str(src))
    lib.check("invalid recipe json fails with json", "not valid JSON" in e.get("error", ""), str(e))


def run():
    tmp = lib.tmp()
    src = tmp / "card.png"
    base = lib.card()
    save_png16(base, src)
    for renderer in renderers():
        print(f"  ({renderer})")
        per_renderer(renderer, tmp, base, src)
    print("  (looks + critique)")
    looks_and_critique()
    print("  (diagnostics)")
    diagnostics(tmp)
    print("  (models)")
    object_mask()
    heal()
    print("  (cli surface)")
    doctor_and_masks(tmp, src)
    error_paths(src)
