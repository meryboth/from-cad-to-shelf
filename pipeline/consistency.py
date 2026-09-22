# Stage - Consistency. Every view of a product has to look like the same object: the same body colour, the same
# buttons, the same trim. Each view is generated on its own, so a model is free to invent a different grey d-pad
# every time. This stage removes that freedom, using the parts map from the passes stage (mask_parts.png, one flat
# colour per material) and the colours in the product spec:
#   - for every part, the hue and chroma come from the spec, the lightness stays from the photo, so the part keeps
#     the scene's light and texture but never drifts in colour
#   - parts the spec does not describe fall back to the studio reference
# It also measures the result: how far each part of each view is from its spec colour, across a whole run.
#
# Usage: py pipeline/consistency.py <passes dir> <image> <colorway> <product dir> [--out file.png]
#        py pipeline/consistency.py --check <passes dir> <colorway> <product dir> <image> [<image> ...]
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qa import chroma_delta, lab, rgb, spec_lab  # noqa: E402


def part_masks(passes, view, size, tolerance=40):
    """Where each material is in the frame, from the flat-colour parts map."""
    manifest = json.load(open(os.path.join(passes, 'manifest.json'), encoding='utf-8'))
    path = os.path.join(passes, view, 'mask_parts.png')
    if not os.path.exists(path):
        return {}
    parts = np.asarray(Image.open(path).convert('RGB').resize(size, Image.NEAREST)).astype(float)
    out = {}
    for name, color in manifest.get('materials', {}).items():
        rgb = np.array([round(c * 255) for c in color])  # the pass is rendered raw, so its bytes are the linear values
        m = np.linalg.norm(parts - rgb, axis=-1) < tolerance
        if m.sum() > 40:
            out[name] = m
    return out


def targets(passes, view, colorway, spec, size, min_share=0.002):
    """The colour each part should have: from the spec where it says, from the studio reference otherwise.
    Parts that are replaced exactly later (a screen, a logo) are left alone, and specks too small to judge are skipped."""
    ref = Image.open(os.path.join(passes, view, f'beauty_{colorway}.png')).convert('RGB').resize(size)
    r = lab(ref)
    exact = set(spec.get('exact_materials', []))
    out = {}
    for name, mask in part_masks(passes, view, size).items():
        if name in exact or mask.sum() < min_share * size[0] * size[1]:
            continue
        props = spec.get('colorways', {}).get(colorway, {}).get(name, {})
        out[name] = (spec_lab(props['color']) if 'color' in props else np.median(r[mask], 0), mask)
    return out


def enforce(img, passes, view, colorway, spec, strength=0.9, feather=1.2):
    """Give every part its colour back, keeping the photo's light."""
    g = lab(img)
    for name, (target, mask) in targets(passes, view, colorway, spec, img.size).items():
        soft = np.asarray(Image.fromarray((mask * 255).astype('uint8')).filter(ImageFilter.GaussianBlur(feather))).astype(float) / 255
        soft = soft[..., None] * strength
        g[..., 1:] = g[..., 1:] * (1 - soft) + np.array(target[1:]) * soft  # hue and chroma from the target, light from the photo
    return rgb(g)


def measure(passes, colorway, spec, images):
    """Per part, how far each view is from the spec colour, and how far the views are from each other."""
    per_part = {}
    for path in images:
        view = os.path.basename(path).split('_')[0]
        img = Image.open(path).convert('RGB')
        g = lab(img)
        for name, (target, mask) in targets(passes, view, colorway, spec, img.size).items():
            per_part.setdefault(name, []).append((view, np.median(g[mask], 0), target))
    report = {}
    for name, rows in per_part.items():
        to_spec = max(chroma_delta(v, t) for _, v, t in rows)
        spread = max((chroma_delta(a, b) for _, a, _ in rows for _, b, _ in rows), default=0.0)
        report[name] = {'views': len(rows), 'to_spec': round(to_spec, 1), 'between_views': round(spread, 1)}
    worst = max((r['between_views'] for r in report.values()), default=0.0)
    return {'colorway': colorway, 'parts': report, 'worst_between_views': round(worst, 1),
            'verdict': 'consistent' if worst <= 6 else 'drifting'}


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[0] == '--check':
        passes, colorway, product, *images = args[1:]
        spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8'))
        print(json.dumps(measure(passes, colorway, spec, images), indent=2))
    else:
        passes, image, colorway, product = args[:4]
        spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8'))
        out = args[args.index('--out') + 1] if '--out' in args else image
        view = os.path.basename(image).split('_')[0]
        enforce(Image.open(image).convert('RGB'), passes, view, colorway, spec).save(out)
        print(out)
