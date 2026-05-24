# Emissive workflow — "kraymore!" branding

The branding is **not** a flat decal in the diffuse map. It is rendered
through GTA V's emissive shader slot so that the lettering keeps its
intensity at night, inside tunnels, and through any tinted scope.

## Authoring pipeline

1.  **Bake the diffuse** in your usual texture editor (Photoshop /
    Substance / Krita). Keep the lettering area neutral grey — no
    colour, no glow — because the diffuse will only be visible where
    the emissive mask is **not** lit.

2.  **Author the emissive mask** at the same resolution as the diffuse
    (typically 1024×1024 for primary weapons, 512×512 for sidearms).
    Rules:

    -   Background must be **pure black** (`#000000`). Any non-zero
        pixel value will leak light onto the model when the emissive
        multiplier is high.
    -   The `kraymore!` lettering itself should be a saturated neon —
        magenta (`#FF1FB8`) and toxic-green (`#5BFF00`) work best
        against carbon-fibre.
    -   Anti-alias the lettering edges normally; the emissive shader
        will gamma-correct them.

3.  **Export both maps** as `.dds` (BC1 for the diffuse, BC3 for the
    emissive — alpha is unused but BC3 preserves the gradient better
    than BC1 in dark areas).

4.  **Pack into the weapon's `.ytd`** with OpenIV's Texture Toolkit
    *or* by re-importing the modified `.ydr.xml` with CodeWalker:

    -   Replace the existing diffuse texture entry.
    -   Add a new texture entry named exactly `kraymore_emissive`.

5.  **Bind the emissive to the shader** by injecting
    `kraymore_emissive.ytd.xml` (from this directory) into the weapon's
    ShaderGroup items. Update the diffuse / normal / specular texture
    names at the top of the file to match the weapon you are editing
    (the shipped sample is wired up for `w_pi_heavypistol`).

6.  **Verify in-engine** with OpenIV's Model Viewer before re-packing
    into `dlc.rpf`. The lettering should be visible in the viewer's
    "Night" lighting preset.

## Shader choice cheat-sheet

| Base weapon material              | Use shader                                  |
|-----------------------------------|---------------------------------------------|
| Stock weapon (most pistols/SMGs)  | `weapon_normal_spec_detail_palette`         |
| Weapon without detail map         | `weapon_normal_spec`                        |
| Weapon already using emissive     | keep the existing shader, add Emissive slot |

If the original shader has no `EmissiveSampler` parameter, switch the
material to `weapon_emissivestrong` — it is functionally identical to
the stock weapon shader but with a dedicated emissive path that does
not interact with the detail palette UVs.

## Why we never edit `weapons.meta`

It is tempting to also bump the muzzle flash or tracer colour in
`weapons.meta`, but that file controls **gameplay** parameters
(damage, recoil, spread). Shipping a customised `weapons.meta` will
overwrite the server's combat balance and is a guaranteed way to get
the pack rejected by any reputable RP server admin. Restrict the
gunpack to texture, model and particle (`.ypt`) overrides.
