# One command, the whole campaign: py pipeline/run.py campaigns/<campaign>.json [--force] [--spend]
# Passes -> generate -> layout -> report, in that order. Every stage reuses what already exists, so a re-run only
# does the missing work; --force redoes the generated images. Paid backends still need --spend.
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLENDER = os.environ.get('BLENDER', r'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe')
PY = sys.executable


def step(title, cmd):
    t0 = time.time()
    print(f'\n== {title}', flush=True)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f'failed: {title}')
    print(f'   done in {time.time() - t0:.0f} s', flush=True)
    return r.stdout


args = sys.argv[1:]
plan = json.load(open(os.path.join(ROOT, args[0]), encoding='utf-8'))
product, brand, backend, scene = plan['product'], plan['brand'], plan['backend'], plan['scene']
pid = os.path.basename(product)
passes = os.path.join('runs', pid, 'passes')
extra = ['--spend'] if '--spend' in args else []

# 1 · passes, once per product
if not os.path.exists(os.path.join(ROOT, passes, 'manifest.json')):
    step('passes', [BLENDER, '-b', '-P', 'pipeline/passes.py', '--', product, passes])

# 3 · generate every view and colorway the pieces need, once each
needed = []
for p in plan['pieces']:
    for v in filter(None, (p['view'], p.get('view2'))):
        if (v, p['colorway']) not in needed:
            needed.append((v, p['colorway']))
gen_dir = os.path.join('runs', pid, 'generate', backend)
for v, cw in needed:
    out = os.path.join(gen_dir, f'{v}_{scene}_{cw}_s7.png')
    if os.path.exists(os.path.join(ROOT, out)) and '--force' not in args:
        print(f'\n== generate {v} {cw}: already there')
        continue
    step(f'generate {v} {cw}', [PY, 'pipeline/generate.py', product, brand, passes, '--backend', backend, '--view', v,
                                '--scene', scene, '--colorway', cw] + extra)

# 4 · layout: each piece on the generated photo, cut with the mask of the camera it came from
layout_dir = os.path.join('runs', pid, 'layout', os.path.basename(plan.get('slug', args[0]))[:-5])
for p in plan['pieces']:
    img = lambda v: os.path.join(gen_dir, f'{v}_{scene}_{p["colorway"]}_s7.png')
    cmd = [PY, 'pipeline/layout.py', brand, product, layout_dir, '--template', p['template'], '--format', p['format'],
           '--image', img(p['view']), '--mask', os.path.join(passes, p['view'], 'mask.png'),
           '--colorway', p['colorway'], '--tagline', p['tagline'],
           '--name', f"{p['template']}-{p['format']}-{p['colorway']}"]
    if p.get('view2'):
        cmd += ['--image2', img(p['view2']), '--mask2', os.path.join(passes, p['view2'], 'mask.png')]
    step(f"layout {p['template']} {p['format']} {p['colorway']}", cmd)

step('report', [PY, 'tools/report.py'])
print(f'\nDone: {len(plan["pieces"])} pieces in {layout_dir}')
