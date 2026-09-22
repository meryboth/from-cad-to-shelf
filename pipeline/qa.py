# Stage - Route (the free version). Checks each generated photo against the product, before it reaches a layout:
#   colour  the body, where nothing is protected, compared with the colour the spec gives it: the spec is the truth,
#           not the studio render, whose tone mapping washes saturated colours out. Hue and chroma only (a CIE94-style
#           delta E without lightness), since each scene's light changes how bright the body looks.
#   parts   the protected parts, compared with the reference after the lock (they should be near identical)
# and decides: publish, review or regenerate. Jev takes this decision over later, with probabilities;
# these measurements stay as its inputs.
# Usage: py pipeline/qa.py <passes dir> <raw image> <colorway> [<product dir>] [<finished image>] -> a JSON verdict
import json
import os
import sys

import numpy as np
from PIL import Image

LIMITS = {'colour': (5.0, 10.0), 'parts': (6.0, 12.0)}  # delta E: publish below the first, regenerate above the second


def lab(img):
    """sRGB -> CIE Lab, per pixel."""
    a = np.asarray(img.convert('RGB')).astype(float) / 255
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    xyz = a @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def rgb(lab_array):
    """CIE Lab -> sRGB, the inverse of lab(). PIL's own LAB conversion is not colour managed, so we do both ways here."""
    l, a, b = lab_array[..., 0], lab_array[..., 1], lab_array[..., 2]
    fy = (l + 16) / 116
    f = np.stack([fy + a / 500, fy, fy - b / 200], -1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27))
    xyz *= np.array([0.95047, 1.0, 1.08883])
    lin = xyz @ np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]).T
    lin = np.clip(lin, 0, 1)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return Image.fromarray(np.clip(srgb * 255 + 0.5, 0, 255).astype('uint8'), 'RGB')


def spec_lab(linear):
    """A colour as the spec stores it (linear, like a material) -> Lab."""
    srgb = [v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055 for v in linear]
    return lab(Image.new('RGB', (1, 1), tuple(int(round(max(0, min(1, v)) * 255)) for v in srgb)))[0, 0]


def chroma_delta(a, b):
    """CIE94 without the lightness term: how far apart two colours are in hue and saturation."""
    c1, c2 = np.hypot(a[1], a[2]), np.hypot(b[1], b[2])
    dc = c1 - c2
    dh2 = max((a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2 - dc ** 2, 0)
    return float(np.sqrt((dc / (1 + 0.045 * c2)) ** 2 + dh2 / (1 + 0.015 * c2) ** 2))


def check(passes, image, colorway, spec=None, final=None):
    view = os.path.basename(image).split('_')[0]
    d = os.path.join(passes, view)
    gen = Image.open(image).convert('RGB')
    ref = Image.open(os.path.join(d, f'beauty_{colorway}.png')).convert('RGB').resize(gen.size)
    mask = lambda n: np.asarray(Image.open(os.path.join(d, n)).convert('L').resize(gen.size)) > 200
    body, parts = mask('mask.png') & ~mask('mask_protected.png'), mask('mask_protected.png')
    g, r = lab(gen), lab(ref)
    # colour: the median over the region, so highlights and shadows do not decide it
    hero = (spec or {}).get('hero_material')
    target = spec_lab(spec['colorways'][colorway][hero]['color']) if hero else np.median(r[body], 0)
    colour = chroma_delta(np.median(g[body], 0), target)
    # the protected parts are judged on the finished photo, after they have been put back
    p = lab(Image.open(final).convert('RGB').resize(gen.size)) if final else g
    parts_de = float(np.linalg.norm(np.median(p[parts], 0) - np.median(r[parts], 0))) if parts.any() else 0.0
    scores = {'colour': round(colour, 1), 'parts': round(parts_de, 1)}
    verdict = 'publish'
    for k, v in scores.items():
        lo, hi = LIMITS[k]
        if v > hi:
            verdict = 'regenerate'
        elif v > lo and verdict == 'publish':
            verdict = 'review'
    return {'image': image, 'view': view, 'colorway': colorway, 'delta_e': scores, 'verdict': verdict}


if __name__ == '__main__':
    product = sys.argv[4] if len(sys.argv) > 4 else None
    spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8')) if product else None
    final = sys.argv[5] if len(sys.argv) > 5 else None
    print(json.dumps(check(*sys.argv[1:4], spec, final)))
