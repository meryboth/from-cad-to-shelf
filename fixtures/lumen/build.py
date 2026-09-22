# LUMEN, an original Game Boy-style handheld, built from code so the geometry is exact (our "CAD").
# Usage: blender -b -P fixtures/lumen/build.py -- [colorway|all] [--front]
#        blender -b -P fixtures/lumen/build.py -- --export products/lumen   (the product, as the pipeline takes it)
# Units are metres at real size: the body is 90 x 148 x 30 mm. The front faces -Y, up is +Z.
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)

# ---------- the design, in numbers ----------
W, H, D = 0.090, 0.148, 0.030          # body
R_TOP, R_BOTTOM = 0.008, 0.020         # corner radii: soft top, generous bottom
SEAM = 0.0005                          # gap between front and back shells

# two editions, in the meridian palette: a white one, and one in the brand's signal orange (#FF5E2C)
COLORWAYS = {
    'white': dict(body=(0.8469, 0.8308, 0.807), rough=0.42, clear=False, ab=(1.0, 0.1119, 0.0252), dpad=(0.0545, 0.0545, 0.0666),
                  pills=(0.7454, 0.7011, 0.6654), bezel=(0.0545, 0.0545, 0.0666), screen=(0.55, 0.62, 0.30), cart=(0.7454, 0.7011, 0.6654)),
    'signal-orange': dict(body=(1.0, 0.1119, 0.0252), rough=0.45, clear=False, ab=(0.956, 0.956, 0.9387), dpad=(0.956, 0.956, 0.9387),
                          pills=(0.0545, 0.0545, 0.0666), bezel=(0.0103, 0.0103, 0.0116), screen=(0.55, 0.62, 0.30), cart=(0.8469, 0.8308, 0.807)),
}


# ---------- geometry helpers ----------
def rounded_profile(w, h, radii, seg=10, cx=0.0, cz=0.0):
    """Rounded rectangle in the XZ plane; radii = (top-left, top-right, bottom-right, bottom-left)."""
    tl, tr, br, bl = radii
    corners = [((w / 2 - tr, h / 2 - tr), tr, 0), ((-w / 2 + tl, h / 2 - tl), tl, 90),
               ((-w / 2 + bl, -h / 2 + bl), bl, 180), ((w / 2 - br, -h / 2 + br), br, 270)]
    pts = []
    for (x, z), r, a0 in corners:
        n = seg if r > 0 else 0
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / max(n, 1))
            pts.append((cx + x + r * math.cos(a), cz + z + r * math.sin(a)))
    return pts


def prism(name, profile, y0, depth, mat, bevel=0.0006, index=0):
    """Extrude an XZ profile from y0 (front) to y0 + depth (back)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    front = [bm.verts.new((x, y0, z)) for x, z in profile]
    back = [bm.verts.new((x, y0 + depth, z)) for x, z in profile]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((front[i], front[j], back[j], back[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat)
    ob.pass_index = index
    if bevel:
        m = ob.modifiers.new('bevel', 'BEVEL')
        m.width, m.segments, m.limit_method, m.angle_limit = bevel, 4, 'ANGLE', math.radians(50)
    smooth(ob)
    return ob


def smooth(ob):
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))


def cylinder(name, r, depth, x, y0, z, mat, index=0, bevel=0.0005, seg=48):
    return prism(name, [(x + r * math.cos(2 * math.pi * i / seg), z + r * math.sin(2 * math.pi * i / seg)) for i in range(seg)],
                 y0, depth, mat, bevel, index)


def pill(name, length, thick, x, z, angle, y0, depth, mat, index=0):
    ob = prism(name, rounded_profile(length, thick, (thick / 2 - 1e-5,) * 4, 8), y0, depth, mat, 0.0004, index)
    ob.location = (x, 0, z)
    ob.rotation_euler = (0, math.radians(angle), 0)
    return ob


def material(name, color, rough=0.45, emit=0.0, clear=False, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    if clear:
        p.inputs['Transmission Weight'].default_value = 0.92
        p.inputs['IOR'].default_value = 1.49
    if emit:
        p.inputs['Emission Color'].default_value = (*color, 1)
        p.inputs['Emission Strength'].default_value = emit
    return m


# ---------- the screen: a dot-matrix boot screen, drawn from code ----------
FONT = {  # 5 x 7 pixel letters
    'L': ['10000'] * 6 + ['11111'], 'U': ['10001'] * 6 + ['01110'], 'M': ['10001', '11011', '10101', '10001', '10001', '10001', '10001'],
    'E': ['11111', '10000', '10000', '11110', '10000', '10000', '11111'], 'N': ['10001', '11001', '10101', '10011', '10001', '10001', '10001'],
}


def boot_screen(tint):
    """160 x 144 pixels, like the handhelds it nods to: the wordmark, a sun and hills."""
    w, h = 160, 144
    px = [[0.0] * w for _ in range(h)]  # 0 = background, 1 = mid, 2 = dark
    x = 40
    for ch in 'LUMEN':
        for r, row in enumerate(FONT[ch]):
            for col, bit in enumerate(row):
                if bit == '1':
                    for dy in range(2):
                        for dx in range(2):
                            px[40 + r * 2 + dy][x + col * 2 + dx] = 2
        x += 16
    for yy in range(h):
        for xx in range(w):
            if (xx - 118) ** 2 + (yy - 78) ** 2 < 90:
                px[yy][xx] = max(px[yy][xx], 1)
            hill = 108 + 10 * math.sin(xx / 17) + 5 * math.sin(xx / 7 + 1)
            if yy > hill:
                px[yy][xx] = 2 if yy > hill + 16 else 1
    levels = [[v * 1.0 for v in tint], [v * 0.62 for v in tint], [v * 0.25 for v in tint]]
    img = bpy.data.images.new('lcd', w, h)
    flat = []
    for yy in range(h - 1, -1, -1):  # Blender images start at the bottom row
        for xx in range(w):
            flat += [*levels[int(px[yy][xx])], 1.0]
    img.pixels = flat
    img.filepath_raw = os.path.join(OUT, 'lcd.png')
    img.file_format = 'PNG'
    img.save()
    img.pack()
    return img


def screen_material(tint):
    m = material('screen', (1, 1, 1), 0.2)
    nt = m.node_tree
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = boot_screen(tint)
    tex.interpolation = 'Closest'  # crisp pixels
    p = nt.nodes['Principled BSDF']
    nt.links.new(tex.outputs['Color'], p.inputs['Base Color'])
    nt.links.new(tex.outputs['Color'], p.inputs['Emission Color'])
    p.inputs['Emission Strength'].default_value = 0.35
    return m


def planar_uv(ob):
    """Front projection: the screen image lands flat on the display face."""
    me = ob.data
    uv = me.uv_layers.new(name='UVMap')
    xs = [v.co.x for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = ((co.x - min(xs)) / (max(xs) - min(xs)), (co.z - min(zs)) / (max(zs) - min(zs)))


# ---------- the console ----------
def build(cw):
    c = COLORWAYS[cw]
    body = material('body', c['body'], c['rough'], clear=c['clear'])
    bezel = material('bezel', c['bezel'], 0.25)
    screen = screen_material(c['screen'])
    dpad = material('dpad', c['dpad'], 0.4)
    ab = material('ab', c['ab'], 0.3)
    pills = material('pills', c['pills'], 0.7)
    dark = material('dark', (0.02, 0.02, 0.025), 0.6)
    led = material('led', (1.0, 0.15, 0.1), 0.3, emit=4)
    cart = material('cart', c['cart'], 0.5)
    label = material('label', (0.93, 0.93, 0.90), 0.6)
    pcb = material('pcb', (0.05, 0.28, 0.16), 0.5)
    gold = material('gold', (0.85, 0.65, 0.25), 0.25, metal=1.0)

    radii = (R_TOP, R_TOP, R_BOTTOM, R_BOTTOM)
    prism('body_front', rounded_profile(W, H, radii), 0.0, D / 2 - SEAM / 2, body, 0.0025, 1)
    prism('body_back', rounded_profile(W, H, radii), D / 2 + SEAM / 2, D / 2 - SEAM / 2, body, 0.0025, 1)
    # inside, so the clear edition has something to show
    prism('pcb', rounded_profile(W - 0.012, H - 0.02, (0.004,) * 4), 0.012, 0.0016, pcb, 0, 5)
    for i in range(6):
        cylinder(f'chip_{i}', 0.004, 0.001, -0.025 + 0.01 * i, 0.0112, 0.012 + 0.03 * (i % 2), gold, 5, 0)

    # screen: a dark glass bezel, the display, the power light and the wordmark
    bz = 0.030
    prism('bezel', rounded_profile(0.078, 0.066, (0.005, 0.005, 0.014, 0.005)), -0.0010, 0.0014, bezel, 0.0004, 2)
    for o in bpy.data.objects:
        if o.name == 'bezel':
            o.location.z = bz
    s = prism('screen', rounded_profile(0.050, 0.044, (0.0008,) * 4), -0.0013, 0.0004, screen, 0, 2)
    planar_uv(s)
    s.location = (0.002, 0, bz + 0.002)
    cylinder('power_led', 0.0012, 0.0006, -0.031, -0.0014, bz + 0.008, led, 2, 0)
    bpy.ops.object.text_add(location=(-0.036, -0.0003, -0.0105), rotation=(math.radians(90), 0, 0))
    t = bpy.context.object
    t.name = 'wordmark'
    t.data.body = 'LUMEN'
    t.data.size = 0.0075
    t.data.extrude = 0.00025
    t.data.space_character = 1.25
    t.data.materials.append(bezel)
    t.pass_index = 1

    # controls
    x0, z0, arm, wid = -0.022, -0.033, 0.0125, 0.0045
    cross = [(wid, arm), (-wid, arm), (-wid, wid), (-arm, wid), (-arm, -wid), (-wid, -wid), (-wid, -arm), (wid, -arm),
             (wid, -wid), (arm, -wid), (arm, wid), (wid, wid)]
    cylinder('dpad_well', 0.0175, 0.0006, x0, -0.0005, z0, (body if c['clear'] else material('well', [v * 0.85 for v in c['body']], 0.6)), 3, 0.0003)
    prism('dpad', [(x0 + x, z0 + z) for x, z in cross], -0.0042, 0.004, dpad, 0.0007, 3)
    cylinder('button_b', 0.0056, 0.0045, 0.019, -0.0042, -0.038, ab, 3, 0.0009)
    cylinder('button_a', 0.0056, 0.0045, 0.033, -0.0042, -0.027, ab, 3, 0.0009)
    pill('select', 0.012, 0.0038, -0.009, -0.058, 22, -0.0022, 0.0024, pills, 3)
    pill('start', 0.012, 0.0038, 0.008, -0.058, 22, -0.0022, 0.0024, pills, 3)
    # speaker: a grid of holes, bottom right
    for i in range(5):
        for j in range(5):
            if (i - 2) ** 2 + (j - 2) ** 2 <= 5:
                cylinder(f'speaker_{i}{j}', 0.0009, 0.0003, 0.026 + 0.0035 * i, -0.0001, -0.062 + 0.0035 * j, dark, 1, 0, 16)
    # the volume wheel on the right side, and the cartridge in the back
    v = cylinder('volume', 0.0065, 0.004, 0, 0, 0, dark, 3, 0.0005)
    v.rotation_euler = (0, 0, math.radians(90))
    v.location = (W / 2 + 0.0019, D / 2 + 0.002, 0.024)
    prism('cartridge', rounded_profile(0.058, 0.060, (0.002, 0.002, 0.002, 0.002)), D - 0.0085, 0.0075, cart, 0.0006, 4) \
        .location.z = H / 2 - 0.026
    prism('cart_label', rounded_profile(0.046, 0.034, (0.002,) * 4), D - 0.0005, 0.0004, label, 0, 4).location.z = H / 2 - 0.028


# ---------- the photo studio ----------
def studio(front=False):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 64
    sc.cycles.use_denoising = True
    sc.render.resolution_x = sc.render.resolution_y = 1000
    sc.view_settings.view_transform = 'AgX'
    for look in ('AgX - Punchy', 'Punchy'):  # the name changed between versions
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            pass
    sc.view_layers[0].use_pass_object_index = True
    world = bpy.data.worlds.new('world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.85, 0.85, 0.87, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.25
    sc.world = world
    floor = material('floor', (0.62, 0.62, 0.60), 0.8)
    bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 0.3, -H / 2))
    bpy.context.object.data.materials.append(floor)
    bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 0.6, 0), rotation=(math.radians(90), 0, 0))
    bpy.context.object.data.materials.append(floor)

    def area(loc, energy, size):
        bpy.ops.object.light_add(type='AREA', location=loc)
        l = bpy.context.object
        l.data.energy, l.data.size = energy, size
        l.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    area((-0.35, -0.45, 0.35), 7, 0.5)    # key
    area((0.45, -0.25, 0.15), 2, 0.4)     # fill
    area((0.2, 0.4, 0.45), 4, 0.3)        # rim

    bpy.ops.object.camera_add()
    cam = bpy.context.object
    sc.camera = cam
    if front:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = 0.19
        cam.location = (0, -0.5, 0)
        cam.rotation_euler = (math.radians(90), 0, 0)
    else:
        cam.data.lens = 85
        cam.location = (-0.20, -0.42, 0.14)
        target = Vector((0.004, 0.01, -0.004))
        cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def export_product(folder):
    """Write LUMEN the way the pipeline takes any product: product.glb plus product.json."""
    os.makedirs(folder, exist_ok=True)
    reset()
    build('white')
    bpy.ops.export_scene.gltf(filepath=os.path.join(folder, 'product.glb'), export_apply=True)
    part = {'body': 'body', 'well': None, 'bezel': 'bezel', 'screen': 'screen', 'dpad': 'dpad', 'ab': 'ab',
            'pills': 'pills', 'cart': 'cart'}
    colorways = {}
    for cw, c in COLORWAYS.items():
        mats = {}
        for mat, key in part.items():
            if mat == 'well':
                mats[mat] = dict(mats['body']) if c['clear'] else {'color': [v * 0.85 for v in c['body']], 'roughness': 0.6}
                continue
            mats[mat] = {'color': list(c[key])}
        mats['body'].update(roughness=c['rough'], transmission=0.92 if c['clear'] else 0.0)
        mats['screen'] = {'color': [1, 1, 1], 'roughness': 0.2, 'coat': 1.0}  # the LCD is a texture; a glass cover on top
        mats['bezel'].update(coat=0.6)
        colorways[cw] = mats
    spec = {
        'name': 'LUMEN',
        'code': 'L-01',
        'year': '2026',
        'category': 'retro handheld game console',
        'fictional': True,
        'size_mm': [90, 148, 30],
        'facts': ['A handheld game console with a retro design', 'Backlit square screen', 'D-pad, A and B buttons, Start and Select',
                  'Cartridge slot on the back', 'Volume wheel on the right side', 'Built-in speaker',
                  'Two colorways: White and Signal Orange'],
        'protected_materials': ['bezel', 'screen', 'dpad', 'ab', 'pills'],
        'hero_material': 'body',  # the colour the QA checks the photos against
        'exact_materials': ['screen', 'bezel'],  # the LCD and the wordmark: exact; the buttons: colour only
        'colorways': colorways,
    }
    json.dump(spec, open(os.path.join(folder, 'product.json'), 'w', encoding='utf-8'), indent=2)
    print('exported', folder)


args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if '--export' in args:
    export_product(os.path.abspath(args[args.index('--export') + 1]))
    sys.exit(0)
front = '--front' in args
names = [a for a in args if not a.startswith('--')] or ['white']
if names == ['all']:
    names = list(COLORWAYS)
for cw in names:
    reset()
    build(cw)
    if cw == 'white' and not front:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'lumen.blend'))
        bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, 'lumen.glb'), export_apply=True)
    studio(front)
    bpy.context.scene.render.filepath = os.path.join(OUT, f'{cw}-{"front" if front else "hero"}.png')
    bpy.ops.render.render(write_still=True)
    print('rendered', cw)
