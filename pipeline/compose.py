# Stage - Compose. Layouts that are sampled, not chosen from a shelf.
# A piece is built from blocks (index line, headline, tagline, paragraph, metadata, logo) stacked inside bands, plus
# the product, bars and a colour field. An archetype picks the skeleton; a seeded sampler picks the numbers: margins,
# product scale and position, headline size, alignment, how many bars, where the field crosses. What the style stage
# measured in the references biases that sampling, so a calm moodboard gives calm pieces and a loud one gives loud
# ones. Every block is measured before it is placed, so text never collides; candidates are scored and the best kept.
#
# Usage: py pipeline/compose.py <brand dir> <product dir> <out dir> --image I [--mask M] [--format F]
#          [--colorway C] [--tagline T] [--seed N] [--tries N] [--archetype A] [--name N]
import json
import os
import random
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout import (FORMATS, Brand, fit, fit_font, load_product, logo, multiply_block, paragraph, place,  # noqa: E402
                    text, text_box, wrap)

ARCHETYPES = ('editorial', 'stack', 'corner', 'field', 'index')
MEASURE = ImageDraw.Draw(Image.new('RGB', (8, 8)))


def sample(rng, style, W, H, archetype):
    air = style.get('composition', {}).get('air', 0.7)
    rules = style.get('composition', {}).get('rules', 0.05)
    loud = style.get('light', {}).get('contrast', 20) > 26
    u = W / 100
    return {
        'archetype': archetype,
        'margin': u * rng.uniform(4.5 + 2.5 * air, 7.0 + 3.5 * air),
        'gap': u * rng.uniform(1.6, 3.4),
        'product_scale': rng.uniform(0.3, 0.78) * (0.94 if air > 0.8 else 1.08),
        'product_x': rng.choice([0.5, 0.5, 0.36, 0.64, 0.7]),
        'headline': rng.uniform(0.09, 0.19) * (1.15 if loud else 0.95),
        'align': rng.choice(['left', 'left', 'centre', 'right']),
        'bars': rng.randint(0, 3 if rules > 0.02 else 1),
        'field': rng.random() < (0.7 if loud else 0.4),
        'field_h': rng.uniform(0.05, 0.14),
        'field_y': rng.uniform(0.26, 0.74),
        'field_w': rng.uniform(0.4, 1.0),
        'meta_cols': rng.choice([1, 2, 2, 3]),
        'caps': rng.random() < (0.7 if loud else 0.35),
        'index': rng.random() < 0.55,
        'intro': rng.random() < 0.7,
        'tagline': rng.random() < 0.8,
    }


# ---------- measured blocks ----------
def measure(kind, brand, spec, ctx, p, W, H, width):
    """What a block would really take, at this width: (draw function, height)."""
    u = W / 100
    ink = 'ink'
    if kind == 'headline':
        s = spec['name'].upper() if p['caps'] else spec['name']
        f = fit_font(MEASURE, brand, 'display', s, width, H * p['headline'])
        w, h, _, _ = text_box(MEASURE, s, f)
        return (lambda d, x, y, colour: text(d, (x, y), s, f, colour), h, w)
    if kind == 'tagline':
        f = brand.font('text', u * 2.1)
        w, h, _, _ = text_box(MEASURE, ctx['tagline'], f)
        return (lambda d, x, y, colour: text(d, (x, y), ctx['tagline'], f, colour), h, w)
    if kind == 'intro':
        f = brand.font('text', u * 1.45)
        lines = wrap(MEASURE, brand.copy.get('intro', ''), f, width)
        return (lambda d, x, y, colour: paragraph(d, (x, y), brand.copy.get('intro', ''), f, colour, width),
                len(lines) * f.size * 1.45, width)
    if kind == 'index':
        year = str(spec.get('year', ''))
        f = brand.font('display', u * rng_size(p, u))
        _, h, _, _ = text_box(MEASURE, year[:2], f)
        small = brand.font('mono', u * 1.3)

        def draw_index(d, x, y, colour, width=width, f=f, small=small, year=year):
            lw, _ = text(d, (x, y), year[:2], f, colour)
            text(d, (x + width, y), year[2:], f, colour, 'ra')
            text(d, (x + lw + u * 1.2, y + u * 0.6), f"{spec.get('code', '')} · {brand.copy.get('series', '')}", small, colour)
        return (draw_index, h, width)
    if kind == 'meta':
        cols = p['meta_cols']
        rows = [(spec['name'].upper(), ctx['tagline']), ('COLORWAY', ctx['colorway'].replace('-', ' ').upper()),
                (brand.copy.get('place', '').upper(), '  '.join(brand.copy.get('coords', [])))][:cols]
        head, body = brand.font('mono_bold', u * 1.25), brand.font('mono', u * 1.25)

        def draw_meta(d, x, y, colour, rows=rows, width=width):
            for i, (a, b) in enumerate(rows):
                cx = x + i * width / len(rows)
                text(d, (cx, y), a, head, colour)
                text(d, (cx, y + u * 2.0), b, body, colour)
        return (draw_meta, u * 4.0, width)
    if kind == 'logo':
        size = u * 3.2
        return (lambda d, x, y, colour, size=size: logo(d._image, brand, x, y, size, colour), size * 1.15, width)
    raise ValueError(kind)


def rng_size(p, u):
    return 9 + 6 * p['headline'] / 0.15


def band_stack(kinds, brand, spec, ctx, p, W, H, x, width, top, align='left'):
    """Stack blocks down from `top`, measured, with the sampler's gap. Returns the drawing calls and the bottom."""
    out, y = [], top
    for kind in kinds:
        fn, h, w = measure(kind, brand, spec, ctx, p, W, H, width)
        dx = x if align == 'left' else x + (width - w) / 2 if align == 'centre' else x + width - w
        out.append((fn, dx, y, h))
        y += h + p['gap']
    return out, y - p['gap']


def plan(p, brand, spec, ctx, W, H):
    """Where each band sits for this archetype, and what the product gets."""
    m = p['margin']
    inner = W - 2 * m
    calls, product = [], None
    if p['archetype'] == 'editorial':
        top, bottom = band_stack(['logo'] + (['intro'] if p['intro'] else []), brand, spec, ctx, p, W, H, m, inner * 0.42, m)
        foot, fbottom = band_stack(['headline'] + (['tagline'] if p['tagline'] else []), brand, spec, ctx, p, W, H,
                                   m, inner * 0.7, H - m - H * (0.18 + p['headline']))
        calls += top + foot
        product = (W * 0.44, bottom + p['gap'] * 2, W - m * 0.4, H - m - H * (0.22 + p['headline']))
    elif p['archetype'] == 'stack':
        head, bottom = band_stack(['logo', 'headline'] + (['tagline'] if p['tagline'] else []), brand, spec, ctx, p,
                                  W, H, m, inner, m, 'centre')
        foot, _ = band_stack(['meta'], brand, spec, ctx, p, W, H, m, inner, H - m - H * 0.07)
        calls += head + foot
        product = (m, bottom + p['gap'] * 2, W - m, H - m - H * 0.1)
    elif p['archetype'] == 'corner':
        side = 'left' if p['align'] != 'right' else 'right'
        x = m if side == 'left' else W - m - inner * 0.46
        head, bottom = band_stack(['headline'] + (['tagline'] if p['tagline'] else []) + (['intro'] if p['intro'] else []),
                                  brand, spec, ctx, p, W, H, x, inner * 0.46, m)
        foot, _ = band_stack(['logo'], brand, spec, ctx, p, W, H, m, inner * 0.3, H - m - H * 0.06)
        calls += head + foot
        product = (m, bottom + p['gap'] * 2, W - m, H - m - H * 0.09)
    elif p['archetype'] == 'field':
        top, tb = band_stack(['logo'] + (['tagline'] if p['tagline'] else []), brand, spec, ctx, p, W, H, m, inner * 0.5, m)
        foot, _ = band_stack(['headline'], brand, spec, ctx, p, W, H, m, inner, H - m - H * p['headline'] * 1.25, p['align'])
        calls += top + foot
        product = (m, tb + p['gap'] * 2, W - m, H - m - H * (p['headline'] * 1.5))
    else:  # index
        top, tb = band_stack((['index'] if p['index'] else []) or ['logo'], brand, spec, ctx, p, W, H, m, inner, m)
        foot_kinds = ['headline'] + (['intro'] if p['intro'] else [])
        foot, _ = band_stack(foot_kinds, brand, spec, ctx, p, W, H, m, inner * 0.55, H - m - H * (0.1 + p['headline']))
        meta, _ = band_stack(['meta', 'logo'], brand, spec, ctx, p, W, H, W - m - inner * 0.4, inner * 0.4,
                             H - m - H * (0.08 + p['headline']))
        calls += top + foot + meta
        product = (m, tb + p['gap'] * 2, W - m, H - m - H * (0.16 + p['headline']))
    return calls, product


def score(calls, product, p, W, H):
    s = 10.0
    if product[3] - product[1] < H * 0.22 or product[2] - product[0] < W * 0.3:
        s -= 6  # nothing left for the product
    for fn, x, y, h in calls:
        if y < 0 or y + h > H:
            s -= 4
        if product[1] < y + h and y < product[3]:
            s -= 1.5  # a band that reaches into the product's room
    area = (product[2] - product[0]) * (product[3] - product[1]) / (W * H)
    s += 2.5 * min(area, 0.45)
    s += 1.2 * (1 - abs((product[1] + product[3]) / 2 / H - 0.52) * 2)
    return s


def draw(p, calls, product_rect, brand, spec, product, W, H, ctx):
    t = brand.spec['templates'].get('poster', {'background': 'paper', 'ink': 'black', 'accent': 'signal'})
    ink, accent = brand.color(t['ink']), brand.color(t['accent'])
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    x0, y0, x1, y1 = product_rect
    pr = fit(product, (x1 - x0) * p['product_scale'] * 1.7, (y1 - y0) * 0.96)
    place(img, pr, x0 + (x1 - x0) * p['product_x'], (y0 + y1) / 2)
    if p['field']:
        fy = H * p['field_y']
        multiply_block(img, (0, fy, W * p['field_w'], fy + H * p['field_h']), accent)
    d = ImageDraw.Draw(img)
    d._image = img  # the logo helper draws on the image itself
    u = W / 100
    # bars go in a gap nothing else uses: between the top band and the product
    top_end = max((y + h for _, _, y, h in calls if y < product_rect[1]), default=p['margin'])
    room = product_rect[1] - top_end - p['gap']
    for i in range(p['bars']):
        by = top_end + p['gap'] + i * u * 2.6
        if by + u * 1.2 > top_end + room:
            break
        d.rectangle([p['margin'], by, p['margin'] + W * (0.16 + 0.09 * (i % 2)), by + u * 1.2], fill=ink)
    for fn, x, y, h in calls:
        fn(d, x, y, ink)
    return img


def compose(brand, spec, product, W, H, ctx, style, seed=7, tries=14, archetype=None):
    rng0 = random.Random(seed)
    arch = archetype or rng0.choice(ARCHETYPES)  # the seed picks the skeleton, the tries only tune it
    best = None
    for i in range(tries):
        p = sample(random.Random(seed * 977 + i), style, W, H, arch)
        calls, product_rect = plan(p, brand, spec, ctx, W, H)
        sc = score(calls, product_rect, p, W, H)
        if not best or sc > best[0]:
            best = (sc, p, calls, product_rect)
    sc, p, calls, product_rect = best
    return draw(p, calls, product_rect, brand, spec, product, W, H, ctx), {
        'score': round(sc, 2), **{k: v for k, v in p.items() if k in ('archetype', 'align', 'bars', 'field', 'caps')}}


if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    brand_dir, product_dir, out = args[:3]
    brand = Brand(brand_dir)
    spec = json.load(open(os.path.join(product_dir, 'product.json'), encoding='utf-8'))
    fmt = opt('--format', 'portrait')
    W, H = FORMATS[fmt]
    ctx = {'tagline': opt('--tagline', brand.copy['taglines'][0]),
           'colorway': opt('--colorway', next(iter(spec['colorways'])))}
    piece, meta = compose(brand, spec, load_product(opt('--image'), opt('--mask')), W, H, ctx,
                          brand.spec.get('measured', {}), int(opt('--seed', 7)), int(opt('--tries', 14)), opt('--archetype'))
    os.makedirs(out, exist_ok=True)
    name = opt('--name', f"composed-{fmt}-{meta['archetype']}-{opt('--seed', 7)}")
    piece.save(os.path.join(out, f'{name}.png'))
    print(json.dumps({'file': os.path.join(out, f'{name}.png').replace(os.sep, '/'), **meta}))
