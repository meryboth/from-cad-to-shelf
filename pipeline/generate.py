# Stage - Generate. The passes of one view + a scene -> a photoreal product image, through ComfyUI.
# Several backends behind one interface, so they can be compared on the same product, view and scene:
#   local-sdxl       RealVisXL + ControlNet Union (depth, normals) on your GPU. Free.
#   nano-banana      Gemini 2.5 Flash Image, edits the studio reference into the scene. Paid, through Comfy.
#   nano-banana-2    Gemini 3.1 Flash Image. Paid.
#   nano-banana-pro  Gemini 3 Pro Image. Paid.
# Paid backends only run with --spend and a COMFY_API_KEY, and every call is written to runs/<product>/generate/ledger.jsonl.
#
# Usage: py pipeline/generate.py <product dir> <brand dir> <passes dir> --backend B --view V --colorway C --scene S
#          [--format square|portrait|story|landscape] [--seed N] [--spend]
import io
import json
import os
import sys
import time
import urllib.request
import uuid

from PIL import Image

COMFY = os.environ.get('COMFY_URL', 'http://127.0.0.1:8000')
# the Comfy API key: an environment variable, or a one-line file in your home folder. Never in this repo.
KEY_FILE = os.path.join(os.path.expanduser('~'), '.comfy_api_key')
if not os.environ.get('COMFY_API_KEY') and os.path.exists(KEY_FILE):
    os.environ['COMFY_API_KEY'] = open(KEY_FILE, encoding='utf-8').read().strip()
PRICES = {'local-sdxl': 0.0, 'nano-banana': 0.039, 'nano-banana-2': 0.0835, 'nano-banana-pro': 0.1608}  # USD per 1K image, from the node badges


# ---------- a tiny ComfyUI client ----------
def upload(img, name):
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n'
            ).encode() + buf.getvalue() + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f'{COMFY}/upload/image', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'})
    return json.load(urllib.request.urlopen(req))['name']


def run(graph):
    body = {'prompt': graph, 'client_id': 'cad-to-shelf'}
    if os.environ.get('COMFY_API_KEY'):
        # partner nodes (Gemini and the rest) bill a Comfy account; a graph sent by script carries its key itself,
        # since the sign-in of the ComfyUI window only applies to graphs queued from that window
        body['extra_data'] = {'api_key_comfy_org': os.environ['COMFY_API_KEY']}
    req = urllib.request.Request(f'{COMFY}/prompt', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    try:
        pid = json.load(urllib.request.urlopen(req))['prompt_id']
    except urllib.error.HTTPError as err:
        raise SystemExit(f'ComfyUI refused the graph: {err.read().decode()[:1500]}')
    while True:
        time.sleep(2)
        h = json.load(urllib.request.urlopen(f'{COMFY}/history/{pid}'))
        if pid in h:
            status = h[pid].get('status', {})
            if status.get('status_str') == 'error':
                msgs = [m for m in status.get('messages', []) if m[0] == 'execution_error']
                raise SystemExit(f'ComfyUI failed: {json.dumps(msgs)[:1500]}')
            for out in h[pid]['outputs'].values():
                for im in out.get('images', []):
                    q = urllib.parse.urlencode({'filename': im['filename'], 'subfolder': im['subfolder'], 'type': im['type']})
                    return Image.open(io.BytesIO(urllib.request.urlopen(f'{COMFY}/view?{q}').read())).convert('RGB')
            raise SystemExit('ComfyUI finished without an image')


# ---------- inputs ----------
def on_grey(path, grey=(200, 200, 198)):
    """The studio reference on a plain grey, since image models and VAEs do not read transparency."""
    im = Image.open(path).convert('RGBA')
    bg = Image.new('RGBA', im.size, (*grey, 255))
    bg.alpha_composite(im)
    return bg.convert('RGB')


def describe(spec, colorway):
    return f"{spec.get('category', 'product')} called {spec['name']}, {colorway.replace('-', ' ')} colorway"


def finish(img, passes, view, colorway, spec):
    """Everything that has to be true of the product, applied after generation, in order:
    every part gets its spec colour (consistency), then the protected parts come back (screen, logo, buttons)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from consistency import enforce, keep_detail
    img = enforce(img, passes, view, colorway, spec)          # colour of every part, from the spec
    img = keep_detail(img, passes, view, colorway)            # fine detail, from the render
    return lock_protected(img, passes, view, colorway)        # screen and logo, exactly


def lock_protected(img, passes, view, colorway, light=0.2, feather=1.5):
    """Bring the protected parts back from the reference, after generation. Two kinds:
    exact parts (mask_exact: a screen, a logo) are copied as they are; the other protected parts keep the reference's
    colour but take `light` of their lightness from the photo, so they get its light and texture instead of looking
    pasted on. Only for backends that keep the camera: the ControlNet graph does, pixel for pixel."""
    import numpy as np
    from PIL import ImageFilter
    d = os.path.join(passes, view)
    load = lambda n: Image.open(os.path.join(d, n)).convert('L').resize(img.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(feather))
    if not os.path.exists(os.path.join(d, 'mask_protected.png')):
        return img
    ref = on_grey(os.path.join(d, f'beauty_{colorway}.png')).resize(img.size, Image.LANCZOS)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from qa import lab, rgb
    g, r = lab(img), lab(ref)
    r[..., 0] = g[..., 0] * light + r[..., 0] * (1 - light)
    tinted = rgb(r)
    out = Image.composite(tinted, img, load('mask_protected.png'))
    if os.path.exists(os.path.join(d, 'mask_exact.png')):
        out = Image.composite(ref, out, load('mask_exact.png'))
    return out


FAST = '--quality' not in sys.argv
SAMPLING = {True: {'steps': 8, 'cfg': 1.5, 'sampler_name': 'euler', 'scheduler': 'sgm_uniform'},
            False: {'steps': 30, 'cfg': 5.0, 'sampler_name': 'dpmpp_2m_sde', 'scheduler': 'karras'}}


# ---------- backends ----------
def local_sdxl(passes, view, colorway, scene, spec, seed):
    d = os.path.join(passes, view)
    depth = upload(Image.open(os.path.join(d, 'depth.png')).convert('RGB'), f'{spec["name"]}_{view}_depth.png')
    normal = upload(Image.open(os.path.join(d, 'normal.png')).convert('RGB'), f'{spec["name"]}_{view}_normal.png')
    start = upload(on_grey(os.path.join(d, f'beauty_{colorway}.png')), f'{spec["name"]}_{view}_{colorway}.png')
    pos = scene['prompt_template'].format(product=describe(spec, colorway)) if scene.get('prompt_template') else         f"professional product photograph of a {describe(spec, colorway)}, {scene['prompt']}, photorealistic, sharp focus, high detail"
    neg = scene.get('negative', 'cartoon, illustration, 3d render, cgi, plastic toy, deformed, extra buttons, text, watermark, blurry, lowres')
    g = {
        'ckpt': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'RealVisXL_V5.0_fp16.safetensors'}},
        'pos': {'class_type': 'CLIPTextEncode', 'inputs': {'text': pos, 'clip': ['ckpt', 1]}},
        'neg': {'class_type': 'CLIPTextEncode', 'inputs': {'text': neg, 'clip': ['ckpt', 1]}},
        'cn': {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': 'controlnet-union-sdxl-promax.safetensors'}},
        'cn_depth': {'class_type': 'SetUnionControlNetType', 'inputs': {'control_net': ['cn', 0], 'type': 'depth'}},
        'cn_normal': {'class_type': 'SetUnionControlNetType', 'inputs': {'control_net': ['cn', 0], 'type': 'normal'}},
        'img_depth': {'class_type': 'LoadImage', 'inputs': {'image': depth}},
        'img_normal': {'class_type': 'LoadImage', 'inputs': {'image': normal}},
        'img_start': {'class_type': 'LoadImage', 'inputs': {'image': start}},
        'apply_depth': {'class_type': 'ControlNetApplyAdvanced', 'inputs': {
            'positive': ['pos', 0], 'negative': ['neg', 0], 'control_net': ['cn_depth', 0], 'image': ['img_depth', 0],
            'strength': scene.get('depth', 0.75), 'start_percent': 0.0, 'end_percent': scene.get('depth_end', 0.8), 'vae': ['ckpt', 2]}},
        'apply_normal': {'class_type': 'ControlNetApplyAdvanced', 'inputs': {
            'positive': ['apply_depth', 0], 'negative': ['apply_depth', 1], 'control_net': ['cn_normal', 0], 'image': ['img_normal', 0],
            'strength': scene.get('normal', 0.45), 'start_percent': 0.0, 'end_percent': 0.6, 'vae': ['ckpt', 2]}},
        # start from the studio reference, so the colourway survives; the ControlNets hold the shape
        'latent': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['img_start', 0], 'vae': ['ckpt', 2]}},
        'sample': {'class_type': 'KSampler', 'inputs': {
            'model': ['model', 0], 'seed': seed, **SAMPLING[FAST],
            'positive': ['apply_normal', 0], 'negative': ['apply_normal', 1], 'latent_image': ['latent', 0], 'denoise': scene.get('denoise', 0.82)}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['ckpt', 2]}},
        'save': {'class_type': 'SaveImage', 'inputs': {'images': ['decode', 0], 'filename_prefix': 'cad-to-shelf/local'}},
    }
    # SDXL Lightning: the same graph in 8 steps instead of 30 (--quality for the slow, full sampler)
    g['model'] = ({'class_type': 'LoraLoaderModelOnly', 'inputs': {
        'model': ['ckpt', 0], 'lora_name': 'sdxl_lightning_8step_lora.safetensors', 'strength_model': 1.0}} if FAST else
        {'class_type': 'ModelSamplingDiscrete', 'inputs': {'model': ['ckpt', 0], 'sampling': 'eps', 'zsnr': False}})
    return run(g), pos


# a piece is composed for its layout: the right aspect ratio, and calm space where the type goes
FORMATS = {'square': ('1:1', 'top third'), 'portrait': ('4:5', 'top third'), 'story': ('9:16', 'top 30 percent'),
           'landscape': ('1:1', None)}  # the landscape spread puts the photo on one half, a square crop

GEMINI = {'nano-banana': ('GeminiImageNode', 'gemini-2.5-flash-image'),
          'nano-banana-2': ('GeminiImage2Node', 'Nano Banana 2 (Gemini 3.1 Flash Image)'),
          'nano-banana-pro': ('GeminiImage2Node', 'gemini-3-pro-image-preview')}


def gemini(backend, passes, view, colorway, scene, spec, seed, fmt=None):
    node, model = GEMINI[backend]
    ref = upload(on_grey(os.path.join(passes, view, f'beauty_{colorway}.png')), f'{spec["name"]}_{view}_{colorway}.png')
    prompt = (f"This image shows a {describe(spec, colorway)}. Create a professional product photograph of this exact product: "
              f"keep its shape, proportions, colours, buttons, screen and printed text exactly as they are, and keep the camera angle. "
              f"Replace the grey background with this scene: {scene['prompt']}. Photorealistic, natural materials, real lighting "
              f"and reflections on the product that match the scene. No added text or logos.")
    aspect, headroom = FORMATS.get(fmt, ('1:1', None))
    if headroom:
        prompt += (f" Compose it as a campaign photo: the product sits in the lower part of the frame and fully visible, "
                   f"and the {headroom} of the image is calm, empty background with nothing important in it, "
                   f"because a headline will be set there.")
    inputs = {'prompt': prompt, 'model': model, 'seed': seed, 'images': ['ref', 0], 'aspect_ratio': aspect, 'response_modalities': 'IMAGE'}
    if node == 'GeminiImage2Node':
        inputs['resolution'] = '1K'
    g = {'ref': {'class_type': 'LoadImage', 'inputs': {'image': ref}},
         'gen': {'class_type': node, 'inputs': inputs},
         'save': {'class_type': 'SaveImage', 'inputs': {'images': ['gen', 0], 'filename_prefix': f'cad-to-shelf/{backend}'}}}
    return run(g), prompt


if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    product_dir, brand_dir, passes = args[:3]
    backend, view, colorway, scene_id = opt('--backend'), opt('--view'), opt('--colorway'), opt('--scene')
    seed = int(opt('--seed', 7))
    spec = json.load(open(os.path.join(product_dir, 'product.json'), encoding='utf-8'))
    scene = json.load(open(os.path.join(brand_dir, 'scenes.json'), encoding='utf-8'))[scene_id]
    if PRICES[backend] and '--spend' not in args:
        raise SystemExit(f'{backend} costs about ${PRICES[backend]} per image. Add --spend to run it.')
    if PRICES[backend] and not os.environ.get('COMFY_API_KEY'):
        raise SystemExit('Paid backends need a Comfy API key (platform.comfy.org -> API keys), in the COMFY_API_KEY '
                         f'environment variable or in {KEY_FILE}. It is never stored in this repo.')
    t0 = time.time()
    img, prompt = local_sdxl(passes, view, colorway, scene, spec, seed) if backend == 'local-sdxl' else \
        gemini(backend, passes, view, colorway, scene, spec, seed, opt('--format'))
    seconds = round(time.time() - t0, 1)
    raw = img
    if backend == 'local-sdxl' and '--no-lock' not in args:
        img = finish(img, passes, view, colorway, spec)
    if opt('--out'):  # an explicit path, for shots that live outside the generate folder
        out, name = os.path.dirname(os.path.abspath(opt('--out'))), os.path.basename(opt('--out'))[:-4]
    else:
        out = os.path.join(os.path.dirname(os.path.abspath(passes)), 'generate', backend)
        name = f'{view}_{scene_id}_{colorway}_s{seed}' + (f"_{opt('--format')}" if opt('--format') else '')
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, name + '.png'))
    if img is not raw:
        raw.save(os.path.join(out, name + '_raw.png'))  # before the lock, to compare
    ledger = os.path.join(os.path.dirname(os.path.abspath(passes)), 'generate', 'ledger.jsonl')
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    record = {'backend': backend, 'view': view, 'colorway': colorway, 'scene': scene_id, 'seed': seed,
              'format': opt('--format'), 'shot': bool(opt('--out')), 'seconds': seconds,
              'usd': PRICES[backend], 'prompt': prompt, 'file': os.path.relpath(os.path.join(out, name + '.png'), os.path.dirname(ledger)).replace(os.sep, '/'), 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
    with open(ledger, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')
    print(json.dumps({k: record[k] for k in ('file', 'seconds', 'usd')}))
