# EPSM icon pack

Ten `epsm_*` repository icons and a companion `epsm` platform icon. Each uses a
distinct, role-based symbol. Colour adds identity; shape carries the meaning.

Open [preview.html](preview.html) for the gallery, actual-size 16/24/32 px samples,
dark-background examples and individual downloads. [overview.png](overview.png)
is the complete contact sheet. [epsm-icon-pack.zip](epsm-icon-pack.zip) contains
the source, exports and documentation.

| Repository | Symbol | Colour |
| --- | --- | --- |
| epsm_core | Cube — physical model | `#3159B8` |
| epsm_data | Layers — materials and constructions | `#167B80` |
| epsm_db | Cylinder — stored evidence | `#4C6190` |
| epsm_rc | Resistor + capacitor — thermal network | `#B75527` |
| epsm_lca | Leaf — climate impact | `#377650` |
| epsm_workflows | Branching graph — execution paths | `#6C4EAD` |
| epsm_studies | Report + chart — research | `#A04466` |
| epsm_development | Code brackets — engineering | `#646750` |
| epsm_studio | Application window — workspace | `#227E9D` |
| epsm_viewer | Eye — display and inspection | `#8459AA` |
| epsm | Building — integrated platform | `#273C4C` |

## Files

- `svg/color/`: coloured strokes on a transparent background, 24 × 24 viewBox.
- `svg/mono/`: `currentColor` strokes, transparent background, same geometry.
- `svg/badges/`: white symbols on coloured rounded tiles, 64 × 64 viewBox.
- `png/color/` and `png/mono/`: transparent exports at 16, 24, 32, 64, 128 and 512 px.
- `png/badges/`: rounded tiles at 128 and 512 px, transparent outer corners.
- `sprite.svg`: monochrome SVG symbols with repository names as IDs.
- `icons.json`: editable geometry and colour source; `manifest.json`: identity metadata.

Use badges for repo avatars and larger identities, and transparent symbols for
navigation, diagrams and documentation. Files are named after each repository.
The separate `smhi2epw` project is outside this pack's `epsm_*` scope.

## Visual rules

All symbols use a 24-unit grid, 1.75-unit strokes, round ends and round joins.
Drawings use the central 20 units with small optical adjustments for wider forms.
Do not stretch, add gradients or combine a second symbol with a glyph. Prefer
24 px or larger for UI; 16 px exports are included for compact contexts.
Keep at least 4 grid units of clear space around a standalone icon. Badge
geometry includes its own clear space. On dark surfaces use monochrome white
or the coloured badges, since the coloured strokes are designed for light surfaces.
Labels should accompany unfamiliar icons; colours are not status indicators.

## Usage

Repository documentation:

```html
<img src="assets/icons/svg/badges/epsm_core.svg" width="48" height="48" alt="EPSM Core">
```

External SVG sprite (served from the same origin):

```html
<svg width="24" height="24" role="img" aria-label="EPSM Core" style="color: #3159B8">
  <use href="/assets/icons/sprite.svg#epsm_core"></use>
</svg>
```

Inline monochrome SVGs inherit CSS `color`. SVGs used through `<img>` do not
inherit the parent colour; use the coloured exports, badges or the sprite.
For decorative icons next to visible text, use `alt=""` on images or
`aria-hidden="true"` on inline SVGs.

## Rebuild

Run `python3 assets/icons/build.py` from the EPSM repository root. Python 3 and
the `rsvg-convert` command from librsvg are required. The generator writes the
SVGs, raster exports, previews, manifest and ZIP from `icons.json`.

The icon artwork is original to this pack and distributed under the repository's
[MIT license](../../LICENSE). An included LICENSE also travels with the ZIP.
