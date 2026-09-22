# Re-apply the consistency and lock stages to photos that are already generated, without generating again:
#   py tools/reprocess.py <passes dir> <product dir> <generated dir>
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from PIL import Image

import generate  # noqa: E402

passes, product, folder = sys.argv[1:4]
spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8'))
for name in sorted(os.listdir(folder)):
    if not name.endswith('_raw.png'):
        continue
    view, _, colorway = name.split('_')[:3]
    if not os.path.isdir(os.path.join(passes, view)):  # e.g. a view framed in another passes run
        print('skipped', view, '(no passes here)')
        continue
    out = generate.finish(Image.open(os.path.join(folder, name)).convert('RGB'), passes, view, colorway, spec)
    out.save(os.path.join(folder, name.replace('_raw.png', '.png')))
    print('reprocessed', view, colorway)
