# Stage 0 - Style. A moodboard in, a brand and a campaign out.
# Drop reference images in a folder (a campaign you like, a palette, a poster) and this reads them:
#   palette      the colours that carry the images, sorted by how much of the frame they hold, then given roles
#   light        brightness, contrast and warmth become the words the scenes are generated with
#   composition  where the content sits and how much air is left decides which templates fit, and in what order
#   type         the visual contrast decides the weight and the case of the headline
# It writes brands/<name>/ (brand.json + scenes.json, fonts copied from the library) and campaigns/<name>.json,
# so the rest of the pipeline runs unchanged. No model, no API, no cost: measurements, then rules.
#
# Usage: py pipeline/style.py <references dir> --name <brand> --product products/lumen [--fonts brands/meridian/fonts]
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
from qa import lab  # noqa: E402

TEMPLATES = ('poster', 'spread', 'specsheet')


def load(folder, side=420):
    out = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
            im = Image.open(os.path.join(folder, name)).convert('RGB')
            im.thumbnail((side, side))
            out.append((name, im))
    if not out:
        raise SystemExit(f'no reference images in {folder}')
    return out


# ---------- palette ----------
def palette(images, k=6, rounds=12):
    """k-means in Lab over every reference at once: the colours that actually hold the frames."""
    px = np.concatenate([lab(im).reshape(-1, 3) for _, im in images])
    px = px[np.random.default_rng(7).choice(len(px), min(40000, len(px)), replace=False)]
    centres = px[np.random.default_rng(3).choice(len(px), k, replace=False)]
    for _ in range(rounds):
        d = np.linalg.norm(px[:, None] - centres[None], axis=-1)
        which = d.argmin(1)
        for i in range(k):
            if (which == i).any():
                centres[i] = px[which == i].mean(0)
    share = np.array([(which == i).mean() for i in range(k)])
    order = np.argsort(-share)
    return centres[order], share[order]


def roles(centres, share):
    """Background, ink, accent, neutral: by lightness, chroma and how much of the frame each colour holds."""
    chroma = np.hypot(centres[:, 1], centres[:, 2])
    light = centres[:, 0]
    bg = int(np.argmax(share * (light > 60)))if (light > 60).any() else int(np.argmax(light))
    ink = int(np.argmin(light))
    # the accent is the most saturated colour that is neither the background nor the ink
    score = chroma.copy()
    score[[bg, ink]] = -1
    accent = int(np.argmax(score))
    rest = [i for i in range(len(centres)) if i not in (bg, ink, accent)]
    neutral = min(rest, key=lambda i: chroma[i]) if rest else bg
    return {'background': bg, 'ink': ink, 'accent': accent, 'neutral': neutral}


def hexes(centres, idx):
    from qa import rgb
    out = {}
    for role, i in idx.items():
        c = np.asarray(rgb(centres[i][None, None]))[0, 0]
        out[role] = '#%02X%02X%02X' % tuple(int(v) for v in c)
    return out


# ---------- light and composition ----------
def light_words(images):
    l = np.concatenate([lab(im)[..., 0].ravel() for _, im in images])
    ab = np.concatenate([lab(im)[..., 1:].reshape(-1, 2) for _, im in images])
    warmth = float(ab[:, 1].mean())          # positive b: warm
    contrast = float(l.std())
    bright = float(l.mean())
    words = []
    words.append('warm' if warmth > 6 else 'cool' if warmth < -2 else 'neutral')
    words.append('high contrast, crisp shadows' if contrast > 28 else 'soft even light, gentle shadows')
    words.append('bright, airy' if bright > 68 else 'moody, low key' if bright < 45 else 'balanced exposure')
    return {'warmth': round(warmth, 1), 'contrast': round(contrast, 1), 'brightness': round(bright, 1),
            'words': ', '.join(words)}


def composition(images):
    """Where the content sits, and how much of the frame is calm: enough to rank the templates."""
    tops, sides, air, lines = [], [], [], []
    for _, im in images:
        g = np.asarray(im.convert('L').filter(ImageFilter.FIND_EDGES)).astype(float)
        g = g / (g.max() or 1)
        busy = g > 0.18
        air.append(1 - busy.mean())
        ys, xs = np.nonzero(busy)
        if len(ys):
            tops.append(ys.mean() / g.shape[0])
            sides.append(xs.mean() / g.shape[1])
        # straight runs: a grid of rules and boxes, as a spec sheet has
        h = (busy.sum(1) > 0.5 * busy.shape[1]).mean()
        v = (busy.sum(0) > 0.5 * busy.shape[0]).mean()
        lines.append(h + v)
    m = {'content_y': round(float(np.mean(tops)), 3), 'content_x': round(float(np.mean(sides)), 3),
         'air': round(float(np.mean(air)), 3), 'rules': round(float(np.mean(lines)), 3)}
    score = {
        'poster': 1.2 * m['air'] + (0.6 if m['content_y'] > 0.45 else 0.1) + (0.3 if abs(m['content_x'] - 0.5) < 0.12 else 0),
        'spread': 0.8 * m['air'] + (0.7 if abs(m['content_x'] - 0.5) > 0.06 else 0.1),
        'specsheet': 2.5 * m['rules'] + 0.4 * (1 - m['air']),
    }
    m['templates'] = [t for t in sorted(TEMPLATES, key=lambda t: -score[t])]
    m['scores'] = {t: round(score[t], 3) for t in TEMPLATES}
    return m


def type_rules(comp, light):
    """Loud references get a bold, upper-case headline; quiet ones a medium, sentence-case one."""
    loud = light['contrast'] > 26 and comp['air'] > 0.55
    return {'weight': 'Bold' if loud else 'Medium', 'case': 'upper' if loud else 'sentence'}


# ---------- write the brand and the campaign ----------
def write(name, refs, product, fonts_src, colors, light, comp, type_):
    brand_dir = os.path.join(ROOT, 'brands', name)
    os.makedirs(os.path.join(brand_dir, 'fonts'), exist_ok=True)
    for f in os.listdir(fonts_src):
        shutil.copy(os.path.join(fonts_src, f), os.path.join(brand_dir, 'fonts', f))
    display = f"fonts/InterTight.ttf#{type_['weight']}"
    brand = {
        'name': name,
        'fictional': True,
        'from_references': os.path.relpath(refs, ROOT).replace(os.sep, '/'),
        'tone': f"Read from the references: {light['words']}.",
        'colors': {'paper': colors['background'], 'stone': colors['neutral'], 'ink': colors['ink'],
                   'black': colors['ink'], 'signal': colors['accent'], 'white': '#FAFAF8'},
        'fonts': {'display': [display], 'medium': ['fonts/InterTight.ttf#Medium'], 'text': ['fonts/InterTight.ttf#Regular'],
                  'mono': ['fonts/SpaceMono-Regular.ttf'], 'mono_bold': ['fonts/SpaceMono-Bold.ttf']},
        'logo': {'text': f'{name}\ninstruments', 'mark': 'meridian'},
        'copy': {'taglines': ['Play it slow.', 'Made to be played.', 'One screen. Two buttons.'],
                 'intro': 'A handheld with a backlit screen, a D-pad and a cartridge slot on the back. Made for the games '
                          'you remember, and the ones you have not played yet.',
                 'place': 'Buenos Aires', 'coords': ['34°36′S', '58°22′W'], 'series': 'Field Series',
                 'nav': ['handheld', 'colorways', 'specs']},
        'templates': {t: {'background': 'paper', 'ink': 'black', 'accent': 'signal',
                          **({'card': 'white'} if t == 'specsheet' else {}), **({'title': 'signal'} if t == 'poster' else {})}
                      for t in TEMPLATES},
        'measured': {'light': light, 'composition': comp, 'type': type_},
    }
    json.dump(brand, open(os.path.join(brand_dir, 'brand.json'), 'w', encoding='utf-8'), indent=2)
    scenes = {'studio-ref': {'label': 'From the references',
                             'prompt': f"on a seamless {['cool', 'neutral', 'warm'][(light['warmth'] > -2) + (light['warmth'] > 6)]} "
                                       f"studio backdrop, {light['words']}, a gentle contact shadow, campaign product photo",
                             'depth': 0.95, 'depth_end': 0.95, 'normal': 0.6, 'denoise': 0.62}}
    json.dump(scenes, open(os.path.join(brand_dir, 'scenes.json'), 'w', encoding='utf-8'), indent=2)

    spec = json.load(open(os.path.join(ROOT, product, 'product.json'), encoding='utf-8'))
    colorways = list(spec['colorways'])
    formats = {'poster': ['portrait', 'story'], 'spread': ['landscape'], 'specsheet': ['sheet']}
    views = {'poster': 'front', 'spread': 'left', 'specsheet': 'front'}
    pieces = []
    for t in comp['templates'][:2]:  # the two templates the references lean to, as fixed layouts
        for i, fmt in enumerate(formats[t]):
            cw = colorways[i % len(colorways)]
            piece = {'template': t, 'format': fmt, 'view': views[t], 'colorway': cw,
                     'tagline': brand['copy']['taglines'][len(pieces) % 3]}
            if t == 'specsheet':
                piece['view2'] = 'right'
            pieces.append(piece)
    # and a set of sampled ones: same inputs, a different composition each seed
    for i, seed in enumerate((3, 8, 14, 21, 29, 33)):
        pieces.append({'template': 'auto', 'format': ['portrait', 'story', 'portrait'][i % 3], 'view': 'front',
                       'colorway': colorways[i % len(colorways)], 'seed': seed,
                       'tagline': brand['copy']['taglines'][i % 3]})
    plan = {'name': f'{name} campaign', 'product': product, 'brand': f'brands/{name}', 'backend': 'local-sdxl',
            'scene': 'studio-ref', 'seed': 11, 'pieces': pieces}
    json.dump(plan, open(os.path.join(ROOT, 'campaigns', f'{name}.json'), 'w', encoding='utf-8'), indent=2)
    return brand, plan


if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    refs = os.path.abspath(args[0])
    name = opt('--name', os.path.basename(refs))
    images = load(refs)
    centres, share = palette(images)
    colors = hexes(centres, roles(centres, share))
    light, comp = light_words(images), composition(images)
    type_ = type_rules(comp, light)
    brand, plan = write(name, refs, opt('--product', 'products/lumen'), opt('--fonts', os.path.join(ROOT, 'brands', 'meridian', 'fonts')),
                        colors, light, comp, type_)
    print(json.dumps({'references': [n for n, _ in images], 'colors': colors, 'light': light,
                      'composition': comp, 'type': type_, 'pieces': len(plan['pieces'])}, indent=2))
