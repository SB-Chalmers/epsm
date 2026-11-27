"""Build the EPSM icon pack. Python 3; PNG export requires rsvg-convert."""

from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parent
ICONS = json.loads((ROOT / "icons.json").read_text())
ATTRS = 'fill="none" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"'
FONT = 'font-family="Helvetica Neue, Helvetica, Arial, sans-serif"'


def glyph(icon, color="currentColor"):
    return f'<g {ATTRS} stroke="{color}">{icon["shapes"]}</g>'


def svg(icon, variant):
    name = icon["name"]
    if variant == "badges":
        body = (
            f'<rect width="64" height="64" rx="14" fill="{icon["color"]}"/>'
            f'<g transform="translate(12 12) scale(1.6666667)">{glyph(icon, "#FFFFFF")}</g>'
        )
        size = 64
    else:
        body = glyph(icon, icon["color"] if variant == "color" else "currentColor")
        size = 24
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img" aria-labelledby="title">'
        f'<title id="title">{name}: {escape(icon["metaphor"])}</title>{body}</svg>\n'
    )


def overview():
    body = [
        '<rect width="1600" height="1270" fill="#F6F5F0"/>',
        f'<g {FONT} fill="#233A43">',
        '<text x="80" y="73" font-size="14" letter-spacing="2.2">EPSM / REPOSITORY ICONS</text>',
        '<text x="80" y="158" font-size="62" font-weight="600" letter-spacing="-2">One family. Eleven identities.</text>',
        '<text x="82" y="205" font-size="22" fill="#647277">Simple geometry. Clear roles. Recognisable at a glance.</text>',
        '<text x="1520" y="73" text-anchor="end" font-size="14" fill="#647277">ICON PACK / 01</text>',
    ]
    for i, icon in enumerate(ICONS):
        x, y = 80 + (i % 4) * 360, 270 + (i // 4) * 240
        body.extend([
            f'<path d="M{x} {y}h336" stroke="#D6DCD7"/>',
            f'<g transform="translate({x + 2} {y + 26}) scale(1.1875)">',
            f'<rect width="64" height="64" rx="14" fill="{icon["color"]}"/>',
            f'<g transform="translate(12 12) scale(1.6666667)">{glyph(icon, "white")}</g></g>',
            f'<text x="{x + 2}" y="{y + 143}" font-size="23" font-weight="500">{icon["name"]}</text>',
            f'<text x="{x + 2}" y="{y + 177}" font-size="17" fill="#647277">{escape(icon["role"])}</text>',
            f'<g transform="translate({x + 297} {y + 52})">{glyph(icon, "#6B777C")}</g>',
        ])
    body.extend([
        '<path d="M1160 750h336" stroke="#D6DCD7"/>',
        '<text x="1162" y="800" font-size="13" letter-spacing="1.7" fill="#647277">A SHARED VISUAL LANGUAGE</text>',
        '<text x="1162" y="845" font-size="24" font-weight="500">24 × 24 grid</text>',
        '<text x="1162" y="879" font-size="18" fill="#647277">1.75-unit stroke · rounded ends</text>',
        '<text x="1162" y="912" font-size="18" fill="#647277">Colour + monochrome + badges</text>',
        '<text x="1162" y="945" font-size="18" fill="#647277">SVG masters · transparent PNGs</text>',
        '<path d="M80 1040h1440" stroke="#D6DCD7"/>',
        '<text x="82" y="1081" font-size="13" letter-spacing="1.6" fill="#647277">SHAPE FIRST / ALL ELEVEN AT 24 PX</text>',
    ])
    for i, icon in enumerate(ICONS):
        body.append(f'<g transform="translate({84 + i * 130} 1120)">{glyph(icon, "#233A43")}</g>')
    body.extend([
        '<text x="82" y="1210" font-size="15" fill="#647277">Ten epsm_* repositories, plus the EPSM platform. No letters inside the icons. No dependence on colour.</text>',
        '</g>',
    ])
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1270" viewBox="0 0 1600 1270">' + "".join(body) + '</svg>\n'


def gallery():
    cards = []
    for icon in ICONS:
        name = icon["name"]
        sizes = "".join(f'<img src="svg/mono/{name}.svg" width="{s}" height="{s}" alt="" title="{s}px">' for s in (16, 24, 32))
        cards.append(f'''<article>
          <div class="marks"><img src="svg/badges/{name}.svg" width="72" height="72" alt="{icon['metaphor']}"><div class="sizes">{sizes}</div></div>
          <h2>{name}</h2><p>{escape(icon['role'])}</p>
          <div class="links"><a download href="svg/color/{name}.svg">Colour SVG</a><a download href="svg/mono/{name}.svg">Mono SVG</a><a download href="svg/badges/{name}.svg">Badge SVG</a><a download href="png/badges/512/{name}.png">512 PNG</a></div>
        </article>''')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>EPSM icon pack</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5f0;color:#233a43;font-family:system-ui,-apple-system,sans-serif}main{max-width:1480px;margin:auto;padding:64px 40px}.eyebrow{font-size:12px;letter-spacing:.16em}h1{font-size:clamp(36px,5vw,64px);letter-spacing:-.045em;line-height:1.1;font-weight:600;margin:32px 0 20px}.intro{font-size:19px;color:#647277;max-width:780px;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:32px;margin-top:64px}article{border-top:1px solid #d6dcd7;padding:24px 0 28px}.marks{display:flex;align-items:center;justify-content:space-between;gap:12px}.sizes{display:flex;align-items:center;gap:12px}h2{font-size:20px;font-weight:600;letter-spacing:-.03em;margin:26px 0 10px}p{font-size:14px;color:#647277}.links{display:flex;flex-wrap:wrap;gap:12px;margin-top:24px}a{color:#3159b8;font-size:12px;text-underline-offset:4px}a:focus-visible{outline:2px solid #3159b8;outline-offset:4px}.inverse{background:#233a43;color:white;padding:28px;border-radius:14px}.inverse h2{margin:0 0 22px}.inverse .strip{display:flex;flex-wrap:wrap;gap:18px}.inverse img{filter:invert(1)}.inverse p{color:#bdcdcf;line-height:1.6}footer{border-top:1px solid #d6dcd7;margin-top:36px;padding-top:24px;color:#647277;font-size:13px;line-height:1.7}@media(max-width:1120px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.sizes{gap:6px}}@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:540px){main{padding:32px 24px}.grid{grid-template-columns:1fr;gap:12px;margin-top:36px}}
</style><main><div class="eyebrow">EPSM / REPOSITORY ICONS / 01</div><h1>One family. Eleven identities.</h1><p class="intro">Ten EPSM repositories, plus the platform. One consistent stroke, a clear symbol for each role, and colour as a secondary cue.</p><div class="grid">''' + "".join(cards) + '''<article class="inverse"><h2>Works in one colour.</h2><div class="strip">''' + "".join(f'<img src="svg/mono/{i["name"]}.svg" width="24" height="24" alt="{i["name"]}">' for i in ICONS) + '''</div><p>24-unit grid · 1.75-unit stroke<br>Rounded ends · transparent backgrounds<br>16, 24 and 32 px shown on each card.</p></article></div><footer>SVG masters in svg/ · PNG exports in png/ · SVG symbol sprite in sprite.svg<br>Monochrome SVGs use currentColor when inlined. Standalone files default to black.<br>Read README.md for usage and rebuilding. No network requests or external dependencies in this preview.</footer></main></html>'''


def build():
    converter = shutil.which("rsvg-convert")
    if not converter:
        raise SystemExit("PNG export requires rsvg-convert; install librsvg or use the committed exports.")
    for variant in ("color", "mono", "badges"):
        folder = ROOT / "svg" / variant
        folder.mkdir(parents=True, exist_ok=True)
        for icon in ICONS:
            source = folder / f'{icon["name"]}.svg'
            source.write_text(svg(icon, variant))
            sizes = (128, 512) if variant == "badges" else (16, 24, 32, 64, 128, 512)
            for size in sizes:
                target = ROOT / "png" / variant / str(size) / f'{icon["name"]}.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([converter, "-w", str(size), "-h", str(size), "-o", str(target), str(source)], check=True)
    symbols = "".join(f'<symbol id="{i["name"]}" viewBox="0 0 24 24">{glyph(i)}</symbol>' for i in ICONS)
    (ROOT / "sprite.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg">' + symbols + '</svg>\n')
    (ROOT / "overview.svg").write_text(overview())
    subprocess.run([converter, "-o", str(ROOT / "overview.png"), str(ROOT / "overview.svg")], check=True)
    (ROOT / "preview.html").write_text(gallery())
    manifest = [{k: v for k, v in i.items() if k != "shapes"} for i in ICONS]
    (ROOT / "manifest.json").write_text(json.dumps({"version": 1, "grid": 24, "stroke": 1.75, "icons": manifest}, indent=2) + "\n")
    archive = ROOT / "epsm-icon-pack.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and path != archive and "__pycache__" not in path.parts:
                bundle.write(path, Path("epsm-icon-pack") / path.relative_to(ROOT))
    print(f"Built {len(ICONS)} icons, 3 SVG variants, 154 PNGs, preview and ZIP in {ROOT}")


if __name__ == "__main__":
    build()
