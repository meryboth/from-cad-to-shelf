# Stage 1 - passes. Any product in, the control images every later stage needs, out.
# Usage: blender -b -P pipeline/passes.py -- <product dir> <out dir> [--quick]
#   <product dir> holds product.glb and product.json (see products/README.md)
# Nothing here knows what the product is: scale, framing and colours all come from the model and its spec.
import json
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
PRODUCT, OUT = os.path.abspath(args[0]), os.path.abspath(args[1])
QUICK = '--quick' in args
spec = json.load(open(os.path.join(PRODUCT, 'product.json'), encoding='utf-8'))
os.makedirs(OUT, exist_ok=True)

RES = spec.get('passes', {}).get('resolution', 1024)
# where the cameras sit, in degrees: azimuth from the front (positive turns to the product's right) and elevation
VIEWS = spec.get('passes', {}).get('views', {
    'front': [0, 4], 'left': [-35, 14], 'right': [35, 14], 'high': [-20, 42],
})
LENS = 70


# ---------- load and normalise ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(PRODUCT, 'product.glb'))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
root = bpy.data.objects.new('product', None)
bpy.context.collection.objects.link(root)
for o in bpy.context.scene.objects:
    if o.parent is None and o is not root:
        o.parent = root
root.rotation_euler.z = math.radians(spec.get('yaw_offset', 0))  # for models that do not face -Y
bpy.context.view_layer.update()


def bbox():
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


lo, hi = bbox()
if spec.get('size_mm'):  # models come in any unit: the spec gives the real size of the longest side
    root.scale *= max(spec['size_mm']) / 1000 / max(hi - lo)
    bpy.context.view_layer.update()
    lo, hi = bbox()
root.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))  # centred, standing on z = 0
bpy.context.view_layer.update()
lo, hi = bbox()
center = (lo + hi) / 2
radius = (hi - lo).length / 2


# ---------- materials: colourways by material name, and flat shaders for the passes ----------
def emission(name, color=(1, 1, 1)):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*color, 1)
    nt.links.new(em.outputs[0], out.inputs[0])
    return m, nt, em


def depth_material(near, far):
    m, nt, em = emission('pass_depth')
    cam = nt.nodes.new('ShaderNodeCameraData')
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value, mr.inputs['From Max'].default_value = near, far
    mr.inputs['To Min'].default_value, mr.inputs['To Max'].default_value = 1.0, 0.0  # near is white
    nt.links.new(cam.outputs['View Z Depth'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], em.inputs['Color'])
    return m


def normal_material():
    m, nt, em = emission('pass_normal')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    vt = nt.nodes.new('ShaderNodeVectorTransform')
    vt.vector_type, vt.convert_from, vt.convert_to = 'NORMAL', 'WORLD', 'CAMERA'
    # camera space: x right, y up, z towards the camera -> the usual normal-map colours
    mul = nt.nodes.new('ShaderNodeVectorMath')
    mul.operation = 'MULTIPLY_ADD'
    mul.inputs[1].default_value = (0.5, 0.5, -0.5)  # Blender's camera space looks down +z here; flip it so facing = blue
    mul.inputs[2].default_value = (0.5, 0.5, 0.5)
    nt.links.new(geo.outputs['Normal'], vt.inputs['Vector'])
    nt.links.new(vt.outputs['Vector'], mul.inputs[0])
    nt.links.new(mul.outputs['Vector'], em.inputs['Color'])
    return m


def apply_colorway(cw):
    for name, props in spec['colorways'][cw].items():
        m = bpy.data.materials.get(name)
        if not m:
            print(f'WARNING colourway {cw}: no material called {name}')
            continue
        nt = m.node_tree
        p = nt.nodes.get('Principled BSDF')
        base = p.inputs['Base Color']
        if 'color' in props and not base.is_linked:
            base.default_value = (*props['color'], 1)
        elif base.is_linked:  # a textured material: tint the texture instead (white leaves it as it is)
            tint = nt.nodes.get('colorway_tint')
            if not tint:
                tint = nt.nodes.new('ShaderNodeMix')
                tint.name, tint.data_type, tint.blend_type = 'colorway_tint', 'RGBA', 'MULTIPLY'
                src = base.links[0].from_socket
                nt.links.new(src, tint.inputs['A'])
                nt.links.new(tint.outputs['Result'], base)
            tint.inputs['Factor'].default_value = props.get('tint_strength', 1.0)
            tint.inputs['B'].default_value = (*props.get('color', (1, 1, 1)), 1)
        for key, socket in (('roughness', 'Roughness'), ('metallic', 'Metallic'), ('transmission', 'Transmission Weight')):
            if key in props:
                p.inputs[socket].default_value = props[key]


original = {o.name: [s.material for s in o.material_slots] for o in meshes}


def paint(fn):
    """Give every mesh the material fn(object) returns; restore() puts the real ones back."""
    for o in meshes:
        for s in o.material_slots:
            s.material = fn(o)


def restore():
    for o in meshes:
        for s, m in zip(o.material_slots, original[o.name]):
            s.material = m


protected = set(spec.get('protected_materials', []))
white, _, _ = emission('pass_white')
black, _, _ = emission('pass_black', (0, 0, 0))


def is_protected(o):
    return any(m and m.name in protected for m in original[o.name])


# ---------- scene ----------
sc = bpy.context.scene
for engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
    try:
        sc.render.engine = engine
        break
    except TypeError:
        pass
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.image_settings.file_format = 'PNG'
world = bpy.data.worlds.new('world')
world.use_nodes = True
bg = world.node_tree.nodes['Background']
sc.world = world
cam = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = LENS
half = math.atan(cam.data.sensor_width / 2 / LENS)
FILL = spec.get('passes', {}).get('fill', 0.82)  # how much of the frame the product takes
corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
dist = radius / math.sin(half)  # the lights keep this safe distance; each view gets its own framing


def frame(direction):
    """Aim at the product from `direction` and back off until its bounding box just fits the frame."""
    cam.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
    cam.location = center
    bpy.context.view_layer.update()
    rot = cam.matrix_world.to_3x3().inverted()
    need = 0.0
    for p in corners:
        v = rot @ (p - center)  # camera axes: x right, y up, -z forward
        need = max(need, v.z + max(abs(v.x), abs(v.y)) / (math.tan(half) * FILL))
    cam.location = center + direction * need
    return need


def lights(on):
    for o in [o for o in sc.objects if o.type == 'LIGHT']:
        bpy.data.objects.remove(o)
    if not on:
        return
    for loc, k in (((-1.2, -1.6, 1.4), 2.0), ((1.6, -0.9, 0.5), 0.6), ((0.6, 1.4, 1.6), 1.0)):  # key, fill, rim
        l = bpy.data.objects.new('light', bpy.data.lights.new('light', 'AREA'))
        sc.collection.objects.link(l)
        l.location = center + Vector(loc) * dist
        l.data.size = radius * 2
        l.data.energy = k * 12 * (Vector(loc) * dist).length ** 2  # same look at any product size
        l.rotation_euler = (center - l.location).to_track_quat('-Z', 'Y').to_euler()


def render(path, transparent=False, view='Standard'):
    sc.render.film_transparent = transparent
    sc.render.image_settings.color_mode = 'RGBA' if transparent else 'RGB'
    sc.view_settings.view_transform = view
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


manifest = {'product': spec.get('name'), 'resolution': RES, 'lens_mm': LENS, 'center': list(center), 'radius': radius,
            'size_m': list(hi - lo), 'views': {}, 'colorways': list(spec['colorways'])}
colorways = list(spec['colorways'])[:1] if QUICK else list(spec['colorways'])
for view, (az, el) in VIEWS.items():
    a, e = math.radians(az), math.radians(el)
    used = frame(Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))))
    d = os.path.join(OUT, view)
    os.makedirs(d, exist_ok=True)
    # control passes: flat colour on black, no lights needed
    lights(False)
    bg.inputs['Strength'].default_value = 0
    # depth range from the product itself, seen from this camera, so the gradient uses all 256 levels
    bpy.context.view_layer.update()
    inv = cam.matrix_world.inverted()
    zs = [-(inv @ (o.matrix_world @ Vector(c))).z for o in meshes for c in o.bound_box]
    pad = (max(zs) - min(zs)) * 0.02
    depth, normal = depth_material(min(zs) - pad, max(zs) + pad), normal_material()
    for name, fn in (('depth', lambda o: depth),
                     ('normal', lambda o: normal),
                     ('mask', lambda o: white),
                     ('mask_protected', lambda o: white if is_protected(o) else black)):
        paint(fn)
        render(os.path.join(d, f'{name}.png'), view='Raw')  # data, not a picture: no tone mapping
        restore()
    # beauty: the real materials in a neutral studio, one per colourway, on transparent background
    lights(True)
    bg.inputs['Color'].default_value = (0.8, 0.8, 0.82, 1)
    bg.inputs['Strength'].default_value = 0.35
    for cw in colorways:
        apply_colorway(cw)
        render(os.path.join(d, f'beauty_{cw}.png'), transparent=True, view='AgX')
    manifest['views'][view] = {'azimuth': az, 'elevation': el, 'camera': list(cam.location), 'distance': used}
    print('view done', view)

json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=2)
print('passes done', OUT)
