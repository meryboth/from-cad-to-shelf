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

# the report first, so it never lists pieces this run is about to replace
subprocess.run([PY, 'tools/report.py'], cwd=ROOT, capture_output=True)

# 1 · passes, once per product
if not os.path.exists(os.path.join(ROOT, passes, 'manifest.json')):
    step('passes', [BLENDER, '-b', '-P', 'pipeline/passes.py', '--', product, passes])

# 3 · generate every view and colorway the pieces need, once each
# 5 · route each photo through the QA: publish, review, or regenerate with the next seed (up to 3 tries)
needed = []
for p in plan['pieces']:
    for v in filter(None, (p['view'], p.get('view2'))):
        if (v, p['colorway']) not in needed:
            needed.append((v, p['colorway']))
gen_dir = os.path.join('runs', pid, 'generate', backend)
qa_path = os.path.join(ROOT, 'runs', pid, 'qa.json')
qa = json.load(open(qa_path)) if os.path.exists(qa_path) else {}
chosen = {}
for v, cw in needed:
    base = int(plan.get('seed', 7))
    for seed in (base, base + 1, base + 2):
        out = os.path.join(gen_dir, f'{v}_{scene}_{cw}_s{seed}.png')
        if not os.path.exists(os.path.join(ROOT, out)) or '--force' in args:
            step(f'generate {v} {cw} seed {seed}', [PY, 'pipeline/generate.py', product, brand, passes, '--backend', backend,
                                                   '--view', v, '--scene', scene, '--colorway', cw, '--seed', str(seed)] + extra)
        # judge what the model produced, before the consistency stage corrects it: that is where drift shows
        raw = out.replace('.png', '_raw.png')
        judged = raw if os.path.exists(os.path.join(ROOT, raw)) else out
        verdict = json.loads(step(f'qa {v} {cw} seed {seed}', [PY, 'pipeline/qa.py', passes, judged, cw, product, out]))
        verdict['seed'] = seed
        qa[out.replace(os.sep, '/')] = verdict
        chosen[(v, cw)] = out
        print(f"   {verdict['verdict']}  delta E {verdict['delta_e']}")
        if verdict['verdict'] != 'regenerate':
            break
json.dump(qa, open(qa_path, 'w'), indent=2)

# 5b · consistency across the views of each colorway: the same object, in every piece
cons = {}
for cw in sorted({cw for _, cw in needed}):
    images = [chosen[k] for k in chosen if k[1] == cw]
    out = step(f'consistency {cw}', [PY, 'pipeline/consistency.py', '--check', passes, cw, product] + images)
    cons[cw] = json.loads(out)
    print(f"   {cons[cw]['verdict']}  worst drift between views: {cons[cw]['worst_between_views']}")
json.dump(cons, open(os.path.join(ROOT, 'runs', pid, 'consistency.json'), 'w'), indent=2)

# 4 · layout: each piece on the generated photo, cut with the mask of the camera it came from
layout_dir = os.path.join('runs', pid, 'layout', os.path.basename(plan.get('slug', args[0]))[:-5])
for p in plan['pieces']:
    img = lambda v: chosen[(v, p['colorway'])]
    cmd = [PY, 'pipeline/layout.py', brand, product, layout_dir, '--template', p['template'], '--format', p['format'],
           '--image', img(p['view']), '--mask', os.path.join(passes, p['view'], 'mask.png'),
           '--colorway', p['colorway'], '--tagline', p['tagline'],
           '--name', f"{p['template']}-{p['format']}-{p['colorway']}"]
    if p.get('view2'):
        cmd += ['--image2', img(p['view2']), '--mask2', os.path.join(passes, p['view2'], 'mask.png')]
    step(f"layout {p['template']} {p['format']} {p['colorway']}", cmd)
    subprocess.run([PY, 'tools/report.py'], cwd=ROOT, capture_output=True)  # each piece shows up as soon as it exists

step('report', [PY, 'tools/report.py'])
print(f'\nDone: {len(plan["pieces"])} pieces in {layout_dir}')
