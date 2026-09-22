# Stage - Layout. Product images + a brand -> finished campaign pieces, with real type, colours and logo.
# The type is set here, never by the image model: generated text is unreliable, and brand type has to be exact.
# Every size is a fraction of the canvas, so one template serves every format.
#
# Usage: py pipeline/layout.py <brand dir> <product dir> <out dir> --template poster|spread|specsheet --format F
#          --image <product image> [--mask <mask.png>] [--image2 <second view>] [--mask2 <mask.png>]
#          [--colorway C] [--tagline T] [--name N]
#   an image is an RGBA cut-out (a beauty pass), or a generated photo plus the mask of the same camera
import datetime
import json
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FORMATS = {'landscape': (1200, 628), 'square': (1080, 1080), 'portrait': (1080, 1350), 'story': (1080, 1920),
           'sheet': (1200, 900)}


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Brand:
    def __init__(self, folder):
        self.dir = folder
        self.spec = json.load(open(os.path.join(folder, 'brand.json'), encoding='utf-8'))
        self.colors = {k: hex_rgb(v) for k, v in self.spec['colors'].items()}
        self.copy = self.spec.get('copy', {})
        self._fonts = {}

    def font(self, role, size):
        size = max(int(size), 6)
        key = (role, size)
        if key not in self._fonts:
            self._fonts[key] = self._load(role, size)
        return self._fonts[key]

    def _load(self, role, size):
        for entry in self.spec['fonts'].get(role) or self.spec['fonts']['text']:
            path, _, variation = entry.partition('#')  # "file.ttf#Bold" picks a weight of a variable font
            full = path if os.path.isabs(path) else os.path.join(self.dir, path)
            try:
                f = ImageFont.truetype(full, size)
            except OSError:
                continue
            if variation:
                f.set_variation_by_name(variation)
            return f
        return ImageFont.load_default(size)

    def color(self, name):
        return self.colors.get(name) or hex_rgb(name)


# ---------- images ----------
def load_product(path, mask=None):
    """The product alone, trimmed. A studio cut-out carries its own alpha; a generated photo is cut with the mask
    of the camera it was generated from (the ControlNet graph keeps the camera, so the mask fits pixel for pixel)."""
    im = Image.open(path).convert('RGBA')
    mask = mask or os.path.join(os.path.dirname(path), 'mask.png')
    if mask and os.path.exists(mask):
        m = Image.open(mask).convert('L').resize(im.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
        im.putalpha(ImageChops.multiply(m, im.getchannel('A')))
    box = im.getchannel('A').point(lambda a: 255 if a > 10 else 0).getbbox()
    return im.crop(box)


def fit(img, max_w, max_h):
    k = min(max_w / img.width, max_h / img.height)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def place(canvas, product, cx, cy, shadow=True):
    """Paste centred on (cx, cy), with a soft contact shadow under it, so it sits on the paper instead of floating."""
    x, y = int(cx - product.width / 2), int(cy - product.height / 2)
    if shadow:  # drawn on a padded canvas, so the blur fades out instead of stopping at a straight edge
        pad = int(product.width * 0.15)
        sh = Image.new('L', (product.width + 2 * pad, max(4, product.height // 14) + 2 * pad), 0)
        ImageDraw.Draw(sh).ellipse([pad + product.width * 0.06, pad, pad + product.width * 0.94, sh.height - pad], fill=80)
        sh = sh.filter(ImageFilter.GaussianBlur(product.width * 0.035))
        canvas.paste(Image.new('RGB', sh.size, (0, 0, 0)), (x - pad, y + product.height - sh.height // 2), sh)
    canvas.paste(product, (x, y), product)
    return x, y


def multiply_block(canvas, box, color, opacity=0.92):
    """A flat colour block that multiplies with what is under it, like ink over a print."""
    x0, y0, x1, y1 = (int(v) for v in box)
    region = canvas.crop((x0, y0, x1, y1))
    inked = ImageChops.multiply(region, Image.new('RGB', region.size, color))
    canvas.paste(Image.blend(region, inked, opacity), (x0, y0))


# ---------- type ----------
def text_box(d, s, font):
    l, t, r, b = d.textbbox((0, 0), s, font=font)
    return r - l, b - t, l, t


def text(d, xy, s, font, fill, anchor='la'):
    """Draw by the ink box, not the font box: 'la' left-top, 'ra' right-top, 'ma' centre-top, 'lb' left-bottom."""
    w, h, l, t = text_box(d, s, font)
    x, y = xy
    if anchor[0] == 'r':
        x -= w
    elif anchor[0] == 'm':
        x -= w / 2
    if anchor[1] == 'b':
        y -= h
    d.text((x - l, y - t), s, font=font, fill=fill)
    return w, h


def wrap(d, s, font, max_w):
    lines, cur = [], ''
    for word in s.split():
        trial = (cur + ' ' + word).strip()
        if text_box(d, trial, font)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def paragraph(d, xy, s, font, fill, max_w, leading=1.45):
    x, y = xy
    lines = wrap(d, s, font, max_w)
    for i, line in enumerate(lines):
        d.text((x, y + i * font.size * leading), line, font=font, fill=fill)
    return len(lines) * font.size * leading


def fit_font(d, brand, role, s, max_w, max_h):
    size = int(max_h * 1.4)
    while size > 6:
        f = brand.font(role, size)
        w, h, _, _ = text_box(d, s, f)
        if w <= max_w and h <= max_h:
            return f
        size = int(size * 0.95)
    return brand.font(role, 6)


def logo(canvas, brand, x, y, size, color):
    """The mark (a circle cut by its meridian) and the wordmark, `size` tall, from its top-left corner."""
    d = ImageDraw.Draw(canvas)
    r = size / 2
    lw = max(1, int(size * 0.09))
    d.ellipse([x, y, x + size, y + size], outline=color, width=lw)
    d.line([x + r, y - size * 0.12, x + r, y + size * 1.12], fill=color, width=lw)
    f = brand.font('medium', size * 0.44)
    for i, line in enumerate(brand.spec['logo']['text'].split('\n')):
        d.text((x + size * 1.35, y + i * size * 0.52), line, font=f, fill=color)


NUMBERS = {'24': 'twenty-four', '25': 'twenty-five', '26': 'twenty-six', '27': 'twenty-seven'}


# ---------- templates ----------
def poster(brand, spec, product, W, H, ctx):
    """A Swiss-grid poster: the year split across the top, a bar and a caption, the product with a signal block
    across it, and a grid of small facts at the bottom."""
    t = brand.spec['templates']['poster']
    ink, accent = brand.color(t['ink']), brand.color(t['accent'])
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    d = ImageDraw.Draw(img)
    u = W / 100  # one grid unit
    m = 4.5 * u
    year = str(spec.get('year', datetime.date.today().year))
    big = brand.font('display', 17 * u)
    small = brand.font('text', 1.9 * u)
    mono, mono_b = brand.font('mono', 1.45 * u), brand.font('mono_bold', 1.45 * u)
    # top row: 20 twenty ......... twenty-six 26
    lw, lh = text(d, (m, m), year[:2], big, ink)
    text(d, (m + lw + 1.2 * u, m + 0.2 * u), 'twenty', small, ink)
    rw, _ = text(d, (W - m, m), year[2:], big, ink, 'ra')
    text(d, (W - m - rw - 1.2 * u, m + 0.2 * u), NUMBERS.get(year[2:], year[2:]), small, ink, 'ra')
    bar_y = m + lh * 0.62
    d.rectangle([33 * u, bar_y, 58 * u, bar_y + 1.9 * u], fill=ink)
    cap_y = bar_y + 3.2 * u
    text(d, (33 * u, cap_y), spec['name'].upper(), mono_b, ink)
    text(d, (33 * u, cap_y + 2.1 * u), f"{spec.get('code', '')} · {brand.copy.get('series', '')}", mono, ink)
    right = W - m - rw - 1.2 * u
    text(d, (right, cap_y), brand.copy.get('place', '').upper(), mono_b, ink, 'ra')
    text(d, (right, cap_y + 2.1 * u), '  '.join(brand.copy.get('coords', [])), mono, ink, 'ra')
    # the product, and the signal block across it
    top = cap_y + 6 * u
    bottom = H - 30 * u
    p = fit(product, W * 0.5, (bottom - top) * 0.9)
    cy = (top + bottom) / 2
    place(img, p, W / 2, cy)
    band = (bottom - top) * 0.16
    multiply_block(img, (0, cy - band * 0.7, W * 0.6, cy + band * 0.3), accent)
    d = ImageDraw.Draw(img)
    # bottom grid: a bar, the date and the intro on the left; name, colorway, a bar and the logo on the right
    y0 = bottom + 2 * u
    d.rectangle([m, y0, m + 25 * u, y0 + 1.4 * u], fill=ink)
    y1 = y0 + 6 * u
    text(d, (m, y1), datetime.date.today().strftime('%d.%m.%Y'), brand.font('text', 3.3 * u), ink)
    paragraph(d, (m, y1 + 5 * u), brand.copy.get('intro', ''), brand.font('text', 1.55 * u), ink, 38 * u)
    col = 58 * u
    text(d, (col, y1), spec['name'].upper(), mono_b, ink)
    text(d, (col, y1 + 2.1 * u), ctx['tagline'], mono, ink)
    text(d, (col + 20 * u, y1), 'COLORWAY', mono_b, ink)
    text(d, (col + 20 * u, y1 + 2.1 * u), ctx['colorway'].replace('-', ' ').upper(), mono, ink)
    d.rectangle([col, y1 + 7 * u, col + 25 * u, y1 + 8.4 * u], fill=ink)
    logo(img, brand, col, H - m - 3.4 * u, 3.4 * u, ink)
    return img


def spread(brand, spec, product, W, H, ctx):
    """A landing-page spread: logo and small navigation on top, an introduction, the name huge at the bottom left,
    the product large on the right, and a signal band along the bottom."""
    t = brand.spec['templates']['spread']
    ink, accent = brand.color(t['ink']), brand.color(t['accent'])
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    d = ImageDraw.Draw(img)
    u = W / 100
    m = 5 * u
    logo(img, brand, m, m, 3 * u, ink)
    nav = brand.font('text', 1.35 * u)
    x = W - m
    for item in reversed(brand.copy.get('nav', [])):
        w, _ = text(d, (x, m + 0.6 * u), '↗', nav, accent, 'ra')
        w2, _ = text(d, (x - w - 0.6 * u, m + 0.6 * u), item, nav, ink, 'ra')
        x -= w + w2 + 4 * u
    for i in range(3):  # thin diagonals behind the product
        o = i * 2.2 * u
        d.line([(W - m + o * 0.2, m * 2.4 + o), (W * 0.52 + o, H * 0.62 + o)], fill=brand.color('ink'), width=1)
    band = H * 0.035
    d.rectangle([m, H - band - 1.5 * u, W - m, H - 1.5 * u], fill=accent)
    p = fit(product, W * 0.4, H * 0.8)  # stays below the navigation
    img.paste(p, (int(W * 0.7 - p.width / 2), int(H - 1.5 * u - band * 0.3 - p.height)), p)
    d = ImageDraw.Draw(img)
    y = H * 0.27
    _, h = text(d, (m, y), f"Introducing {spec['name']}", brand.font('medium', 3.2 * u), ink)
    ph = paragraph(d, (m, y + h + 2.5 * u), brand.copy.get('intro', ''), brand.font('text', 1.3 * u), ink, 33 * u)
    ly = y + h + 2.5 * u + ph + 1.8 * u
    lw, lh = text(d, (m, ly), 'explore →', brand.font('text', 1.8 * u), accent)
    d.line([m, ly + lh + 0.8 * u, m + lw, ly + lh + 0.8 * u], fill=accent, width=max(1, int(0.15 * u)))
    f = fit_font(d, brand, 'display', spec['name'], W * 0.5, H * 0.24)
    text(d, (m - 0.4 * u, H - band - 4.5 * u), spec['name'], f, brand.color('black'), 'lb')
    return img


def specsheet(brand, spec, product, W, H, ctx):
    """A spec sheet on a card: two views of the product, the line-up of colorways with the current one marked,
    a buy block, and the tagline set in mono as a technical label."""
    t = brand.spec['templates']['specsheet']
    ink, accent, card = brand.color(t['ink']), brand.color(t['accent']), brand.color(t['card'])
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    d = ImageDraw.Draw(img)
    u = W / 100
    m = 4 * u
    d.rounded_rectangle([m, m, W - m, H - m], radius=1.2 * u, fill=card)
    split_x, split_y = W * 0.72, H * 0.64
    line = brand.color('stone')
    d.line([split_x, m, split_x, H - m], fill=line, width=1)
    d.line([m, split_y, W - m, split_y], fill=line, width=1)
    logo(img, brand, m + 3 * u, m + 3 * u, 2.6 * u, ink)
    views = [product] + ([ctx['product2']] if ctx.get('product2') else [])
    fitted = [fit(v, (split_x - m) * 0.38, (split_y - m) * 0.7) for v in views]
    gap = 5 * u
    total = sum(v.width for v in fitted) + gap * (len(fitted) - 1)
    x = m + (split_x - m - total) / 2 + 3 * u
    for v in fitted:
        img.paste(v, (int(x), int(m + (split_y - m - v.height) / 2 + 2 * u)), v)
        x += v.width + gap
    d = ImageDraw.Draw(img)
    rx = split_x + 2.5 * u
    rw = W - m - rx - 2.5 * u
    paragraph(d, (rx, m + 3 * u), f"THE {spec['name'].upper()}. {spec.get('category', '').upper()}.", brand.font('mono', 1.1 * u), ink, rw)
    row = brand.font('mono', 1.2 * u)
    y = split_y + 3 * u
    for cw in list(spec.get('colorways', {}))[:6]:
        label = cw.replace('-', '_').upper()
        if cw == ctx['colorway']:
            d.rectangle([rx - 0.8 * u, y - 0.5 * u, rx + rw + 0.8 * u, y + 2.1 * u], fill=accent)
            text(d, (rx, y), '>>> ' + label, row, brand.color('white'))
        else:
            text(d, (rx, y), label, row, ink)
        y += 3 * u
    text(d, (rx, H - m - 4 * u), 'LOAD_MORE', row, accent)
    bx, by = m + 3 * u, split_y + 4 * u
    bs = (H - m - split_y) - 8 * u
    d.rounded_rectangle([bx, by, bx + bs * 0.8, by + bs], radius=1 * u, fill=accent)
    text(d, (bx + 1.5 * u, by + 1.5 * u), '>>>', brand.font('mono_bold', 1.6 * u), brand.color('white'))
    text(d, (bx + 1.5 * u, by + bs - 1.5 * u), 'BUY NOW', brand.font('mono_bold', 1.1 * u), brand.color('white'), 'lb')
    words = ctx['tagline'].upper().rstrip('.').replace('.', '').split()
    half = math.ceil(len(words) / 2)
    lines = ['_'.join(words[:half]), '_'.join(words[half:])] if len(words) > 2 else ['_'.join(words)]
    lf = fit_font(d, brand, 'mono_bold', max(lines, key=len), split_x - bx - bs * 0.8 - 8 * u, 5.2 * u)
    ty = by + (bs - len(lines) * lf.size * 1.15) / 2
    for i, s in enumerate(lines):
        d.text((bx + bs * 0.8 + 5 * u, ty + i * lf.size * 1.15), s, font=lf, fill=brand.color('black'))
    return img


TEMPLATES = {'poster': poster, 'spread': spread, 'specsheet': specsheet}

if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    brand_dir, product_dir, out = args[:3]
    brand = Brand(brand_dir)
    spec = json.load(open(os.path.join(product_dir, 'product.json'), encoding='utf-8'))
    template, fmt = opt('--template', 'poster'), opt('--format', 'portrait')
    W, H = FORMATS[fmt]
    ctx = {'tagline': opt('--tagline', brand.copy['taglines'][0]), 'colorway': opt('--colorway', next(iter(spec['colorways'])))}
    if opt('--image2'):
        ctx['product2'] = load_product(opt('--image2'), opt('--mask2'))
    piece = TEMPLATES[template](brand, spec, load_product(opt('--image'), opt('--mask')), W, H, ctx)
    os.makedirs(out, exist_ok=True)
    name = opt('--name', f'{template}-{fmt}')
    piece.save(os.path.join(out, f'{name}.png'))
    print(os.path.join(out, f'{name}.png'))
