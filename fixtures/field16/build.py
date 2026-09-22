# FIELD 16, an original pocket camera, built from code so the geometry is exact (our "CAD").
# A nod to the boxy point-and-shoots of the era: a white body with a coloured band across the top, a big ribbed
# dial, a viewfinder and a lens window. No existing brand, logo or type is used; everything here is ours.
# Usage: blender -b -P fixtures/field16/build.py -- [colorway|all] [--front]
#        blender -b -P fixtures/field16/build.py -- --export products/field16
# Units are metres at real size: the body is 92 x 52 x 30 mm. The front faces -Y, up is +Z.
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

W, H, D = 0.092, 0.052, 0.030
R = 0.005


def lin(h):
    """A brand hex -> the linear values a material takes."""
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(round(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4, 4) for v in c)


PAPER, STONE, INK, SIGNAL, WHITE = (lin(x) for x in ('#EDEBE8', '#E0DAD5', '#424249', '#FF5E2C', '#FAFAF8'))
COLORWAYS = {
    'white': dict(body=PAPER, band=SIGNAL, dial=lin('#1A1A1C'), cap=lin('#C8A24A'), rough=0.4),
    'signal-orange': dict(body=SIGNAL, band=PAPER, dial=lin('#1A1A1C'), cap=WHITE, rough=0.42),
}


# ---------- geometry helpers ----------
def rounded_profile(w, h, r, seg=10, cx=0.0, cz=0.0):
    pts = []
    for (x, z), a0 in (((w / 2 - r, h / 2 - r), 0), ((-w / 2 + r, h / 2 - r), 90),
                       ((-w / 2 + r, -h / 2 + r), 180), ((w / 2 - r, -h / 2 + r), 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + x + r * math.cos(a), cz + z + r * math.sin(a)))
    return pts


def prism(name, profile, y0, depth, mat, bevel=0.0005, index=0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    front = [bm.verts.new((x, y0, z)) for x, z in profile]
    back = [bm.verts.new((x, y0 + depth, z)) for x, z in profile]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(profile)
    for i in range(n):
        bm.faces.new((front[i], front[(i + 1) % n], back[(i + 1) % n], back[i]))
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
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    return ob


def disc(name, r, depth, x, y0, z, mat, index=0, bevel=0.0004, seg=64):
    return prism(name, [(x + r * math.cos(2 * math.pi * i / seg), z + r * math.sin(2 * math.pi * i / seg)) for i in range(seg)],
                 y0, depth, mat, bevel, index)


def material(name, color, rough=0.4, metal=0.0, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    if emit:
        p.inputs['Emission Color'].default_value = (*color, 1)
        p.inputs['Emission Strength'].default_value = emit
    return m


# ---------- the camera ----------
def build(cw):
    c = COLORWAYS[cw]
    body = material('body', c['body'], c['rough'])
    band = material('band', c['band'], 0.38)
    dial = material('dial', c['dial'], 0.45)
    cap = material('cap', c['cap'], 0.3, metal=0.6)
    glass = material('glass', (0.02, 0.02, 0.03), 0.08)
    lens = material('lens', (0.03, 0.02, 0.02), 0.12)
    dark = material('dark', (0.02, 0.02, 0.025), 0.5)
    trim = material('trim', STONE, 0.35, metal=0.4)

    prism('body', rounded_profile(W, H, R), 0.0, D, body, 0.0022, 1)
    # the coloured band across the top, standing a hair proud of the body
    prism('band', rounded_profile(W - 0.004, 0.013, 0.002, cz=H / 2 - 0.0085), -0.0008, D + 0.0016, band, 0.0006, 2)
    # lens: a dark window with a barrel inside
    prism('window', rounded_profile(0.034, 0.019, 0.002, cx=-0.006, cz=-0.004), -0.0012, 0.0018, glass, 0.0004, 3)
    disc('lens', 0.0068, 0.0022, -0.006, -0.0022, -0.004, lens, 3, 0.0005)
    disc('lens_ring', 0.0086, 0.0012, -0.006, -0.0016, -0.004, trim, 3, 0.0004)
    # viewfinder
    prism('finder', rounded_profile(0.0125, 0.0085, 0.0015, cx=-0.034, cz=0.006), -0.0011, 0.0016, glass, 0.0004, 3)
    # the dial: a ribbed cylinder with a coloured cap
    dx, dz = 0.026, 0.001
    disc('dial', 0.0135, 0.0085, dx, -0.0075, dz, dial, 4, 0.0006)
    for i in range(44):  # ribs
        a = 2 * math.pi * i / 44
        rib = prism(f'rib_{i}', rounded_profile(0.0016, 0.0042, 0.0005, cx=dx + 0.0128 * math.cos(a), cz=dz + 0.0128 * math.sin(a)),
                    -0.0072, 0.0078, dial, 0.0002, 4)
        rib.rotation_euler = (0, 0, 0)
    disc('cap', 0.0062, 0.0012, dx, -0.0082, dz, cap, 4, 0.0004)
    # the small speaker-style grille and the strap lug
    for i in range(6):
        for j in range(4):
            disc(f'grille_{i}{j}', 0.0006, 0.0004, 0.014 + 0.0018 * i, -0.0006, -0.019 + 0.0018 * j, dark, 5, 0)
    prism('lug', rounded_profile(0.004, 0.009, 0.0018, cx=W / 2 + 0.0015, cz=0.012), 0.008, 0.004, trim, 0.0005, 5)
    # two buttons on the band
    for i, x in enumerate((0.004, 0.018)):
        prism(f'button_{i}', rounded_profile(0.009, 0.005, 0.0015, cx=x, cz=H / 2 - 0.0085), -0.0016, 0.0014, dark, 0.0004, 4)
    # the wordmark, ours
    bpy.ops.object.text_add(location=(-0.040, -0.0009, 0.014), rotation=(math.radians(90), 0, 0))
    t = bpy.context.object
    t.name = 'wordmark'
    t.data.body = 'FIELD 16'
    t.data.size = 0.0052
    t.data.extrude = 0.0002
    t.data.space_character = 1.2
    t.data.materials.append(material('wordmark', c['dial'], 0.4))
    t.pass_index = 6


def export_product(folder):
    os.makedirs(folder, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build('white')
    bpy.ops.export_scene.gltf(filepath=os.path.join(folder, 'product.glb'), export_apply=True)
    part = {'body': 'body', 'band': 'band', 'dial': 'dial', 'cap': 'cap'}
    colorways = {}
    for cw, c in COLORWAYS.items():
        mats = {mat: {'color': list(c[key])} for mat, key in part.items()}
        mats['body'].update(roughness=c['rough'])
        colorways[cw] = mats
    spec = {
        'name': 'FIELD 16',
        'code': 'C-16',
        'year': '2026',
        'category': 'compact digital camera',
        'fictional': True,
        'size_mm': [92, 52, 30],
        'facts': ['A pocket camera with a fixed lens and an optical viewfinder',
                  'A ribbed control dial on the front', 'A coloured band across the top with two buttons',
                  'A strap lug on the right side', 'Two colorways: White and Signal Orange'],
        'hero_material': 'body',
        'protected_materials': ['window', 'lens', 'lens_ring', 'finder', 'glass', 'wordmark', 'cap', 'dark'],
        'exact_materials': ['glass', 'lens', 'wordmark'],
        'colorways': colorways,
    }
    json.dump(spec, open(os.path.join(folder, 'product.json'), 'w', encoding='utf-8'), indent=2)
    print('exported', folder)


args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if '--export' in args:
    export_product(os.path.abspath(args[args.index('--export') + 1]))
    sys.exit(0)
for cw in (list(COLORWAYS) if args[:1] == ['all'] else (args[:1] or ['white'])):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build(cw)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f'field16-{cw}.blend'))
    print('built', cw)
