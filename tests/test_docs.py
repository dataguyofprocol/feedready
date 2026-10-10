from __future__ import annotations

import re

import lib
import develop
import detect

VIBES = lib.ROOT / "skills" / "feedready" / "reference" / "vibes.md"
RECIPE = lib.ROOT / "skills" / "feedready" / "reference" / "recipe.md"
SKILL = lib.ROOT / "skills" / "feedready" / "SKILL.md"
SWIFT = lib.ROOT / "skills" / "feedready" / "swift" / "feedready_engine.swift"


def section(text, start, end):
    body = text.split(start, 1)[1]
    return body.split(end, 1)[0]


def test_looks_names():
    vibes = section(VIBES.read_text(), "## Looks", "## Directions")
    vibes_names = re.findall(r"^\| `([a-z-]+)`", vibes, re.M)
    recipe_line = re.search(r"Looks: (.*)\n", RECIPE.read_text()).group(1)
    recipe_names = re.findall(r"`([a-z-]+)`", recipe_line)
    lib.check("look names match vibes.md", set(vibes_names) == set(develop.LOOKS), f"vibes={vibes_names}")
    lib.check("look names match recipe.md", set(recipe_names) == set(develop.LOOKS), f"recipe={recipe_names}")


def test_slider_ranges():
    ranges = {}
    for key1, key2, lo, hi in re.findall(r"^\| `(\w+)`(?: / `(\w+)`)? \| (-?\d+)…(-?\d+) \|", RECIPE.read_text(), re.M):
        for key in (key1, key2):
            if key:
                ranges[key] = (int(lo), int(hi))
    code = {k: v[:2] for k, v in develop.SLIDERS.items()}
    lib.check("slider ranges match recipe.md", ranges == code,
              f"docs-only={set(ranges) - set(code)} code-only={set(code) - set(ranges)}")


def test_hsl_bands():
    text = RECIPE.read_text()
    bands = re.search(r"bands: ([a-z, ]+);", text).group(1).replace(" ", "").split(",")
    hue_line = re.search(r"hue in degrees \(([^)]+)\)", text).group(1)
    degrees = {name: int(deg) for name, deg in re.findall(r"([a-z]+) (\d+)", hue_line)}
    lib.check("hsl band names match recipe.md", bands == list(develop.HSL_BANDS), f"docs={bands}")
    lib.check("hsl hue degrees match recipe.md", degrees == develop.HSL_BANDS, f"docs={degrees}")


def test_presets():
    text = RECIPE.read_text()
    found = {name: (int(w), int(h)) for name, w, h in
             re.findall(r"`(instagram|story|linkedin)` \((\d+):(\d+)[;)]", text)}
    code = {k: v["aspect"] for k, v in develop.PRESETS.items() if v["aspect"]}
    lib.check("preset aspects match recipe.md", found == code, f"docs={found} code={code}")
    lib.check("original preset is documented", "`original`" in text)


def test_mask_types():
    text = RECIPE.read_text()
    documented = set(re.findall(r'"type": "([a-z]+)"', text))
    geometric = {"radial", "linear", "polygon", "brush", "luminance", "color"}
    detected = {"person", "subject", "background", "face", "segment", "sky", "object"}
    lib.check("every documented mask type exists in masks.py",
              documented == geometric | detected, f"docs={sorted(documented)}")
    swift_types = {"person", "subject"}
    lib.check("combinators are documented", all(f'"op": "{op}"' in text for op in ("union", "intersect", "subtract")))
    skill = SKILL.read_text()
    works = re.search(r"- Works: (.+)", skill).group(1)
    blocked = re.search(r"- Doesn't work: (.+?)\.", skill).group(1)
    lib.check("skill basic tier lists every geometric mask",
              all((t if t != "color" else "colour") in works for t in geometric), works)
    lib.check("skill basic tier blocks every detected mask",
              all(t in blocked for t in detected - {"sky"}), blocked.replace("\n", " "))


def test_segment_aliases():
    friendly = re.search(r"Friendly names: ([^.]+)\.", RECIPE.read_text()).group(1)
    names = set()
    for name in re.findall(r"([a-z]+)(\(s\))?", friendly):
        names.add(name[0])
        if name[1]:
            names.add(name[0] + "s")
    lib.check("segment friendly names match detect.py", names == set(detect.SEG_ALIASES),
              f"docs={sorted(names)} code={sorted(detect.SEG_ALIASES)}")


def test_commands():
    import feedready

    skill_commands = set(re.findall(r"^\| `([a-z]+)[^`]*` \|", section(SKILL.read_text(), "**Commands:**", "A RECIPE"), re.M))
    usage = feedready.USAGE
    usage_commands = set(re.findall(r"feedready\.py (\w+)", usage))
    expected = {"doctor", "inspect", "masks", "board", "preview", "apply"}
    lib.check("skill command table matches the cli", skill_commands == expected, f"skill={skill_commands}")
    lib.check("usage text matches the cli", usage_commands == expected, f"usage={usage_commands}")


def test_engine_contract():
    swift = SWIFT.read_text()
    swift_ops = set(re.findall(r'^\s+case "([a-z_]+)":', swift, re.M))
    adjust = {"temp": 10, "tint": -10, "exposure": 0.3, "shadows": 20, "highlights": -20, "contrast": 10,
              "whites": 10, "blacks": -10, "hsl": {"blue": {"sat": -10}}, "vibrance": 10, "saturation": -10,
              "sharpen": 10}
    code_ops = {op["op"] for op in develop.build_ops(adjust, 1600)}
    lib.check("engine handles every op build_ops emits", swift_ops == code_ops,
              f"swift-only={swift_ops - code_ops} code-only={code_ops - swift_ops}")
    plan_keys = ("input", "output", "quality", "steps", "crop", "resize", "vignette", "p3")
    lib.check("engine reads every plan key", all(f'"{key}"' in swift for key in plan_keys))
    render_src = (lib.SCRIPTS / "render.py").read_text()
    lib.check("cube dimension travels with the plan", "dim=develop.CUBE_DIM" in render_src and 'num(op, "dim")' in swift)


def run():
    test_looks_names()
    test_slider_ranges()
    test_hsl_bands()
    test_presets()
    test_mask_types()
    test_segment_aliases()
    test_commands()
    test_engine_contract()
