import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib

FEEDREADY = lib.SCRIPTS / "feedready.py"

out = {}
photos = lib.corpus_photos() + lib.corpus_photos(("private",))
for photo in photos:
    rel = str(photo.relative_to(lib.CORPUS))
    res = subprocess.run([sys.executable, str(FEEDREADY), "inspect", str(photo)],
                         capture_output=True, text=True)
    if res.returncode:
        out[rel] = {"error": res.stderr.strip()[:200]}
        print(rel, "ERROR")
        continue
    r = json.loads(res.stdout)
    out[rel] = {
        "genre": r["profile"]["genre"],
        "hero": r["profile"]["hero"],
        "signals": r["profile"]["signals"],
        "findings": {f["check"]: {"finding": f["finding"], "step": f.get("step"), "crop": bool(f.get("crop"))}
                     for f in r["diagnostics"]["findings"]},
        "skipped": r["diagnostics"]["skipped"],
    }
    print(rel, out[rel]["genre"], "|", ",".join(out[rel]["findings"]))

Path("/tmp/corpus-diagnostics.json").write_text(json.dumps(out, indent=1, sort_keys=True))
print("wrote /tmp/corpus-diagnostics.json for", len(out), "photos")
