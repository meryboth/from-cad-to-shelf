# Draw the ComfyUI graph the pipeline sends, as a diagram a person can read:
#   py tools/graph_diagram.py docs/img/comfy-graph.jpg
# The node list is captured from generate.py with the network calls stubbed out, so the drawing cannot describe a
# graph that no longer exists; the grouping and the wording are ours, so it reads as a flow and not as a hairball.
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
import generate  # noqa: E402

CAPTURED = {}
generate.upload = lambda img, name: name
generate.run = lambda graph: CAPTURED.update(graph) or Image.new('RGB', (8, 8))
generate.on_grey = lambda path, grey=None: Image.new('RGB', (8, 8))
generate.Image.open = staticmethod(lambda *a, **k: Image.new('RGB', (8, 8)))
generate.local_sdxl('runs/x/passes', 'front', 'white', {'prompt': 'studio', 'depth': 0.95, 'depth_end': 0.95,
                                                        'normal': 0.6, 'denoise': 0.62},
                    {'name': 'PRODUCT', 'category': 'product'}, 11)

# the graph, grouped the way it actually works: what comes in, what holds it, what makes the picture, what comes out
GROUPS = [
    ('From the passes', '#424249', [
        ('depth pass', 'LoadImage'), ('normals pass', 'LoadImage'), ('studio render', 'LoadImage + VAEEncode')]),
    ('Control', '#7B8794', [
        ('ControlNet Union', 'ControlNetLoader'), ('as depth · 0.95', 'SetUnionControlNetType + Apply'),
        ('as normals · 0.60', 'SetUnionControlNetType + Apply')]),
    ('Model and words', '#7B8794', [
        ('RealVisXL', 'CheckpointLoaderSimple'), ('SDXL Lightning · 8 steps', 'LoraLoaderModelOnly'),
        ('the scene, from the brand', 'CLIPTextEncode'), ('what to avoid', 'CLIPTextEncode')]),
    ('One generative step', '#FF5E2C', [
        ('KSampler · denoise 0.62', 'starts from the render')]),
    ('Out', '#424249', [('the photo', 'VAEDecode + SaveImage')]),
]
NOTES = [
    'the shape and the surfaces are the product’s own, never the model’s',
    'after this graph: each part gets its spec colour and tone, the fine detail comes back from the render,',
    'and the screen and the logo are replaced exactly',
]

W, H = 1680, 760
PAD = 64
COL_W, ROW_H, ROW_GAP = 268, 84, 20
img = Image.new('RGB', (W, H), (237, 235, 232))
d = ImageDraw.Draw(img)
fonts = os.path.join(ROOT, 'brands', 'meridian', 'fonts')


def inter(size, weight='Regular'):
    f = ImageFont.truetype(os.path.join(fonts, 'InterTight.ttf'), size)
    f.set_variation_by_name(weight)
    return f


mono = lambda size, bold=False: ImageFont.truetype(os.path.join(fonts, f'SpaceMono-{"Bold" if bold else "Regular"}.ttf'), size)
title, lead, group_f, node_f, note_f = inter(38, 'Bold'), inter(17), mono(13, True), inter(19, 'SemiBold'), mono(12)

d.text((PAD, 44), 'The ComfyUI graph', font=title, fill=(18, 18, 20))
d.text((PAD, 96), f'{len(CAPTURED)} nodes. One of them generates; the rest hold the product in place.',
       font=lead, fill=(104, 108, 120))

# lay the groups out left to right, each as a labelled column
top = 190
columns = []
for i, (name, colour, rows) in enumerate(GROUPS):
    x = PAD + i * (COL_W + 62)
    height = len(rows) * ROW_H + (len(rows) - 1) * ROW_GAP
    y = top + (4 * ROW_H + 3 * ROW_GAP - height) / 2
    d.text((x, top - 34), name.upper(), font=group_f, fill=(120, 124, 136))
    boxes = []
    for r, (label, sub) in enumerate(rows):
        by = y + r * (ROW_H + ROW_GAP)
        accent = colour == '#FF5E2C'
        fill = (255, 94, 44) if accent else (255, 255, 255)
        ink = (255, 255, 255) if accent else (22, 22, 24)
        d.rounded_rectangle([x, by, x + COL_W, by + ROW_H], radius=12, fill=fill,
                            outline=(255, 94, 44) if accent else (206, 201, 194), width=2)
        d.text((x + 16, by + 16), label, font=node_f, fill=ink)
        d.text((x + 16, by + 46), sub[:38], font=note_f, fill=(232, 232, 232) if accent else (126, 129, 140))
        boxes.append((x, by, x + COL_W, by + ROW_H))
    columns.append(boxes)

# arrows: every box of a column feeds the column on its right, drawn as elbows so nothing crosses
for i in range(len(columns) - 1):
    right = columns[i + 1]
    for (x0, y0, x1, y1) in columns[i]:
        for (rx0, ry0, rx1, ry1) in right:
            if len(right) > 1 and len(columns[i]) == len(right) and columns[i].index((x0, y0, x1, y1)) != right.index((rx0, ry0, rx1, ry1)):
                continue  # one to one when the columns match, otherwise fan out
            mid = (x1 + rx0) / 2
            cy0, cy1 = (y0 + y1) / 2, (ry0 + ry1) / 2
            d.line([(x1, cy0), (mid, cy0), (mid, cy1), (rx0 - 10, cy1)], fill=(168, 168, 168), width=2)
            d.polygon([(rx0, cy1), (rx0 - 11, cy1 - 6), (rx0 - 11, cy1 + 6)], fill=(168, 168, 168))

y = H - 104
for i, line in enumerate(NOTES):
    d.text((PAD, y + i * 26), line, font=inter(17) if i == 0 else note_f, fill=(120, 124, 136))
d.line([(PAD, y - 22), (W - PAD, y - 22)], fill=(214, 210, 203), width=1)

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join('docs', 'img', 'comfy-graph.jpg')
os.makedirs(os.path.dirname(os.path.join(ROOT, out)), exist_ok=True)
img.save(os.path.join(ROOT, out), quality=92)
print(out, len(CAPTURED), 'nodes')
