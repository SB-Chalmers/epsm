# EPSM / The section identity

An **E drawn as a building section** is the EPSM signature. A vertical spine and
three floorplates stay fixed across the family. Geometry on the right expresses
each repository's role. The platform mark completes the three floorplates.

This direction connects the initial of EPSM to the physical building at the
centre of the platform. Shared geometry and one palette carry the identity.
The individual marks combine the section with a solid cell (Core), construction
layers (Data), stored records (DB), energy (RC), a leaf (LCA), branching paths
(Workflows), comparative bars (Studies), construction brackets (Development),
a workspace (Studio), and an inspection aperture (Viewer).

## Review and download

- Open `preview.html` for the gallery, individual downloads, and 16/24/32 px samples.
- `overview.png` and `overview.svg` show the platform mark and all ten repo marks.
- `epsm-icon-pack-v2.zip` contains the complete pack.
- The previous direction remains in `../icons/` for comparison.

## Assets

| Location | Use |
| --- | --- |
| `svg/color/` | Two green tones, transparent background, 32 × 32 viewBox |
| `svg/mono/` | Single colour via `currentColor`, transparent background |
| `svg/badges/` | Deep green tiles, warm white section, mint role geometry |
| `png/color/`, `png/mono/` | RGBA PNGs at 16, 24, 32, 64, 128, 512 px |
| `png/badges/` | Rounded badges at 128 and 512 px |
| `sprite.svg` | Monochrome symbols with repository names as IDs |
| `icons.json` | Editable repository geometry |
| `manifest.json` | Palette, grid, and identity metadata |

## Geometry and colour

The shared E is on a 32-unit grid: a 4-unit spine, three 4-unit floorplates,
and 6-unit spaces between floors. Role geometry uses solids and 2.5–3-unit
structural strokes. The grid leaves room for optical adjustments. Keep these
proportions and the section unchanged when making new marks.

- Deep green `#184A48`: the shared building section and badge backgrounds.
- Green `#27826E`: adjoining geometry on light surfaces.
- Mint `#83D8BC`: adjoining geometry on dark badges.
- Warm white `#F5F3ED`: light backgrounds and the section on badges.

Use colour marks on light backgrounds and badges or white monochrome marks
on dark backgrounds. Keep 4 units of clear space outside a standalone mark.
Use 32 px or larger where practical; the complex role shapes are less distinct
at 16 px. Use visible repository labels when the audience is learning the family.
The new compound marks occupy a 32-unit grid rather than v1's 24-unit grid.

## Use

```html
<img src="assets/icons-v2/svg/badges/epsm_core.svg"
     width="48" height="48" alt="EPSM Core">
```

Or use the SVG sprite from the same web origin:

```html
<svg width="32" height="32" role="img" aria-label="EPSM Core"
     style="color: #184A48">
  <use href="/assets/icons-v2/sprite.svg#epsm_core"></use>
</svg>
```

Inline monochrome SVGs inherit CSS `color`; SVGs loaded with `<img>` do not.
Decorative images beside visible labels should have `alt=""`; decorative inline
SVGs should use `aria-hidden="true"`.

## Rebuild

Run `python3 assets/icons-v2/build.py` from the EPSM repository root.
Python 3 and `rsvg-convert` from librsvg are required. It regenerates the source
exports, PNGs, gallery, overview, sprite, manifest and ZIP. The shared section
is defined in `build.py`; repository geometry is in `icons.json`.

Original artwork, distributed under the included MIT LICENSE.
