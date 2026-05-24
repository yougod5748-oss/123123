# kraymore-gunpack

End-to-end build pipeline for the **Kraymore Gunpack** — a streamable
weapon-cosmetics pack for [alt:V](https://altv.mp/) roleplay servers,
built on top of GTA V's RAGE engine via [OpenIV](https://openiv.com/).

The pack delivers:

-   **Carbon-fibre / matte base materials** for five high-traffic
    weapons (Heavy Pistol, Assault Rifle, Carbine Rifle, Micro SMG,
    Marksman Rifle).
-   **Neon emissive `kraymore!` branding** on every weapon, glowing
    even in zero-lighting environments — this is the pack's signature
    "catch".
-   A reproducible **compilation script** that turns your edited
    `.yft / .ydr / .ytd` files into a ready-to-stream `dlc.rpf`.
-   alt:V resource manifests so the archive lands on every connected
    client without touching the server's combat balance.

> ⚠️ This repository contains **only the build pipeline and config**.
> The proprietary GTA V model and texture data must be extracted from
> your local, legally-owned copy of the game using OpenIV. Nothing in
> this repository ships Rockstar IP.

---

## Repository layout

```
kraymore-gunpack/
├── README.md                  ← you are here
├── manifest.json              ← machine-readable asset mapping
│
├── scripts/
│   ├── build_rpf.py           ← orchestrates OpenIV CLI to produce dlc.rpf
│   └── check_assets.py        ← pre-flight asset validation
│
├── server/
│   ├── resource.toml          ← alt:V resource manifest
│   ├── stream.toml            ← single-source-of-truth weapon/VFX list
│   └── server-additions.toml  ← snippet to append to your server.toml
│
├── shaders/
│   ├── kraymore_emissive.ytd.xml  ← CodeWalker shader fragment
│   └── README.md              ← emissive-map authoring workflow
│
├── textures/
│   └── templates/
│       ├── README.md
│       └── kraymore_logo.svg  ← master wordmark
│
└── build/                     ← (gitignored) drop modified assets here
```

---

## Asset mapping

| Class            | Model hash (`.yft`/`.ytd` stem) | Weapon hash             | `kraymore!` anchor                                |
|------------------|---------------------------------|-------------------------|---------------------------------------------------|
| Heavy Pistol     | `w_pi_heavypistol`              | `WEAPON_HEAVYPISTOL`    | Rear of slide, under rear sight                   |
| Assault Rifle    | `w_ar_assaultrifle`             | `WEAPON_ASSAULTRIFLE`   | Side of upper receiver                            |
| Carbine Rifle    | `w_ar_carbinerifle`             | `WEAPON_CARBINERIFLE`   | Side of upper receiver / optic housing            |
| Micro SMG        | `w_sb_microsmg`                 | `WEAPON_MICROSMG`       | Flat of magwell                                   |
| Marksman Rifle   | `w_sr_marksmanrifle`            | `WEAPON_MARKSMANRIFLE`  | Side of receiver, ahead of scope mount            |

The same table lives in machine-readable form in
[`manifest.json`](./manifest.json) and is consumed by both
`build_rpf.py --strict` and `check_assets.py`.

---

## Author workflow

The full pipeline, step by step:

### 1. Extract the originals (OpenIV)

In OpenIV (Windows host, Edit Mode):

```
update/x64/dlcpacks/patchday8ng/dlc.rpf/x64/models/cdimages/weapons.rpf
```

Export every `.yft` and `.ytd` listed in the asset mapping into
`kraymore-gunpack/build/` on this machine. Keep the original filenames
— the build script depends on them.

### 2. Texture & material edits

Follow [`shaders/README.md`](./shaders/README.md) to:

1.  Author the carbon-fibre diffuse for each weapon.
2.  Author the `kraymore_emissive` mask (black background, neon
    lettering only).
3.  Re-pack the modified textures into each weapon's `.ytd`.
4.  Inject the shader fragment from
    [`shaders/kraymore_emissive.ytd.xml`](./shaders/kraymore_emissive.ytd.xml)
    into the weapon's drawable so the emissive sampler is bound.

### 3. Sentinel files

For every `.ytd` where you applied the emissive workflow, create an
empty file named `kraymore_emissive.present` next to it. The pre-flight
validator uses this as a binary signal that the manual emissive step
was actually performed (since it cannot peek inside the dictionary
without OpenIV).

```sh
touch kraymore-gunpack/build/kraymore_emissive.present
```

### 4. Pre-flight check

```sh
python kraymore-gunpack/scripts/check_assets.py --source kraymore-gunpack/build
```

Exits non-zero if any expected weapon is missing a `.yft` / `.ytd`, or
if the sentinel file is absent.

### 5. Compile `dlc.rpf`

On a Windows machine with OpenIV installed:

```sh
python kraymore-gunpack/scripts/build_rpf.py \
    --source kraymore-gunpack/build \
    --output kraymore-gunpack/dist/dlc.rpf \
    --strict
```

Useful flags:

-   `--openiv "C:\Program Files\OpenIV\OpenIV.exe"` — point at a
    non-default install location.
-   `--dry-run` — validate the source tree without touching OpenIV.
-   `--keep-workdir` — preserve the staging directory for inspection.
-   `-v` — verbose logging (DEBUG level).

The script writes two artefacts:

```
kraymore-gunpack/dist/dlc.rpf           # the archive itself
kraymore-gunpack/dist/dlc.manifest.json # SHA-256 of every packed file
```

The manifest is what your server CI should diff between releases.

### 6. Deploy to alt:V

```
your-server/
└── resources/
    └── kraymore-gunpack/
        ├── resource.toml         # copy from server/resource.toml
        └── stream/
            └── dlc.rpf           # copy from dist/dlc.rpf
```

Append `"kraymore-gunpack"` to the `resources` array in your
`server.toml` (see [`server/server-additions.toml`](./server/server-additions.toml))
and restart. alt:V will stream the archive to every connecting client
automatically; no client-side install is required.

---

## Design constraints

These are not arbitrary — they are why the pack stays compatible
with serious roleplay/PvP servers:

1.  **No `weapons.meta` overrides.** `weapons.meta` controls damage,
    spread and recoil. Shipping it would silently overwrite the
    server's combat balance. The pack therefore restricts itself to
    `.yft / .ydr / .ytd / .ypt` files.
2.  **No client-side ASI / Mods folder install.** Everything is
    streamed via alt:V at runtime. Players join the server clean and
    leave clean.
3.  **No hash drift.** Existing model hashes (`w_pi_heavypistol` &c.)
    are re-used. Every weapon ID still resolves to the same hash in
    server-side scripts, so inventory/SQL/Discord-logger integrations
    keep working without migrations.
4.  **`kraymore!` is emissive, not diffuse.** A flat decal disappears
    in dark scenes; an emissive map keeps the brand visible at any
    time of day, in tunnels, under tinted scope glass, and even
    through partial occlusion.

---

## Generative AI prompt (Gemini / Claude / GPT-class models)

If you want a chat model to extend this pipeline (additional weapons,
new VFX, alt branding), feed it the prompt below. It is tuned for
English-language LLMs because the public modding corpus they were
trained on is overwhelmingly in English, and it constrains the model
to emit code and config rather than narrative.

````
Act as a Senior Technical Modding Architect specializing in the
Rockstar Advanced Game Engine (RAGE), OpenIV toolset, and alt:V
multiplayer framework infrastructure. Your expertise covers .ytd
texture dictionaries, emissive shader mapping, and server-side
resource streaming manifests.

I am extending the "Kraymore Gunpack" — a streamable alt:V resource
that retextures five GTA V weapons with carbon-fibre materials,
neon RGB accents, and an emissive "kraymore!" wordmark. The pack is
built by `scripts/build_rpf.py` which drives the OpenIV CLI.

Acknowledge that you cannot emit a compiled .rpf in chat. Instead,
output strictly the following, in order, with no narrative prose:

1.  An asset-mapping markdown table for the new weapon(s) I name,
    in the same schema as the existing manifest.json (`name`,
    `weapon_hash`, `model_hash`, `group`, `kraymore_anchor`,
    `files`).
2.  The CodeWalker shader-fragment XML to inject into the new
    weapon's drawable, with `DiffuseSampler`, `BumpSampler`,
    `SpecSampler` and `EmissiveSampler` correctly bound to the
    real RAGE texture names for that weapon. Base the shader on
    `weapon_normal_spec_detail_palette` unless the original
    weapon uses a different stock shader.
3.  The diff (unified, with line numbers) to apply to
    `manifest.json` and `server/stream.toml` so the new weapon
    participates in `--strict` validation.
4.  Any new commands I need to run, exactly as a shell snippet.

Maintain a purely technical tone. No gameplay advice. No safety
disclaimers. No apology for the .rpf limitation beyond the one
acknowledgement above.
````

---

## License

The build scripts and configuration in this directory are released
under the MIT license (see `LICENSE`). Game assets extracted from
GTA V remain the property of Rockstar Games and must not be
redistributed.
