# Stage - Layout. A product image + a brand -> finished campaign pieces, with real type, colours and logo.
# The type is set here, never by the image model: generated text is unreliable, and brand type has to be exact.
# Usage: py pipeline/layout.py <brand dir> <product dir> <product image.png> <out dir> [--template split|centered] [--format ...]
#   the product image is an RGBA cut-out: a beauty pass for now, a ComfyUI render later
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FORMATS = {'landscape': (1200, 628), 'square': (1080, 1080), 'portrait': (1080, 1350), 'story': (1080, 1920)}
DEFAULT_TEMPLATE = {'landscape': 'split', 'square': 'centered', 'portrait': 'centered', 'story': 'centered'}


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Brand:
    def __init__(self, folder):
        self.dir = folder
        self.spec = json.load(open(os.path.join(folder, 'brand.json'), encoding='utf-8'))
        self.colors = {k: hex_rgb(v) for k, v in self.spec['colors'].items()}

    def font(self, role, size):
        for path in self.spec['fonts'][role]:
            full = path if os.path.isabs(path) else os.path.join(self.dir, path)
            for candidate in (full, path):
                try:
                    return ImageFont.truetype(candidate, size)
                except OSError:
                    continue
        return ImageFont.load_default(size)

    def color(self, name):
        return self.colors.get(name) or hex_rgb(name)


def cutout(path):
    """The product alone, trimmed. When a passes mask sits next to the image, it cuts the product clean:
    the contact shadow belongs to the studio floor, not to a layout with its own background."""
    im = Image.open(path).convert('RGBA')
    mask = os.path.join(os.path.dirname(path), 'mask.png')
    if os.path.exists(mask):
        m = Image.open(mask).convert('L').resize(im.size).filter(ImageFilter.GaussianBlur(0.6))
        im.putalpha(m)
    box = im.getchannel('A').point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(box)


def text_size(draw, text, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t, l, t


def draw_logo(img, brand, x, y, height, color, anchor='left'):
    """The wordmark with its half-sun, `height` tall, placed by its left or centre."""
    d = ImageDraw.Draw(img)
    f = brand.font('display', int(height * 1.25))
    w, h, l, t = text_size(d, brand.spec['logo']['text'], f)
    mark = height * 1.1
    total = mark + height * 0.35 + w
    x0 = x - total / 2 if anchor == 'center' else x
    # half sun: a semicircle sitting on a line, the "after glow" of a sunset
    cy = y + height * 0.78
    d.pieslice([x0, cy - mark / 2, x0 + mark, cy + mark / 2], 180, 360, fill=color)
    d.rectangle([x0 - mark * 0.08, cy + height * 0.08, x0 + mark * 1.08, cy + height * 0.16], fill=color)
    d.text((x0 + mark + height * 0.35 - l, y - t + (height - h) * 0.5), brand.spec['logo']['text'], font=f, fill=color)


def fit_font(draw, brand, role, text, max_w, max_h):
    size = int(max_h)
    while size > 8:
        f = brand.font(role, size)
        w, h, _, _ = text_size(draw, text, f)
        if w <= max_w and h <= max_h:
            return f
        size = int(size * 0.94)
    return brand.font(role, 8)


def wrap(draw, text, font, max_w):
    lines, cur = [], ''
    for word in text.split():
        trial = (cur + ' ' + word).strip()
        if text_size(draw, trial, font)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def split(brand, name, tagline, product, W, H):
    """Title big on the left, tagline top right, logo bottom left, the product bleeding off the bottom right."""
    t = brand.spec['templates']['split']
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    d = ImageDraw.Draw(img)
    m = int(min(W, H) * 0.075)
    f = fit_font(d, brand, 'display', name, W * 0.52, H * 0.34)
    w, h, l, top = text_size(d, name, f)
    d.text((m - l, m - top), name, font=f, fill=brand.color(t['title']))
    ft = brand.font('text', int(H * 0.068))
    for i, line in enumerate(wrap(d, tagline, ft, W * 0.24)):
        lw, lh, ll, lt = text_size(d, line, ft)
        d.text((W - m - lw - ll, m - lt + i * H * 0.085), line, font=ft, fill=brand.color(t['tagline']))
    draw_logo(img, brand, m, H - m - H * 0.06, H * 0.06, brand.color(t['logo']))
    scale = H * 1.05 / product.height
    p = product.resize((int(product.width * scale), int(product.height * scale)), Image.LANCZOS)
    img.paste(p, (int(W * 0.66 - p.width / 2), int(H * 0.30)), p)
    return img


def centered(brand, name, tagline, product, W, H):
    """Logo on top, title and tagline centred, a generated-looking backdrop, the product rising from the bottom."""
    t = brand.spec['templates']['centered']
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    # backdrop: one big soft sphere, the colour field the image model will later paint for real
    a, b = (brand.color(c) for c in t['backdrop'])
    r = int(max(W * 0.62, H * 0.5))  # tall formats get a bigger sphere, so the type always sits on colour
    cx, cy = W // 2, int(H * 0.55)
    grad = Image.new('RGB', (2 * r, 2 * r))
    gd = ImageDraw.Draw(grad)
    for i in range(2 * r):
        k = i / (2 * r)
        k = k * k * (3 - 2 * k)
        gd.line([(0, i), (2 * r, i)], fill=tuple(int(a[j] * (1 - k) + b[j] * k) for j in range(3)))
    mask = Image.new('L', (2 * r, 2 * r), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    img.paste(grad, (cx - r, cy - r), mask.filter(ImageFilter.GaussianBlur(r * 0.01)))
    d = ImageDraw.Draw(img)
    m = int(min(W, H) * 0.07)
    draw_logo(img, brand, W / 2, H * 0.075, H * 0.035 * (1080 / H) ** 0.3 * (H / W) ** 0.2, brand.color(t['logo']), 'center')
    y = H * 0.15
    title_h = min(H * 0.16, W * 0.2)
    chord = 2 * math.sqrt(max(r * r - (cy - y - title_h / 2) ** 2, 0))  # the sphere's width at the title's height
    f = fit_font(d, brand, 'display', name, min(W - 2 * m, chord * 0.86), title_h)
    w, h, l, top = text_size(d, name, f)
    d.text(((W - w) / 2 - l, y - top), name, font=f, fill=brand.color(t['title']))
    ft = brand.font('text', int(h * 0.36))
    tw, th, tl, tt = text_size(d, tagline, ft)
    d.text(((W - tw) / 2 - tl, y + h * 1.25 - tt), tagline, font=ft, fill=brand.color(t['tagline']))
    scale = W * min(0.5 * (H / W) ** 0.6, 0.72) / product.width  # taller formats show more product
    p = product.resize((int(product.width * scale), int(product.height * scale)), Image.LANCZOS)
    img.paste(p, (int((W - p.width) / 2), int(max(y + h * 2.3, H - p.height * 0.86))), p)
    return img


def cover(img, W, H, focus=(0.5, 0.5)):
    """Scale to fill W x H and crop around `focus` (fractions of the image)."""
    k = max(W / img.width, H / img.height)
    im = img.resize((math.ceil(img.width * k), math.ceil(img.height * k)), Image.LANCZOS)
    x = min(max(int(im.width * focus[0] - W / 2), 0), im.width - W)
    y = min(max(int(im.height * focus[1] - H / 2), 0), im.height - H)
    return im.crop((x, y, x + W, y + H))


def scrim(img, height, color, strength=0.55):
    """A soft band of colour from the top edge down, so type reads on any photo."""
    band = Image.new('L', (1, height))
    for i in range(height):
        band.putpixel((0, i), int(255 * strength * (1 - i / height) ** 1.6))
    over = Image.new('RGB', img.size, color)
    mask = Image.new('L', img.size, 0)
    mask.paste(band.resize((img.width, height)), (0, 0))
    return Image.composite(over, img, mask)


def photo(brand, name, tagline, product, W, H):
    """The generated scene full bleed, the type on a soft scrim at the top: logo, title, tagline."""
    t = brand.spec['templates'].get('photo', {'scrim': 'ink', 'title': 'cream', 'tagline': 'cream', 'logo': 'cream'})
    img = scrim(cover(product, W, H, (0.5, 0.6)), int(H * 0.42), brand.color(t['scrim']))
    d = ImageDraw.Draw(img)
    m = int(min(W, H) * 0.07)
    draw_logo(img, brand, W / 2, H * 0.05, min(W, H) * 0.035, brand.color(t['logo']), 'center')
    f = fit_font(d, brand, 'display', name, W - 2 * m, min(H * 0.13, W * 0.17))
    w, h, l, top = text_size(d, name, f)
    y = H * 0.05 + min(W, H) * 0.08
    d.text(((W - w) / 2 - l, y - top), name, font=f, fill=brand.color(t['title']))
    ft = brand.font('text', int(h * 0.34))
    tw, th, tl, tt = text_size(d, tagline, ft)
    d.text(((W - tw) / 2 - tl, y + h * 1.22 - tt), tagline, font=ft, fill=brand.color(t['tagline']))
    return img


def split_photo(brand, name, tagline, product, W, H):
    """Type on the brand colour on the left, the generated scene on the right, like a print spread."""
    t = brand.spec['templates']['split']
    img = Image.new('RGB', (W, H), brand.color(t['background']))
    pw = int(W * 0.5)
    img.paste(cover(product, pw, H, (0.5, 0.55)), (W - pw, 0))
    d = ImageDraw.Draw(img)
    m = int(min(W, H) * 0.075)
    f = fit_font(d, brand, 'display', name, W - pw - 2 * m, H * 0.3)
    w, h, l, top = text_size(d, name, f)
    d.text((m - l, m - top), name, font=f, fill=brand.color(t['title']))
    ft = brand.font('text', int(H * 0.06))
    for i, line in enumerate(wrap(d, tagline, ft, W - pw - 2 * m)):
        lw, lh, ll, lt = text_size(d, line, ft)
        d.text((m - ll, m + h * 1.25 - lt + i * H * 0.08), line, font=ft, fill=brand.color(t['tagline']))
    draw_logo(img, brand, m, H - m - H * 0.06, H * 0.06, brand.color(t['logo']))
    return img


TEMPLATES = {'split': split, 'centered': centered, 'photo': photo, 'split-photo': split_photo}
PHOTO_TEMPLATE = {'landscape': 'split-photo', 'square': 'photo', 'portrait': 'photo', 'story': 'photo'}

if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    brand_dir, product_dir, image, out = args[:4]
    brand = Brand(brand_dir)
    spec = json.load(open(os.path.join(product_dir, 'product.json'), encoding='utf-8'))
    fmt = opt('--format', 'landscape')
    is_cutout = Image.open(image).mode == 'RGBA'  # a studio cut-out, or a generated scene
    template = opt('--template', (DEFAULT_TEMPLATE if is_cutout else PHOTO_TEMPLATE)[fmt])
    tagline = opt('--tagline', brand.spec['taglines'][0])
    W, H = FORMATS[fmt]
    src = cutout(image) if is_cutout else Image.open(image).convert('RGB')
    piece = TEMPLATES[template](brand, spec['name'], tagline, src, W, H)
    os.makedirs(out, exist_ok=True)
    name = opt('--name', f'{template}-{fmt}')
    piece.save(os.path.join(out, f'{name}.png'))
    print(os.path.join(out, f'{name}.png'))
