# What each guard is worth: run the same view with pieces of the pipeline turned off, and measure.
#   py tools/ablation.py <product dir> <passes dir> <view> <colorway>
# Writes runs/<product>/ablation.json. Local only, free.
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
from PIL import Image  # noqa: E402

import consistency  # noqa: E402
import generate  # noqa: E402
import qa  # noqa: E402

product, passes, view, colorway = sys.argv[1:5]
spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8'))
scene = json.load(open(os.path.join('brands', 'meridian', 'scenes.json'), encoding='utf-8'))['studio-paper']
out_dir = os.path.join('runs', os.path.basename(product), 'ablation')
os.makedirs(out_dir, exist_ok=True)

VARIANTS = [
    ('full', {}, 'the pipeline as it ships'),
    ('loose-control', {'depth': 0.55, 'normal': 0.25, 'denoise': 0.85}, 'ControlNet at half strength, more freedom'),
    ('no-guards', {}, 'the raw model output: no colour, tone or detail put back'),
]
rows = []
for name, tweak, note in VARIANTS:
    sc = {**scene, **tweak}
    # the view has to lead the filename: the QA reads it from there
    path = os.path.join(out_dir, f'{view}_{name}.png')
    raw_path = os.path.join(out_dir, f'{view}_{name}_raw.png')
    seconds = 0.0
    if os.path.exists(raw_path):
        raw = Image.open(raw_path).convert('RGB')
        print(f'{name}: reusing the photo already generated', flush=True)
    else:
        t0 = time.time()
        raw, _ = generate.local_sdxl(passes, view, colorway, sc, spec, 11)
        seconds = round(time.time() - t0, 1)
        raw.save(raw_path)
    img = raw if name == 'no-guards' else generate.finish(raw, passes, view, colorway, spec)
    img.save(path)
    verdict = qa.check(passes, raw_path, colorway, spec, path)
    parts = consistency.measure(passes, colorway, spec, [path])
    rows.append({'variant': name, 'note': note, 'seconds': seconds, 'file': path.replace(os.sep, '/'),
                 'colour_delta_e': verdict['delta_e']['colour'], 'parts_delta_e': verdict['delta_e']['parts'],
                 'verdict': verdict['verdict'],
                 'worst_part_to_spec': max((p['to_spec'] for p in parts['parts'].values()), default=0.0)})
    print(json.dumps(rows[-1]), flush=True)
json.dump(rows, open(os.path.join('runs', os.path.basename(product), 'ablation.json'), 'w'), indent=2)
