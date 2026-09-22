# The run report: one page that tells each campaign end to end, from its two inputs to its pieces.
#   py tools/report.py   ->  runs/index.html
# Serve the repo root (py -m http.server 5190) and open http://localhost:5190/runs/
# Images on the page are cached thumbnails; the full file is fetched only when one is opened.
import datetime
import glob
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, 'runs')
THUMBS = os.path.join(RUNS, '_thumbs')
e = html.escape

STAGES = [
    ('1', 'Passes', 'Depth, normals, masks, a parts map and a studio reference per view and colorway, from any product.'),
    ('2', 'Plan', 'A campaign file lists the pieces: template or sampled layout, format, view, colorway, scene.'),
    ('3', 'Generate', 'A ComfyUI graph turns the passes into photoreal images, locally or through a paid model.'),
    ('3b', 'Consistency', 'Every part takes its spec colour and tone in every view; fine detail comes from the render.'),
    ('4', 'Route', 'Colour and parts are checked per photo: publish, review, or regenerate with a new seed.'),
    ('5', 'Layout', 'The brand on top: real type, colours and logo, in the poster, spread and spec-sheet templates.'),
    ('6', 'Report', 'This page: every input, photo, verdict and piece, campaign by campaign.'),
]


def thumb(path, side=420):
    """A small JPEG for the page, cached by modification time."""
    from PIL import Image
    src = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(src):
        return None
    key = f'{abs(hash(os.path.relpath(src, ROOT)))}-{int(os.path.getmtime(src))}-{side}.jpg'
    out = os.path.join(THUMBS, key)
    if not os.path.exists(out):
        os.makedirs(THUMBS, exist_ok=True)
        im = Image.open(src)
        if im.mode == 'RGBA':
            bg = Image.new('RGBA', im.size, (216, 216, 216, 255))
            bg.alpha_composite(im)
            im = bg
        im = im.convert('RGB')
        im.thumbnail((side, side))
        im.save(out, quality=82)
    return '_thumbs/' + key


def rel(path):
    """A path as the page refers to it: relative to runs/."""
    return os.path.relpath(os.path.join(ROOT, path), RUNS).replace(os.sep, '/')


def img(path, side=420, cls='', caption=None):
    t = thumb(path, side)
    if not t:
        return ''
    tag = f'<img class="{cls}" loading="lazy" src="{t}" data-full="{rel(path)}" alt="{e(caption or os.path.basename(path))}">'
    return f'<figure>{tag}<figcaption>{caption}</figcaption></figure>' if caption else tag


def when(path):
    p = os.path.join(ROOT, path)
    return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%d/%m %H:%M') if os.path.exists(p) else '—'


# ---------- the two inputs ----------
def swatch(color):
    return '#%02X%02X%02X' % tuple(round(max(0, min(1, v)) ** (1 / 2.2) * 255) for v in color['color'])


def product_card(product):
    spec = json.load(open(os.path.join(ROOT, product, 'product.json'), encoding='utf-8'))
    facts = ''.join(f'<li>{e(f)}</li>' for f in spec.get('facts', [])[:4])
    cws = ''
    for cw, mats in spec['colorways'].items():
        dots = ''.join(f'<i style="background:{swatch(v)}"></i>' for k, v in mats.items()
                       if 'color' in v and k in ('body', 'ab', 'bezel'))
        cws += f'<span class="cw"><span class="sw">{dots}</span>{e(cw)}</span>'
    return f'''<div class="card">
      <h4>Product <small>{e(product)}</small></h4>
      <model-viewer src="{rel(os.path.join(product, "product.glb"))}" camera-controls auto-rotate shadow-intensity="0.6"
        environment-image="neutral" alt="{e(spec["name"])}"></model-viewer>
      <dl><dt>Name</dt><dd>{e(spec["name"])}</dd><dt>Size</dt><dd>{" × ".join(str(v) for v in spec.get("size_mm", []))} mm</dd>
      <dt>Protected</dt><dd>{e(", ".join(spec.get("protected_materials", [])) or "none")}</dd></dl>
      <div class="cws">{cws}</div><ul class="facts">{facts}</ul></div>'''


def brand_card(brand):
    b = json.load(open(os.path.join(ROOT, brand, 'brand.json'), encoding='utf-8'))
    sw = ''.join(f'<span class="cw"><span class="sw"><i style="background:{v}"></i></span>{e(k)}</span>'
                 for k, v in b['colors'].items() if k in ('paper', 'stone', 'ink', 'signal'))
    refs, measured = '', ''
    if b.get('from_references'):
        folder = os.path.join(ROOT, b['from_references'])
        if os.path.isdir(folder):
            refs = '<div class="refs">' + ''.join(
                img(os.path.join(b['from_references'], f), 260, 'ref')
                for f in sorted(os.listdir(folder))[:4] if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))) + '</div>'
        m = b.get('measured', {})
        measured = (f'<p class="sub">light: {e(m.get("light", {}).get("words", ""))} · contrast '
                    f'{m.get("light", {}).get("contrast")} · air {m.get("composition", {}).get("air")} · '
                    f'headline {m.get("type", {}).get("weight")} {m.get("type", {}).get("case")}</p>')
    origin = 'read from a moodboard' if b.get('from_references') else 'written by hand'
    return f'''<div class="card">
      <h4>Brand <small>{e(brand)} · {origin}</small></h4>
      {refs}<div class="cws">{sw}</div>{measured}
      <p class="sub">{e(b.get("tone", ""))}</p></div>'''


# ---------- one campaign, end to end ----------
def campaign(path):
    plan = json.load(open(path, encoding='utf-8'))
    slug = os.path.basename(path)[:-5]
    pid = os.path.basename(plan['product'])
    gen_dir = os.path.join('runs', pid, 'generate', plan['backend'])
    layout_dir = os.path.join(RUNS, pid, 'layout', slug)
    pieces = sorted(glob.glob(os.path.join(layout_dir, '*.png')))
    if not pieces:
        return ''
    qa_path, cons_path = os.path.join(RUNS, pid, 'qa.json'), os.path.join(RUNS, pid, 'consistency.json')
    qa = json.load(open(qa_path)) if os.path.exists(qa_path) else {}
    cons = json.load(open(cons_path)) if os.path.exists(cons_path) else {}

    wanted = {(p['view'], p['colorway']) for p in plan['pieces']}
    wanted |= {(p['view2'], p['colorway']) for p in plan['pieces'] if p.get('view2')}
    photos = ''
    for view, cw in sorted(wanted):
        shots = [s for s in sorted(glob.glob(os.path.join(ROOT, gen_dir, f"{view}_{plan['scene']}_{cw}_s*.png")))
                 if not s.endswith('_raw.png')]
        if not shots:
            continue
        path_rel = os.path.relpath(shots[-1], ROOT).replace(os.sep, '/')
        v = qa.get(path_rel, {})
        badge = (f'<span class="verdict {v["verdict"]}">{v["verdict"]}</span>'
                 f'<small> colour ΔE {v["delta_e"]["colour"]} · parts {v["delta_e"]["parts"]}</small>') if v else ''
        photos += f'<figure>{img(path_rel, 320)}<figcaption>{e(view)} · {e(cw)}<br>{badge}</figcaption></figure>'

    drift = ' · '.join(f"{e(cw)} {r['worst_between_views']}" for cw, r in sorted(cons.items()))
    piece_figs = ''.join(img(os.path.relpath(p, ROOT).replace(os.sep, '/'), 520, 'piece', e(os.path.basename(p)[:-4]))
                         for p in pieces)
    templates = sorted({p['template'] for p in plan['pieces']})
    return f'''
<section class="campaign" id="{slug}">
  <header><h2>{e(plan.get("name", slug))}</h2>
    <span class="tag">{len(pieces)} pieces</span><span class="tag">{e(plan["backend"])}</span>
    <span class="tag">scene: {e(plan["scene"])}</span><span class="tag">{e(", ".join(templates))}</span>
    <span class="tag">{when(os.path.relpath(pieces[-1], ROOT))}</span></header>

  <h3>1 · Inputs <small>the product, and the look</small></h3>
  <div class="cards">{product_card(plan["product"])}{brand_card(plan["brand"])}</div>

  <h3>2 · Photos <small>generated from the passes of each view, then checked · drift between views: {drift or "—"}</small></h3>
  <div class="pieces small">{photos}</div>

  <h3>3 · Pieces <small>type, colour and logo set from the brand file</small></h3>
  <div class="pieces">{piece_figs}</div>
</section>'''


# ---------- appendix ----------
def passes_block(pid):
    man_path = os.path.join(RUNS, pid, 'passes', 'manifest.json')
    if not os.path.exists(man_path):
        return ''
    man = json.load(open(man_path))
    cols = [('depth', 'Depth'), ('normal', 'Normals'), ('mask', 'Mask'), ('mask_protected', 'Protected'), ('mask_parts', 'Parts')]
    head = ''.join(f'<th>{e(cw)}</th>' for cw in man['colorways']) + ''.join(f'<th>{e(t)}</th>' for _, t in cols)
    rows = ''
    for view in man['views']:
        cells = ''.join(f'<td class="beauty">{img(f"runs/{pid}/passes/{view}/beauty_{cw}.png", 220)}</td>'
                        for cw in man['colorways'])
        cells += ''.join(f'<td class="pass">{img(f"runs/{pid}/passes/{view}/{p}.png", 220)}</td>' for p, _ in cols)
        rows += f'<tr><th class="view">{e(view)}</th>{cells}</tr>'
    return (f'<details><summary>{e(pid)} · passes: {len(man["views"])} views, {when(f"runs/{pid}/passes/manifest.json")}</summary>'
            f'<div class="scroll"><table class="grid"><thead><tr><th></th>{head}</tr></thead><tbody>{rows}</tbody></table></div></details>')


def ledger_block():
    rows, total = '', 0.0
    for path in sorted(glob.glob(os.path.join(RUNS, '*', 'generate', 'ledger.jsonl'))):
        pid = os.path.basename(os.path.dirname(os.path.dirname(path)))
        by_backend = {}
        for line in open(path, encoding='utf-8'):
            if not line.strip():
                continue
            r = json.loads(line)
            b = by_backend.setdefault(r['backend'], {'n': 0, 'usd': 0.0, 'seconds': 0.0})
            b['n'] += 1
            b['usd'] += r['usd']
            b['seconds'] += r['seconds']
        for backend, b in sorted(by_backend.items()):
            total += b['usd']
            rows += (f'<tr><td>{e(pid)}</td><td>{e(backend)}</td><td>{b["n"]}</td>'
                     f'<td>{b["seconds"] / max(b["n"], 1):.0f} s</td><td>US$ {b["usd"]:.3f}</td></tr>')
    if not rows:
        return ''
    return (f'<details><summary>Images generated, time and cost: US$ {total:.2f} in total</summary>'
            f'<table class="grid qa"><thead><tr><th>Product</th><th>Backend</th><th>Images</th><th>Average</th>'
            f'<th>Cost</th></tr></thead><tbody>{rows}</tbody></table></details>')


campaigns = sorted(glob.glob(os.path.join(ROOT, 'campaigns', '*.json')))
sections = ''.join(campaign(c) for c in campaigns)
products = sorted(os.path.basename(os.path.dirname(os.path.dirname(p)))
                  for p in glob.glob(os.path.join(RUNS, '*', 'passes', 'manifest.json')))
nav = ''.join(f'<a href="#{os.path.basename(c)[:-5]}">{e(os.path.basename(c)[:-5])}</a>' for c in campaigns)
stages = ''.join(f'<li><b>{n}</b><span><strong>{e(t)}</strong>{e(d)}</span></li>' for n, t, d in STAGES)
page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>From CAD to Shelf · Run report</title>
<script type="module" src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
  :root {{ --bg: #f4f2ee; --ink: #1d2230; --soft: #6b7080; --line: #dcd8d0; --card: #fff; --accent: #d9542b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 1500px; margin: 0 auto; padding: 32px 20px 80px; }}
  h1 {{ font-size: clamp(28px, 4vw, 44px); letter-spacing: -0.03em; margin: 0; }}
  h2 {{ margin: 0; font-size: 26px; letter-spacing: -0.02em; }}
  h3 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .07em; color: var(--soft); margin: 30px 0 12px; }}
  h3 small, header small {{ text-transform: none; letter-spacing: 0; font-weight: 400; }}
  h4 {{ margin: 0 0 10px; font-size: 14px; }} h4 small {{ color: var(--soft); font-weight: 400; }}
  .sub {{ color: var(--soft); margin: 8px 0 0; font-size: 13px; }}
  nav a {{ margin-right: 14px; color: var(--accent); font-weight: 600; }}
  .stages {{ list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin: 20px 0 36px; }}
  .stages li {{ display: flex; gap: 10px; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px; }}
  .stages b {{ flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; background: #7bb58a; color: #fff; font-size: 12px; }}
  .stages span {{ font-size: 12.5px; color: var(--soft); }} .stages strong {{ display: block; color: var(--ink); font-size: 14px; }}
  .campaign {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 24px; margin-bottom: 30px; }}
  .campaign header {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .tag {{ font-size: 12px; background: var(--bg); border-radius: 99px; padding: 3px 10px; color: var(--soft); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }}
  .card {{ border: 1px solid var(--line); border-radius: 12px; padding: 16px; }}
  model-viewer {{ width: 100%; height: 240px; background: #ebe8e2; border-radius: 10px; margin-bottom: 12px; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px; margin: 0 0 10px; font-size: 13px; }}
  dt {{ color: var(--soft); }} dd {{ margin: 0; }}
  .cws {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .cw {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 99px; padding: 3px 12px 3px 6px; font-size: 13px; }}
  .sw {{ display: inline-flex; }} .sw i {{ width: 13px; height: 13px; border-radius: 50%; border: 1px solid rgba(0,0,0,.12); margin-right: -3px; }}
  .facts {{ margin: 10px 0 0; padding-left: 18px; font-size: 13px; color: var(--soft); }}
  .refs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
  .refs img {{ height: 110px; border-radius: 8px; border: 1px solid var(--line); cursor: zoom-in; }}
  .pieces {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }}
  .pieces figure {{ margin: 0; max-width: 270px; }}
  .pieces img {{ max-height: 300px; max-width: 270px; width: auto; height: auto; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,.08); cursor: zoom-in; display: block; background: #eee; }}
  .pieces.small img {{ max-height: 190px; }}
  .pieces figcaption {{ font-size: 12px; color: var(--soft); margin-top: 6px; }}
  .verdict {{ padding: 2px 9px; border-radius: 99px; font-weight: 600; font-size: 11px; }}
  .verdict.publish {{ background: #dff0e2; color: #2d6a3b; }} .verdict.review {{ background: #fdf0d5; color: #8a5a00; }}
  .verdict.regenerate {{ background: #fbe0da; color: #9b2c16; }}
  details {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 18px; margin-bottom: 14px; }}
  summary {{ cursor: pointer; font-weight: 600; }}
  .scroll {{ overflow-x: auto; }}
  .grid {{ border-collapse: separate; border-spacing: 6px; margin-top: 12px; }}
  .grid th {{ font-size: 12px; color: var(--soft); font-weight: 600; }} .grid th.view {{ text-align: left; }}
  .grid img {{ width: 130px; height: 130px; object-fit: contain; border-radius: 6px; cursor: zoom-in; display: block; }}
  .grid td.pass img {{ background: #000; }} .grid td.beauty img {{ background: #e6e3dd; }}
  .grid.qa td {{ text-align: center; font-size: 13px; }}
  #box {{ position: fixed; inset: 0; background: rgba(20,22,30,.9); display: none; place-items: center; z-index: 9; cursor: zoom-out; }}
  #box.on {{ display: grid; }} #box img {{ max-width: 94vw; max-height: 90vh; background: #e6e3dd; border-radius: 10px; }}
  #box p {{ position: fixed; bottom: 14px; left: 0; right: 0; text-align: center; color: #fff; margin: 0; }}
</style></head>
<body><main>
  <h1>From CAD to Shelf</h1>
  <p class="sub">Run report · generated {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} · {len(campaigns)} campaigns · {len(products)} products</p>
  <nav>{nav}</nav>
  <ol class="stages">{stages}</ol>
  {sections}
  <h3>Appendix <small>the technical passes, and what was generated</small></h3>
  {''.join(passes_block(p) for p in products)}
  {ledger_block()}
</main>
<div id="box"><img alt=""><p></p></div>
<script>
  const box = document.querySelector('#box');
  document.addEventListener('click', (ev) => {{
    const img = ev.target.closest('.pieces img, .grid img, .refs img');
    if (img) {{ box.querySelector('img').src = img.dataset.full || img.src; box.querySelector('p').textContent = img.alt; box.classList.add('on'); }}
    else if (ev.target.closest('#box')) box.classList.remove('on');
  }});
  addEventListener('keydown', (ev) => {{ if (ev.key === 'Escape') box.classList.remove('on'); }});
</script>
</body></html>'''
os.makedirs(RUNS, exist_ok=True)
open(os.path.join(RUNS, 'index.html'), 'w', encoding='utf-8').write(page)
print(os.path.join(RUNS, 'index.html'))
