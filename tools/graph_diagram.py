# Draw the ComfyUI graph the pipeline actually sends, straight from the code that builds it:
#   py tools/graph_diagram.py docs/img/comfy-graph.jpg
# The graph is captured by letting generate.py build it with the network calls stubbed out, so the picture can never
# describe a graph that no longer exists.
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

scene = {'prompt': 'studio', 'depth': 0.95, 'depth_end': 0.95, 'normal': 0.6, 'denoise': 0.62}
spec = {'name': 'PRODUCT', 'category': 'product'}
generate.local_sdxl('runs/x/passes', 'front', 'white', scene, spec, 11)

LABELS = {
    'ckpt': ('CheckpointLoaderSimple', 'RealVisXL, the base model'),
    'model': ('LoraLoaderModelOnly', 'SDXL Lightning: 8 steps'),
    'pos': ('CLIPTextEncode', 'the scene, from the brand'),
    'neg': ('CLIPTextEncode', 'what to avoid'),
    'cn': ('ControlNetLoader', 'ControlNet Union'),
    'cn_depth': ('SetUnionControlNetType', 'depth'),
    'cn_normal': ('SetUnionControlNetType', 'normals'),
    'img_depth': ('LoadImage', 'depth pass'),
    'img_normal': ('LoadImage', 'normals pass'),
    'img_start': ('LoadImage', 'studio reference'),
    'apply_depth': ('ControlNetApplyAdvanced', 'holds the shape'),
    'apply_normal': ('ControlNetApplyAdvanced', 'holds the surface'),
    'latent': ('VAEEncode', 'start from the render'),
    'sample': ('KSampler', 'the one generative step'),
    'decode': ('VAEDecode', 'back to pixels'),
    'save': ('SaveImage', 'the photo'),
}
COLUMNS = [['img_depth', 'img_normal', 'img_start'], ['cn', 'cn_depth', 'cn_normal'], ['ckpt', 'pos', 'neg', 'model'],
           ['apply_depth', 'apply_normal', 'latent'], ['sample'], ['decode', 'save']]
ACCENT = {'sample': (255, 94, 44), 'img_depth': (66, 66, 73), 'img_normal': (66, 66, 73), 'img_start': (66, 66, 73)}

W, H = 1700, 760
PAD, BOX_W, BOX_H, GAP = 56, 196, 74, 22
img = Image.new('RGB', (W, H), (237, 235, 232))
d = ImageDraw.Draw(img)
fonts = os.path.join(ROOT, 'brands', 'meridian', 'fonts')
title = ImageFont.truetype(os.path.join(fonts, 'InterTight.ttf'), 34)
title.set_variation_by_name('Bold')
name_f = ImageFont.truetype(os.path.join(fonts, 'SpaceMono-Bold.ttf'), 13)
note_f = ImageFont.truetype(os.path.join(fonts, 'SpaceMono-Regular.ttf'), 12)
small = ImageFont.truetype(os.path.join(fonts, 'InterTight.ttf'), 16)

d.text((PAD, 40), 'The ComfyUI graph', font=title, fill=(20, 20, 22))
d.text((PAD, 86), f'{len(CAPTURED)} nodes, drawn from the graph the pipeline sends. One generative step; everything else is control.',
       font=small, fill=(100, 104, 116))

pos = {}
for c, column in enumerate(COLUMNS):
    x = PAD + c * (BOX_W + 62)
    total = len(column) * BOX_H + (len(column) - 1) * GAP
    y0 = 165 + (H - 250 - total) / 2
    for r, key in enumerate(column):
        pos[key] = (x, y0 + r * (BOX_H + GAP))

for key, node in CAPTURED.items():
    for value in node['inputs'].values():
        if isinstance(value, list) and value and value[0] in pos and key in pos:
            x0, y0 = pos[value[0]]
            x1, y1 = pos[key]
            d.line([(x0 + BOX_W, y0 + BOX_H / 2), (x0 + BOX_W + 35, y0 + BOX_H / 2),
                    (x1 - 35, y1 + BOX_H / 2), (x1, y1 + BOX_H / 2)], fill=(150, 150, 150), width=2)

for key, (x, y) in pos.items():
    name, note = LABELS.get(key, (CAPTURED[key]['class_type'], ''))
    colour = ACCENT.get(key, (255, 255, 255))
    ink = (255, 255, 255) if key == 'sample' else (20, 20, 22)
    d.rounded_rectangle([x, y, x + BOX_W, y + BOX_H], radius=10, fill=colour, outline=(205, 200, 193), width=2)
    d.text((x + 14, y + 16), name[:24], font=name_f, fill=ink)
    d.text((x + 14, y + 42), note[:28], font=note_f, fill=(235, 235, 235) if key == 'sample' else (110, 112, 122))

d.text((PAD, H - 48), 'passes in · one photo out · the protected parts and the part colours are put back after this graph',
       font=small, fill=(110, 112, 122))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join('docs', 'img', 'comfy-graph.jpg')
os.makedirs(os.path.dirname(os.path.join(ROOT, out)), exist_ok=True)
img.save(os.path.join(ROOT, out), quality=90)
print(out, len(CAPTURED), 'nodes')
