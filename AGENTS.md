# AGENTS.md

Repo is a Claude Code plugin (`feedready`) that is also its own plugin marketplace (`.claude-plugin/marketplace.json`). The README is accurate — trust it, but the gotchas below are what agents get wrong.

## Commands

```bash
# Test — the only verification step; no CI, lint, or typecheck exists
~/.cache/feedready/venv/bin/python tests/selftest.py   # must end with "ALL PASSED"

# Engine CLI (prints JSON); run from skills/feedready/
./run.sh doctor | inspect <photo> | masks <recipe> <photo> | apply <recipe> <photo>

# Rebuild runtime (safe to rerun); --segformer / --models download models (~75 MB)
skills/feedready/setup.sh --segformer --models

# Phone upload bundle → ~/Desktop/feedready.zip
./build_zip.sh [outfile]
```

- The venv lives at `~/.cache/feedready/venv` (Python 3.14, created by `setup.sh`); if missing, `run.sh` falls back to `python3`.
- Selftest skips model-dependent checks (EdgeTAM, MI-GAN) with `skip` when models aren't installed — `ALL PASSED` with skips is not full coverage.

## Editing workflow (the part that's easy to get wrong)

- **Claude Code runs an installed copy** at `~/.claude/plugins/cache/feedready/`. Never edit that copy. Edit the repo, then ship via: bump `version` in `.claude-plugin/plugin.json` → `claude plugin marketplace update feedready && claude plugin update feedready@feedready` → `/reload-plugins`.
- Changing `skills/feedready/swift/feedready_engine.swift` requires rerunning `setup.sh` (it records a sha256; `doctor` reports the engine stale until rebuilt).
- Any skill change means rebuilding and re-uploading `build_zip.sh` for the phone tier.
- Commit messages use conventional commits scoped to the package: `feat(feedready): ...`, `fix(feedready): ...`.

## Architecture

- `skills/feedready/scripts/feedready.py` — CLI entrypoint and pipeline (working copy → masks → prepass → render → compare).
- `scripts/diagnose.py` — every suggestion is one function in the `CHECKS` list (line ~241); add checks there.
- `scripts/detect.py` — owns **all** model and engine paths (`~/.cache/feedready/...`); other modules import from it.
- `scripts/masks.py` (mask specs → masks), `scripts/develop.py` (Lightroom sliders → engine ops + prepass), `scripts/imaging.py` (numpy primitives).
- `swift/feedready_engine.swift` — Core Image/Vision renderer. Without it (or off macOS), everything falls back to numpy: that's the "basic"/phone tier.
- `skills/feedready/SKILL.md` is the runtime instructions for Claude; `reference/recipe.md` is the recipe schema reference. Keep them in sync with script behavior.

## Conventions worth knowing

- **No code comments or docstrings** — in any language (Python, Swift, shell). The codebase is comment-free by choice; don't add explanatory comments, inline or standalone. Shebangs and user-facing strings (e.g. the argparse `USAGE` help text) are not comments — keep those. Explain design intent in commit messages instead.
- **Two tiers.** Person/subject/face/segment/object masks and `heal` need the Mac engine/models; the phone tier must not fake them — route the user to the Mac instead. `doctor` reports tier and what's missing.
- **Coordinates are fractions of the original photo, origin top-left, before crop** — crop is applied last. Read coordinates off the `inspect` grid image, never by eye.
- All state (venv, models, engine, per-photo work dirs) lives in `~/.cache/feedready/`; the repo and plugin copy stay code-only (`build_zip.sh` excludes `swift/`, `setup.sh`, `__pycache__`). Final images go to `~/Pictures/feedready/` (Mac) or `/mnt/user-data/outputs/` (phone).
- Requirements: Apple Silicon, macOS 14+, Xcode CLT (`swiftc`), `uv` or Python 3.14. Model licences are personal-use-only for some (see README) — don't add models without noting licence implications.
