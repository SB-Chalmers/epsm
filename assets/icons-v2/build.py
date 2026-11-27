"""Rebuild the EPSM section identity. Requires Python 3 and rsvg-convert."""
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
ICONS = json.loads((ROOT / 'icons.json').read_text())
INK = '#184A48'
ACCENT = '#27826E'
MINT = '#83D8BC'
PAPER = '#F5F3ED'
SHARED = '<path d="M3 4h9v4H7v6h5v4H7v6h5v4H3Z"/>'
FONT = 'font-family="Helvetica Neue, Helvetica, Arial, sans-serif"'


def glyph(icon, color='currentColor', accent=None):
    accent = accent or color
    return f'<g fill="{color}" color="{color}">{SHARED}</g><g fill="{accent}" color="{accent}">{icon["shapes"]}</g>'


def badge(icon, size=64):
    return f'<g transform="scale({size / 64})"><rect width="64" height="64" rx="12" fill="{INK}"/><g transform="translate(10 10) scale(1.375)">{glyph(icon, PAPER, MINT)}</g></g>'


def svg(icon, variant):
    size = 64 if variant == 'badges' else 32
    body = badge(icon) if variant == 'badges' else glyph(icon, INK, ACCENT) if variant == 'color' else glyph(icon)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-labelledby="title"><title id="title">{icon["name"]}: {escape(icon["metaphor"])}</title>{body}</svg>\n'


def text(x, y, value, size=18, color=INK, weight=400, extra=''):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" {extra}>{escape(value)}</text>'


def overview():
    b = [f'<rect width="1600" height="1370" fill="{PAPER}"/>', f'<g {FONT}>']
    b += [text(80, 64, 'EPSM / THE SECTION IDENTITY', 13, extra='letter-spacing="2"'), text(1520, 64, '02', 13, extra='text-anchor="end"')]
    b += [f'<rect x="80" y="103" width="1440" height="330" rx="4" fill="{INK}"/>', f'<g transform="translate(132 154) scale(6.4)">{glyph(ICONS[0], PAPER, MINT)}</g>']
    b += [text(405, 264, 'epsm', 123, PAPER, 600, 'letter-spacing="-6"'), text(411, 321, 'Energy Performance Simulation Manager', 23, '#C6DCD4')]
    b += [text(1000, 188, 'THE BUILDING IS THE BRAND.', 13, MINT, extra='letter-spacing="1.4"'), text(1000, 234, 'An E, drawn as a building section.', 22, PAPER), text(1000, 272, 'Three floorplates. One shared spine.', 20, '#C6DCD4'), text(1000, 310, 'Every repository starts here.', 20, '#C6DCD4')]
    b += [text(80, 492, 'ONE SECTION. TEN EXPRESSIONS.', 13, extra='letter-spacing="1.7"'), text(1520, 492, 'Shared geometry / shared palette', 14, '#5A746C', extra='text-anchor="end"')]
    for i, icon in enumerate(ICONS[1:]):
        x, y = 80 + i % 5 * 292, 532 + i // 5 * 260
        b += [f'<path d="M{x} {y}h264" stroke="#CED7CF"/>', f'<g transform="translate({x} {y+24})">{badge(icon, 84)}</g>', f'<g transform="translate({x+216} {y+48})">{glyph(icon, INK)}</g>']
        b += [text(x, y+151, icon['name'], 21, weight=500), text(x, y+184, icon['role'], 15, '#5A746C')]
    b += [f'<path d="M80 1085h1440" stroke="#CED7CF"/>', text(80, 1125, 'THE FAMILY IN ONE COLOUR / 32 PX', 12, '#5A746C', extra='letter-spacing="1.5"')]
    for i, icon in enumerate(ICONS):
        b += [f'<g transform="translate({80+i*132} 1161)">{glyph(icon, INK)}</g>']
    b += [text(80, 1256, 'The E-section remains constant. The adjoining geometry describes what each repository does.', 20), text(80, 1300, '32-unit grid · two shared greens · solid construction · SVG + PNG · colour and monochrome', 15, '#5A746C'), '</g>']
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1370" viewBox="0 0 1600 1370">'+''.join(b)+'</svg>\n'


def gallery():
    cards = []
    for i in ICONS:
        n = i['name']
        sizes = ''.join(f'<img src="svg/mono/{n}.svg" width="{s}" height="{s}" alt="" title="{s} px">' for s in (16,24,32))
        cards.append(f'<article><div class="marks"><img src="svg/badges/{n}.svg" width="80" height="80" alt="{i["metaphor"]}"><div class="sizes">{sizes}</div></div><h2>{n}</h2><p>{escape(i["role"])}</p><nav aria-label="{n} downloads"><a download href="svg/color/{n}.svg">Colour SVG</a><a download href="svg/mono/{n}.svg">Mono SVG</a><a download href="svg/badges/{n}.svg">Badge SVG</a><a download href="png/badges/512/{n}.png">512 PNG</a></nav></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EPSM / Section identity</title><style>
*{box-sizing:border-box}body{margin:0;background:#F5F3ED;color:#184A48;font-family:system-ui,-apple-system,sans-serif}main{max-width:1480px;margin:auto;padding:48px 40px}.eyebrow{font-size:12px;letter-spacing:.16em}.hero{background:#184A48;color:#F5F3ED;padding:40px;display:flex;align-items:center;gap:32px;margin-top:32px}.hero h1{font-size:clamp(48px,7vw,100px);line-height:1;letter-spacing:-.06em;margin:0 0 20px}.hero p{color:#C6DCD4;font-size:18px;line-height:1.7;max-width:760px}.hero img{width:160px;height:160px}.intro{margin:36px 0;color:#5A746C;line-height:1.7}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:28px}.marks{display:flex;justify-content:space-between;align-items:center}.sizes{display:flex;gap:10px;align-items:center}article{border-top:1px solid #CED7CF;padding:24px 0 32px}h2{font-size:20px;margin:28px 0 10px;font-weight:600;letter-spacing:-.03em}article p{font-size:14px;color:#5A746C}nav{display:flex;flex-wrap:wrap;gap:12px;margin-top:24px}a{font-size:12px;color:#184A48;text-underline-offset:4px}a:focus-visible{outline:2px solid #27826E;outline-offset:4px}.dark{background:#184A48;color:#F5F3ED;padding:24px}.dark h2{margin-top:0}.dark p{color:#C6DCD4;line-height:1.7}.dark img{filter:invert(1)}.strip{display:flex;flex-wrap:wrap;gap:16px}footer{border-top:1px solid #CED7CF;padding-top:24px;color:#5A746C;font-size:13px;line-height:1.7}@media(max-width:1150px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.sizes{gap:6px}}@media(max-width:870px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{padding:28px;gap:16px}.hero img{width:100px;height:100px}}@media(max-width:580px){main{padding:24px}.grid{grid-template-columns:1fr}.hero{align-items:flex-start;flex-direction:column}.hero img{width:80px;height:80px}}
</style><main><div class="eyebrow">EPSM / THE SECTION IDENTITY / 02</div><header class="hero"><img src="svg/badges/epsm.svg" alt="EPSM section mark"><div><h1>epsm</h1><p>Energy Performance Simulation Manager<br>An E, drawn as a building section. Three floorplates and a shared spine form the signature of every repository.</p></div></header><p class="intro">One building section. Ten expressions. The adjoining geometry gives each repository its role within the EPSM family.</p><div class="grid">'''+''.join(cards)+'''<article class="dark"><h2>The same family in white.</h2><div class="strip">'''+''.join(f'<img src="svg/mono/{i["name"]}.svg" width="32" height="32" alt="{i["name"]}">' for i in ICONS)+'''</div><p>Shared section, solid geometry.<br>32-unit grid. Two greens.<br>16, 24 and 32 px shown on each card.</p></article></div><footer>SVG masters, transparent PNGs, symbol sprite and source geometry are included.<br>Monochrome SVGs inherit currentColor when inlined. Read README.md for use and rebuilding.</footer></main></html>'''


def build():
    converter = shutil.which('rsvg-convert')
    if not converter:
        raise SystemExit('Rebuilding PNGs requires rsvg-convert from librsvg.')
    for variant in ('color','mono','badges'):
        dest = ROOT/'svg'/variant
        dest.mkdir(parents=True, exist_ok=True)
        for icon in ICONS:
            source = dest/f'{icon["name"]}.svg'
            source.write_text(svg(icon,variant))
            for size in ((128,512) if variant=='badges' else (16,24,32,64,128,512)):
                target=ROOT/'png'/variant/str(size)/f'{icon["name"]}.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([converter,'-w',str(size),'-h',str(size),'-o',str(target),str(source)],check=True)
    (ROOT/'sprite.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg">'+''.join(f'<symbol id="{i["name"]}" viewBox="0 0 32 32">{glyph(i)}</symbol>' for i in ICONS)+'</svg>\n')
    (ROOT/'overview.svg').write_text(overview())
    subprocess.run([converter,'-o',str(ROOT/'overview.png'),str(ROOT/'overview.svg')],check=True)
    (ROOT/'preview.html').write_text(gallery())
    manifest={'version':2,'grid':32,'palette':{'ink':INK,'accent':ACCENT,'mint':MINT,'paper':PAPER},'icons':[{k:v for k,v in i.items() if k!='shapes'} for i in ICONS]}
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=ROOT/'epsm-icon-pack-v2.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob('*')):
            if p.is_file() and p!=archive and '__pycache__' not in p.parts:
                z.write(p,Path('epsm-icon-pack-v2')/p.relative_to(ROOT))
    print(f'Built {len(ICONS)} identities in {ROOT}')


if __name__=='__main__':
    build()
