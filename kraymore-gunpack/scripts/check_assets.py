#!/usr/bin/env python3
"""
check_assets.py — pre-flight verification of the source asset tree.

Designed to be called from CI or a pre-commit hook *before* invoking
`build_rpf.py`. It is intentionally cheaper than the full builder:
no OpenIV, no staging, no archive creation. It just walks the source
tree and confirms:

  1.  Every expected weapon has a matching `.ytd` (texture dict).
  2.  Every weapon that has a `.yft` also has a `.ytd` of the same stem
      (a `.yft` without a `.ytd` will load with the default texture).
  3.  The emissive companion texture `kraymore_emissive` is present in
      at least one `.ytd` (we cannot inspect inside the dictionary
      without OpenIV, so we check via a sibling sentinel file).

Exit code 0 means "build is allowed". Non-zero means "do not ship".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


EXPECTED_WEAPONS = (
    "w_pi_heavypistol",
    "w_ar_assaultrifle",
    "w_ar_carbinerifle",
    "w_sb_microsmg",
    "w_sr_marksmanrifle",
)

EMISSIVE_SENTINEL = "kraymore_emissive.present"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path("build"))
    args = p.parse_args()

    src: Path = args.source
    if not src.is_dir():
        print(f"FAIL: source directory not found: {src}", file=sys.stderr)
        return 2

    files = {f.stem.lower(): f for f in src.rglob("*") if f.is_file()}
    errors: list[str] = []

    for weapon in EXPECTED_WEAPONS:
        if weapon not in files:
            errors.append(f"missing asset for weapon: {weapon}")
            continue
        # both yft and ytd should exist for full pack
        siblings = {p.suffix.lower() for p in src.rglob(weapon + ".*")}
        if ".ytd" not in siblings:
            errors.append(f"{weapon}: missing .ytd (texture dictionary)")
        if ".yft" not in siblings:
            errors.append(f"{weapon}: missing .yft (fragment drawable)")

    sentinel = src / EMISSIVE_SENTINEL
    if not sentinel.exists():
        errors.append(
            f"missing sentinel {EMISSIVE_SENTINEL} — create an empty file with "
            "this name next to each .ytd that has the kraymore_emissive map "
            "baked in, to confirm the emissive workflow was applied."
        )

    if errors:
        print("check_assets: FAILED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"check_assets: OK ({len(EXPECTED_WEAPONS)} weapons verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
