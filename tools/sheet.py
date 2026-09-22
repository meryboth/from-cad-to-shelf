# Contact sheet of a passes run: one row per view, one column per pass.
# Usage: py tools/sheet.py runs/<product>/passes out.jpg [tile px]
import json
import os
import sys

from PIL import Image

run, out = sys.argv[1], sys.argv[2]
tile = int(sys.argv[3]) if len(sys.argv) > 3 else 280
m = json.load(open(os.path.join(run, 'manifest.json')))
views = list(m['views'])
cols = [f'beauty_{cw}' for cw in m['colorways'] if os.path.exists(os.path.join(run, views[0], f'beauty_{cw}.png'))]
cols += ['depth', 'normal', 'mask', 'mask_protected']
sheet = Image.new('RGB', (tile * len(cols), tile * len(views)), (216, 216, 216))
for r, v in enumerate(views):
    for c, name in enumerate(cols):
        im = Image.open(os.path.join(run, v, f'{name}.png'))
        if im.mode == 'RGBA':
            bg = Image.new('RGBA', im.size, (216, 216, 216, 255))
            bg.alpha_composite(im)
            im = bg
        sheet.paste(im.convert('RGB').resize((tile, tile)), (c * tile, r * tile))
sheet.save(out, quality=88)
print(out)
