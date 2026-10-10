from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

import lib
import imaging
from imaging import load_rgb

KODAK_URL = "http://r0k.us/graphics/kodak/kodim{:02d}.png"
COMMONS_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=1800"
USER_AGENT = "feedready-selftest/0.2 (https://github.com/dataguyofprocol/feedready)"

COMMONS_FILES = {
    "portrait-light": "AR700164-Edit.jpg",
    "portrait-dark": "AR700076-Edit.jpg",
    "selfie": "2025 11 JB.jpg",
    "group": "Friends forever.jpg",
    "backlit": "(306-365) Sandstorm (6120514673).jpg",
    "person-mountains": "Bluff Knoll, Stirling Range, Western Australia.jpg",
    "mountains": "Gentau Pic du Midi Ossau.jpg",
    "night-city": "Union Square Lights (52458666007).jpg",
    "food": "Full English breakfast at Sainsbury's Low Hall, Chingford, London.jpg",
    "low-light": "Het Wapen van Ermelo.jpg",
    "sunset": "Mekong water reflection of lightings of Don Det and colorful sky at sunset seen from a sand beach in Laos.jpg",
    "colour-cast": "Inside the Wild Wing pub (20563631078).jpg",
}

CREDITS = """portrait-light: File:AR700164-Edit.jpg by Nellacphoto, CC BY 4.0, https://commons.wikimedia.org/wiki/File:AR700164-Edit.jpg
portrait-dark: File:AR700076-Edit.jpg by Nellacphoto, CC BY 4.0, https://commons.wikimedia.org/wiki/File:AR700076-Edit.jpg
selfie: File:2025 11 JB.jpg by Octavosaurus, CC BY-SA 4.0, https://commons.wikimedia.org/wiki/File:2025_11_JB.jpg
group: File:Friends forever.jpg by Sarfraz sarik, CC BY-SA 4.0, https://commons.wikimedia.org/wiki/File:Friends_forever.jpg
backlit: File:(306-365) Sandstorm (6120514673).jpg by Sander van der Wel from Netherlands, CC BY-SA 2.0, https://commons.wikimedia.org/wiki/File:(306-365)_Sandstorm_(6120514673).jpg
person-mountains: File:Bluff Knoll, Stirling Range, Western Australia.jpg by SamJeffs1, CC BY-SA 4.0, https://commons.wikimedia.org/wiki/File:Bluff_Knoll,_Stirling_Range,_Western_Australia.jpg
mountains: File:Gentau Pic du Midi Ossau.jpg by Myrabella, CC BY-SA 3.0, https://commons.wikimedia.org/wiki/File:Gentau_Pic_du_Midi_Ossau.jpg
night-city: File:Union Square Lights (52458666007).jpg by Eden, Janine and Jim from New York City, CC BY 2.0, https://commons.wikimedia.org/wiki/File:Union_Square_Lights_(52458666007).jpg
food: File:Full English breakfast at Sainsbury's Low Hall, Chingford, London.jpg by Acabashi, CC BY-SA 4.0, https://commons.wikimedia.org/wiki/File:Full_English_breakfast_at_Sainsbury%27s_Low_Hall,_Chingford,_London.jpg
low-light: File:Het Wapen van Ermelo.jpg by Dennis van Zuijlekom, CC BY-SA 2.0, https://commons.wikimedia.org/wiki/File:Het_Wapen_van_Ermelo.jpg
sunset: File:Mekong water reflection of lightings of Don Det and colorful sky at sunset seen from a sand beach in Laos.jpg by Basile Morin, CC BY-SA 4.0, https://commons.wikimedia.org/wiki/File:Mekong_water_reflection_of_lightings_of_Don_Det_and_colorful_sky_at_sunset_seen_from_a_sand_beach_in_Laos.jpg
colour-cast: File:Inside the Wild Wing pub (20563631078).jpg by shankar s. from Dubai, united arab emirates, CC BY 2.0, https://commons.wikimedia.org/wiki/File:Inside_the_Wild_Wing_pub_(20563631078).jpg
"""


def _download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as res, open(dest, "wb") as f:
        f.write(res.read())


def fetch():
    kodak = lib.CORPUS / "kodak"
    kodak.mkdir(parents=True, exist_ok=True)
    for i in range(1, 25):
        dest = kodak / f"kodim{i:02d}.png"
        if dest.exists() and dest.stat().st_size > 100_000:
            continue
        print(f"  fetch {dest.name}")
        _download(KODAK_URL.format(i), dest)
    commons = lib.CORPUS / "commons"
    commons.mkdir(parents=True, exist_ok=True)
    for name, wiki in COMMONS_FILES.items():
        dest = commons / f"{name}.jpg"
        if dest.exists() and dest.stat().st_size > 50_000:
            continue
        print(f"  fetch {dest.name}")
        quoted = urllib.parse.quote(f"File:{wiki}")
        _download(COMMONS_URL.format(quoted), dest)
    (commons / "CREDITS.txt").write_text(CREDITS)
    print("  corpus ready in", lib.CORPUS)


def _completeness():
    missing = [f"kodak/kodim{i:02d}.png" for i in range(1, 25)
               if not (lib.CORPUS / "kodak" / f"kodim{i:02d}.png").exists()]
    missing += [f"commons/{n}.jpg" for n in COMMONS_FILES
                if not (lib.CORPUS / "commons" / f"{n}.jpg").exists()]
    return missing


def run():
    photos = lib.corpus_photos()
    if not photos:
        lib.skip("corpus (run tests/selftest.py --fetch-corpus to download it)")
        return
    missing = _completeness()
    lib.check("corpus is complete", not missing, f"missing {missing}")
    recipe = {"steps": [{"look": "natural"}], "max_edge": 1200}
    bad = []
    for photo in photos:
        out = lib.tmp() / f"corpus-{photo.stem}.jpg"
        try:
            rendered = lib.apply_np(recipe, photo, out)
        except Exception as e:
            bad.append(f"{photo.name}: {e}")
            continue
        if not np.isfinite(rendered).all() or max(rendered.shape[:2]) > 1200:
            bad.append(photo.name)
    lib.check("every corpus photo renders on the numpy tier", not bad, str(bad))

    import feedready

    with lib.basic_tier():
        args = type("Args", (), {"image": str(photos[0])})()
        report = feedready.cmd_inspect(args)
    lib.check("inspect covers a corpus photo",
              {"work_dir", "size", "tier", "stats", "megapixels", "file_mb", "large", "color_space", "profile",
               "diagnostics", "grid", "original"} <= set(report)
              and set(report["diagnostics"]) == {"findings", "skipped"},
              str(sorted(report)[:6]))
