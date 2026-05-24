#!/usr/bin/env python3
"""
build_rpf.py — Kraymore Gunpack compilation driver.

Packs a directory of modified .yft / .ydr / .ytd files into a single
GTA V DLC archive (`dlc.rpf`) that is ready to be streamed by an alt:V
server resource.

The script is a thin orchestrator on top of OpenIV's command line
interface (`OpenIV.exe -cli`). OpenIV ships with a CLI that supports
batch-mode archive creation, file injection and re-saving with the
correct RAGE encryption / compression. We never re-implement the
proprietary RPF format ourselves — that is the job of OpenIV.

Reference: see "Command Line Mode" in OpenIV documentation
(https://openiv.com/?p=2640).

Typical invocation
------------------

    python build_rpf.py \
        --source ./build \
        --output ./dist/dlc.rpf \
        --openiv "C:\\Program Files\\OpenIV\\OpenIV.exe"

On non-Windows hosts pass `--openiv` pointing at the Wine-wrapped
binary, or use `--dry-run` to only validate the source tree.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

LOG = logging.getLogger("kraymore.build")

# File extensions that the gunpack is allowed to ship. Anything else in
# the source tree is treated as build noise and refused — this prevents
# accidentally streaming editor temp files, .psd sources, or stray
# weapons.meta overrides that would clash with the server's balance
# scripts (see README.md → "Why we never ship weapons.meta").
ALLOWED_EXTENSIONS = frozenset(
    {
        ".yft",   # Fragment Drawable — rigged weapon meshes
        ".ydr",   # Drawable Dictionary — static parts (scopes, suppressors, …)
        ".ytd",   # Texture Dictionary  — diffuse + emissive maps
        ".ypt",   # Particle dictionary — muzzle flash / tracer VFX
    }
)

# Subset of the GTA V weapon catalogue that the Kraymore pack covers.
# Keeping this list explicit gives `--strict` mode something to verify
# against before we hand a half-finished pack to OpenIV.
EXPECTED_WEAPONS = (
    "w_pi_heavypistol",
    "w_ar_assaultrifle",
    "w_ar_carbinerifle",
    "w_sb_microsmg",
    "w_sr_marksmanrifle",
)


@dataclasses.dataclass
class BuildPlan:
    source: Path
    output: Path
    openiv: Path | None
    strict: bool
    dry_run: bool
    keep_workdir: bool


def parse_args(argv: list[str] | None = None) -> BuildPlan:
    p = argparse.ArgumentParser(
        description="Compile the Kraymore gunpack into a streamable dlc.rpf"
    )
    p.add_argument(
        "--source",
        type=Path,
        default=Path("build"),
        help="Directory containing modified .yft/.ydr/.ytd/.ypt files",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("dist/dlc.rpf"),
        help="Path to the dlc.rpf that will be produced",
    )
    p.add_argument(
        "--openiv",
        type=Path,
        default=None,
        help="Path to OpenIV.exe (omit on --dry-run)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Fail unless every weapon in EXPECTED_WEAPONS has a .yft and .ytd",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the source tree but do not invoke OpenIV",
    )
    p.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Leave the intermediate staging directory in place for inspection",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    return BuildPlan(
        source=args.source.resolve(),
        output=args.output.resolve(),
        openiv=args.openiv.resolve() if args.openiv else None,
        strict=args.strict,
        dry_run=args.dry_run,
        keep_workdir=args.keep_workdir,
    )


def iter_assets(source: Path) -> Iterable[Path]:
    if not source.is_dir():
        raise FileNotFoundError(f"--source directory not found: {source}")
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
            yield path


def validate(plan: BuildPlan) -> list[Path]:
    assets = list(iter_assets(plan.source))
    if not assets:
        raise SystemExit(
            f"No allowed assets found under {plan.source}. "
            f"Expected files with extensions: {sorted(ALLOWED_EXTENSIONS)}"
        )

    stems = {a.stem.lower() for a in assets}

    # Refuse rogue files. The RAGE pipeline silently ignores unknown
    # files inside dlc.rpf and they cost streaming bandwidth.
    suspicious = [
        p for p in plan.source.rglob("*") if p.is_file() and p.suffix.lower() not in ALLOWED_EXTENSIONS
    ]
    for s in suspicious:
        LOG.warning("ignoring %s (extension not in allowlist)", s)

    if plan.strict:
        missing: list[str] = []
        for weapon in EXPECTED_WEAPONS:
            if weapon not in stems:
                missing.append(weapon)
        if missing:
            raise SystemExit(
                "--strict: missing required weapon assets: " + ", ".join(missing)
            )

    LOG.info("validated %d asset(s) from %s", len(assets), plan.source)
    return assets


def stage(assets: list[Path], workdir: Path) -> None:
    """Flatten the source tree into the layout OpenIV expects inside
    the resulting dlc.rpf: every weapon file goes to the archive root.

    GTA V's stream loader resolves weapon .yft / .ytd assets by name
    hash, not by directory, so the flat layout is both legal and the
    most compact.
    """
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    for asset in assets:
        target = workdir / asset.name
        if target.exists():
            raise SystemExit(
                f"duplicate asset name: {asset.name} "
                f"(weapon files must be unique inside dlc.rpf)"
            )
        shutil.copy2(asset, target)
        LOG.debug("staged %s -> %s", asset, target)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(workdir: Path, output: Path) -> Path:
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(workdir.iterdir()):
        if path.is_file():
            entries.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    payload = {
        "name": output.name,
        "asset_count": len(entries),
        "assets": entries,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOG.info("wrote manifest %s (%d assets)", manifest_path, len(entries))
    return manifest_path


def resolve_openiv(plan: BuildPlan) -> Path:
    if plan.openiv is not None:
        if not plan.openiv.exists():
            raise SystemExit(f"--openiv path does not exist: {plan.openiv}")
        return plan.openiv

    candidates = [
        Path(r"C:\Program Files\OpenIV\OpenIV.exe"),
        Path(r"C:\Program Files (x86)\OpenIV\OpenIV.exe"),
        Path.home() / "OpenIV" / "OpenIV.exe",
    ]
    for c in candidates:
        if c.exists():
            LOG.info("auto-detected OpenIV at %s", c)
            return c

    raise SystemExit(
        "OpenIV.exe was not found. Pass --openiv <path> or install OpenIV.\n"
        "On Linux/macOS run OpenIV under Wine and point --openiv at the "
        "wrapper binary."
    )


def invoke_openiv(plan: BuildPlan, workdir: Path) -> None:
    """Invoke OpenIV in CLI mode.

    The current OpenIV CLI accepts (per official docs):
        OpenIV.exe -cli -mode:create -src:<dir> -dst:<rpf> -platform:pc

    `-platform:pc` is the standard PC platform identifier for GTA V's
    encrypted RPF8 format. Earlier versions of the CLI used -fmt
    instead — see OpenIV release notes if your install is older than
    4.0.
    """
    openiv = resolve_openiv(plan)
    plan.output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(openiv),
        "-cli",
        "-mode:create",
        f"-src:{workdir}",
        f"-dst:{plan.output}",
        "-platform:pc",
    ]

    LOG.info("invoking OpenIV: %s", " ".join(cmd))
    if platform.system() != "Windows":
        LOG.warning(
            "running OpenIV outside Windows — make sure --openiv points at "
            "a Wine-wrapped binary. Native Linux OpenIV does not exist."
        )

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        LOG.debug("OpenIV stdout:\n%s", result.stdout)
    if result.stderr:
        LOG.debug("OpenIV stderr:\n%s", result.stderr)

    if result.returncode != 0:
        raise SystemExit(
            f"OpenIV CLI exited with code {result.returncode}. "
            f"stderr:\n{result.stderr.strip() or '<empty>'}"
        )

    if not plan.output.exists():
        raise SystemExit(
            f"OpenIV exited 0 but the expected output {plan.output} "
            "was not produced. Inspect OpenIV logs."
        )


def main(argv: list[str] | None = None) -> int:
    plan = parse_args(argv)
    LOG.debug("plan: %s", plan)

    assets = validate(plan)

    workdir = plan.output.parent / "_kraymore_stage"
    try:
        stage(assets, workdir)

        if plan.dry_run:
            LOG.info("--dry-run: would pack %d asset(s) into %s",
                     len(assets), plan.output)
        else:
            invoke_openiv(plan, workdir)
            LOG.info("built %s (%.1f KiB)",
                     plan.output, plan.output.stat().st_size / 1024)

        write_manifest(workdir, plan.output)
    finally:
        if not plan.keep_workdir and workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
