# Texture templates

This directory is where pre-rendered `kraymore!` decals live as raw
source images, *before* they are baked into the per-weapon emissive
maps described in `../../shaders/README.md`.

## Expected files (not checked in)

| File                                  | Purpose                                  |
|---------------------------------------|------------------------------------------|
| `kraymore_logo_master_4k.png`         | Vector logo rasterised at 4096×1024 for resampling per weapon. |
| `kraymore_logo_magenta.png`           | Pre-coloured neon-magenta variant.       |
| `kraymore_logo_toxic.png`             | Pre-coloured toxic-green variant.        |

These are **PSD/PNG sources** intended for human editing; they are
deliberately *not* committed to the repository to keep clone size
small. Generate them from `kraymore_logo.svg` (provided here) with
your editor of choice.

## Why this layout

The compile script (`scripts/build_rpf.py`) only ships RAGE-native
asset extensions (`.yft`, `.ydr`, `.ytd`, `.ypt`). Anything in this
folder is editor-side source material and is explicitly skipped by
the allowlist in `ALLOWED_EXTENSIONS`. You can drop PSDs here without
worrying about polluting the resulting `dlc.rpf`.
