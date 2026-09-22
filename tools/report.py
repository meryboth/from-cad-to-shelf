# A local report of everything the pipeline has produced: py tools/report.py  ->  runs/index.html
# Serve the repo root (py -m http.server 5190) and open http://localhost:5190/runs/
import datetime
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, 'runs')
STAGES = [
    ('1', 'Passes', 'Depth, normals, masks and a studio reference per view and colorway, from any product.'),
    ('2', 'Plan', 'Jev picks scenes, moods and formats from the brief, each with a probability.'),
    ('3', 'Generate', 'A ComfyUI graph turns the passes and the plan into photoreal images.'),
    ('4', 'Layout', 'The brand on top: real type, colours and logo, per template and format.'),
    ('5', 'Route', 'Jev decides per piece: publish, human review or regenerate, by confidence.'),
    ('6', 'Copy', 'Text from the spec sheet only, so it cannot invent a fact.'),
    ('7', 'Report', 'Cost per approved asset, calibration, latency.'),
]
PASSES = [('depth', 'Depth'), ('normal', 'Normals'), ('mask', 'Mask'), ('mask_protected', 'Protected parts')]
e = html.escape


def rgb(c):
    return 'rgb(%d,%d,%d)' % tuple(round(max(0, min(1, v)) ** (1 / 2.2) * 255) for v in c)  # linear -> screen


def layouts(pid):
    d = os.path.join(RUNS, pid, 'layout')
    files = sorted(f for f in os.listdir(d) if f.endswith('.png')) if os.path.isdir(d) else []
    if not files:
        return ''
    figs = ''.join(f'<figure><img class="piece" loading="lazy" src="{pid}/layout/{f}" alt="{e(f[:-4])}"><figcaption>{e(f[:-4])}</figcaption></figure>' for f in files)
    return f'<h3>Stage 4 · Layout <small>prototype: the product image is still the studio reference, until ComfyUI renders it</small></h3><div class="pieces">{figs}</div>'


def product_section(pid):
    spec = json.load(open(os.path.join(ROOT, 'products', pid, 'product.json'), encoding='utf-8'))
    run = os.path.join(RUNS, pid, 'passes')
    man_path = os.path.join(run, 'manifest.json')
    man = json.load(open(man_path)) if os.path.exists(man_path) else None
    when = datetime.datetime.fromtimestamp(os.path.getmtime(man_path)).strftime('%d/%m %H:%M') if man else '—'
    chips = ''
    for cw, mats in spec['colorways'].items():
        sw = ''.join(f'<i style="background:{rgb(p["color"])}" title="{e(m)}"></i>' for m, p in mats.items() if 'color' in p)
        chips += f'<span class="cw"><span class="sw">{sw}</span>{e(cw)}</span>'
    facts = ''.join(f'<li>{e(f)}</li>' for f in spec.get('facts', []))
    size = spec.get('size_mm')
    meta = [('Category', spec.get('category', '—')), ('Real size', ' × '.join(str(v) for v in size) + ' mm' if size else '—'),
            ('Protected materials', ', '.join(spec.get('protected_materials', [])) or 'none'),
            ('Source', spec.get('source', 'built for this project')), ('Last passes run', when)]
    rows = ''
    if man:
        cws = [cw for cw in man['colorways'] if os.path.exists(os.path.join(run, next(iter(man['views'])), f'beauty_{cw}.png'))]
        head = ''.join(f'<th>{e(cw)}</th>' for cw in cws) + ''.join(f'<th class="pass">{e(t)}</th>' for _, t in PASSES)
        for view, v in man['views'].items():
            cells = ''.join(f'<td class="beauty"><img loading="lazy" src="{pid}/passes/{view}/beauty_{cw}.png" alt="{e(view)} {e(cw)}"></td>' for cw in cws)
            cells += ''.join(f'<td class="pass"><img loading="lazy" src="{pid}/passes/{view}/{p}.png" alt="{e(view)} {e(t)}"></td>' for p, t in PASSES)
            rows += f'<tr><th class="view">{e(view)}<small>az {v["azimuth"]}° · el {v["elevation"]}°</small></th>{cells}</tr>'
        grid = f'<div class="scroll"><table class="grid"><thead><tr><th></th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
    else:
        grid = '<p class="empty">No passes yet. Run <code>blender -b -P pipeline/passes.py -- products/%s runs/%s/passes</code></p>' % (pid, pid)
    return f'''
<section class="product" id="{pid}">
  <header><h2>{e(spec.get("name", pid))}</h2>{'<span class="tag">fictional</span>' if spec.get('fictional') else ''}</header>
  <div class="intro">
    <model-viewer src="../products/{pid}/product.glb" camera-controls auto-rotate shadow-intensity="0.6" exposure="1"
      environment-image="neutral" alt="{e(spec.get("name", pid))}, the input model"></model-viewer>
    <div>
      <h3>Input</h3>
      <dl>{''.join(f'<dt>{e(k)}</dt><dd>{e(str(v))}</dd>' for k, v in meta)}</dl>
      <h3>Colorways</h3><div class="cws">{chips}</div>
      <h3>Facts for the copy</h3><ul class="facts">{facts}</ul>
    </div>
  </div>
  <h3>Stage 1 · Passes <small>click any image to enlarge</small></h3>
  {grid}
  {layouts(pid)}
</section>'''


products = [p for p in os.listdir(os.path.join(ROOT, 'products')) if os.path.exists(os.path.join(ROOT, 'products', p, 'product.json'))]
# our own products first, then third-party ones
products.sort(key=lambda p: ('source' in json.load(open(os.path.join(ROOT, 'products', p, 'product.json'), encoding='utf-8')), p))
done = {'1': any(os.path.exists(os.path.join(RUNS, p, 'passes', 'manifest.json')) for p in products)}
# layout counts as started, not done, until it runs on generated images
stages = ''.join(f'<li class="{"done" if done.get(n) else ""}"><b>{n}</b><span><strong>{e(t)}</strong>{e(d)}</span></li>' for n, t, d in STAGES)
nav = ''.join(f'<a href="#{p}">{e(p)}</a>' for p in products)
page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>From CAD to Shelf · Run report</title>
<script type="module" src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
  :root {{ --bg: #f4f2ee; --ink: #1d2230; --soft: #6b7080; --line: #dcd8d0; --card: #fff; --accent: #d9542b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 1400px; margin: 0 auto; padding: 32px 20px 80px; }}
  h1 {{ font-size: clamp(28px, 4vw, 44px); letter-spacing: -0.03em; margin: 0; }}
  .sub {{ color: var(--soft); margin: 6px 0 24px; }}
  nav a {{ margin-right: 14px; color: var(--accent); font-weight: 600; }}
  .stages {{ list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0 40px; }}
  .stages li {{ display: flex; gap: 10px; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px; opacity: .55; }}
  .stages li.done {{ opacity: 1; border-color: #7bb58a; }}
  .stages b {{ flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; background: var(--line); font-size: 13px; }}
  .stages li.done b {{ background: #7bb58a; color: #fff; }}
  .stages span {{ font-size: 13px; color: var(--soft); }} .stages strong {{ display: block; color: var(--ink); }}
  .product {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 22px; margin-bottom: 32px; }}
  .product header {{ display: flex; align-items: center; gap: 10px; }} .product h2 {{ margin: 0; font-size: 28px; }}
  .tag {{ font-size: 12px; background: var(--bg); border-radius: 99px; padding: 2px 10px; color: var(--soft); }}
  h3 {{ font-size: 14px; text-transform: uppercase; letter-spacing: .06em; color: var(--soft); margin: 22px 0 10px; }} h3 small {{ text-transform: none; letter-spacing: 0; font-weight: 400; }}
  .intro {{ display: grid; grid-template-columns: minmax(260px, 420px) 1fr; gap: 24px; margin-top: 12px; }}
  model-viewer {{ width: 100%; height: 380px; background: #ebe8e2; border-radius: 12px; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }} dt {{ color: var(--soft); }} dd {{ margin: 0; }}
  .cws {{ display: flex; flex-wrap: wrap; gap: 8px; }} .cw {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 99px; padding: 4px 12px 4px 6px; }}
  .sw {{ display: inline-flex; }} .sw i {{ width: 14px; height: 14px; border-radius: 50%; border: 1px solid rgba(0,0,0,.12); margin-right: -4px; }}
  .facts {{ margin: 0; padding-left: 18px; }}
  .scroll {{ overflow-x: auto; }}
  .grid {{ border-collapse: separate; border-spacing: 6px; }} .grid th {{ font-size: 12px; color: var(--soft); font-weight: 600; text-align: center; }}
  .grid th.view {{ text-align: left; white-space: nowrap; color: var(--ink); }} .grid th.view small {{ display: block; color: var(--soft); font-weight: 400; }}
  .grid img {{ width: 150px; height: 150px; object-fit: contain; border-radius: 8px; cursor: zoom-in; display: block; }}
  .grid td.beauty img {{ background: #e6e3dd; }} .grid td.pass img {{ background: #000; }}
  .empty {{ color: var(--soft); }}
  .pieces {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }} .pieces figure {{ margin: 0; }}
  .pieces img {{ height: 300px; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,.08); cursor: zoom-in; display: block; }}
  .pieces figcaption {{ font-size: 12px; color: var(--soft); margin-top: 6px; }}
  #box {{ position: fixed; inset: 0; background: rgba(20,22,30,.88); display: none; place-items: center; z-index: 9; cursor: zoom-out; }}
  #box.on {{ display: grid; }} #box img {{ max-width: 94vw; max-height: 90vh; background: #e6e3dd; border-radius: 10px; }}
  #box p {{ position: fixed; bottom: 14px; left: 0; right: 0; text-align: center; color: #fff; margin: 0; }}
  @media (max-width: 760px) {{ .intro {{ grid-template-columns: 1fr; }} }}
</style></head>
<body><main>
  <h1>From CAD to Shelf</h1>
  <p class="sub">Run report · generated {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} · {len(products)} products</p>
  <nav>{nav}</nav>
  <ol class="stages">{stages}</ol>
  {''.join(product_section(p) for p in products)}
</main>
<div id="box"><img alt=""><p></p></div>
<script>
  const box = document.querySelector('#box');
  document.addEventListener('click', (ev) => {{
    const img = ev.target.closest('.grid img, .pieces img');
    if (img) {{ box.querySelector('img').src = img.src; box.querySelector('p').textContent = img.alt; box.classList.add('on'); }}
    else if (ev.target.closest('#box')) box.classList.remove('on');
  }});
  addEventListener('keydown', (ev) => {{ if (ev.key === 'Escape') box.classList.remove('on'); }});
</script>
</body></html>'''
os.makedirs(RUNS, exist_ok=True)
open(os.path.join(RUNS, 'index.html'), 'w', encoding='utf-8').write(page)
print(os.path.join(RUNS, 'index.html'))
