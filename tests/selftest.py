from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

SUITES = ("units", "docs", "render", "engine", "golden", "corpus", "suggest", "eval")


def main():
    ap = argparse.ArgumentParser(description="feedready self-test")
    ap.add_argument("--suite", action="append", choices=SUITES, help="run only this suite (repeatable)")
    ap.add_argument("--regen", action="store_true", help="rebaseline goldens and eval fingerprints")
    ap.add_argument("--fetch-corpus", action="store_true", help="download the kodak + commons test corpus")
    args = ap.parse_args()
    if args.fetch_corpus:
        import test_corpus

        test_corpus.fetch()
        return
    lib.REGEN = args.regen
    for name in args.suite or SUITES:
        print(f"[{name}]")
        __import__(f"test_{name}").run()
    print("\nALL PASSED" if not lib.FAILS else f"\nFAILED: {lib.FAILS}")
    sys.exit(1 if lib.FAILS else 0)


if __name__ == "__main__":
    main()
