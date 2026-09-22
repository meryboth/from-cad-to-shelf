# Stage 1 - passes. Any product in, the control images every later stage needs, out.
# Usage: blender -b -P pipeline/passes.py -- <product dir> <out dir> [--quick] [--view V] [--format square|portrait|story]
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
ONLY = args[args.index('--view') + 1] if '--view' in args else None  # render one view, to iterate fast
spec = json.load(open(os.path.join(PRODUCT, 'product.json'), encoding='utf-8'))
os.makedirs(OUT, exist_ok=True)

RES = spec.get('passes', {}).get('resolution', 1024)
# a piece format frames the product for its layout: its size (SDXL-friendly), and the share of the frame kept free at the
# top for the headline. Without --format the frame is square and centred.
FORMATS = {'square': (1024, 1024, 0.33), 'portrait': (896, 1120, 0.33), 'story': (768, 1344, 0.30)}
FMT = args[args.index('--format') + 1] if '--format' in args else None
W_PX, H_PX, HEADROOM = FORMATS[FMT] if FMT else (RES, RES, 0.0)
# where the cameras sit, in degrees: azimuth from the front (positive turns to the product's right) and elevation
VIEWS = spec.get('passes', {}).get('views', {
    'front': [0, 4], 'left': [-35, 14], 'right': [35, 14], 'high': [-20, 42],
})
LENS = 70
if '--views' in args:  # extra framings for one run, e.g. --views held=0,24
    VIEWS = {k: [float(x) for x in v.split(',')] for k, v in (item.split('=') for item in args[args.index('--views') + 1].split(';'))}


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
        for key, socket in (('roughness', 'Roughness'), ('metallic', 'Metallic'), ('transmission', 'Transmission Weight'),
                            ('coat', 'Coat Weight')):
            if key in props:
                p.inputs[socket].default_value = props[key]


RENDER = spec.get('render', {})


def micro_surface(strength):
    """A faint noise bump on every material without a normal map: real surfaces are never perfectly smooth."""
    for m in {s.material for o in meshes for s in o.material_slots if s.material}:
        nt = m.node_tree
        p = nt.nodes.get('Principled BSDF')
        if not p or p.inputs['Normal'].is_linked:
            continue
        tex = nt.nodes.new('ShaderNodeTexNoise')
        tex.inputs['Scale'].default_value = 2500 / max(radius, 1e-3) * 0.05  # the grain follows the product size
        tex.inputs['Detail'].default_value = 6
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = strength
        bump.inputs['Distance'].default_value = radius * 0.0004
        nt.links.new(tex.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], p.inputs['Normal'])


micro_surface(RENDER.get('micro_surface', 0.15))
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
exact = set(spec.get('exact_materials', []))  # a subset of protected: copied as they are, not just in colour
MASKS_ONLY = '--masks-only' in args
white, _, _ = emission('pass_white')
black, _, _ = emission('pass_black', (0, 0, 0))

# every material gets a flat colour of its own, so later stages can find each part in the photo
MATERIALS = sorted({m.name for o in meshes for m in [s.material for s in o.material_slots] if m})
PART_COLORS = {}
for i, name in enumerate(MATERIALS):
    h = (i * 0.61803398875) % 1.0  # spread the hues, so no two parts look alike
    import colorsys
    PART_COLORS[name] = [round(v, 4) for v in colorsys.hsv_to_rgb(h, 0.85, 1.0 if i % 2 else 0.7)]
part_mats = {n: emission(f'part_{n}', c)[0] for n, c in PART_COLORS.items()}


def part_material(o):
    m = next((m for m in original[o.name] if m), None)
    return part_mats.get(m.name if m else '', black)




def is_protected(o, names=None):
    return any(m and m.name in (names or protected) for m in original[o.name])


# ---------- scene ----------
sc = bpy.context.scene
EEVEE = next(e for e in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT')
             if e in [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items])


def use_engine(engine):
    sc.render.engine = engine
    if engine == 'CYCLES':
        sc.cycles.samples = RENDER.get('samples', 128)
        sc.cycles.use_denoising = True
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):  # the fastest GPU backend there is, else the CPU
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                if any(d.type == kind for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = d.type == kind
                    sc.cycles.device = 'GPU'
                    return
            except TypeError:
                pass
        sc.cycles.device = 'CPU'


use_engine(EEVEE)
sc.render.resolution_x, sc.render.resolution_y = W_PX, H_PX
sc.render.image_settings.file_format = 'PNG'
world = bpy.data.worlds.new('world')
world.use_nodes = True
bg = world.node_tree.nodes['Background']
sc.world = world
# a studio HDRI for reflections; Blender ships it, so every machine has the same one
hdri = world.node_tree.nodes.new('ShaderNodeTexEnvironment')
hdri.image = bpy.data.images.load(os.path.join(bpy.utils.system_resource('DATAFILES'), 'studiolights', 'world',
                                               RENDER.get('hdri', 'studio.exr')))
# the floor only catches shadows, so the beauty keeps its transparent background
bpy.ops.mesh.primitive_plane_add(size=1)
floor = bpy.context.object
floor.scale = (radius * 30,) * 3
floor.is_shadow_catcher = True
floor.hide_render = True
cam = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = LENS
half = math.atan(cam.data.sensor_width / 2 / LENS)  # along the longer side of the frame
tan_x = math.tan(half) * W_PX / max(W_PX, H_PX)
tan_y = math.tan(half) * H_PX / max(W_PX, H_PX)
# the product fills the frame below the headroom; lens shift slides that window down without tilting the camera
cam.data.shift_y = HEADROOM / 2 * H_PX / max(W_PX, H_PX)
FILL = float(args[args.index('--fill') + 1]) if '--fill' in args else spec.get('passes', {}).get('fill', 0.82)  # share of the frame
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
        need = max(need, v.z + abs(v.x) / (tan_x * FILL), v.z + abs(v.y) / (tan_y * (1 - HEADROOM) * FILL))
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
        l.data.size = radius * 4  # big, soft sources: product light, not a torch
        l.data.energy = k * RENDER.get('light', 2.5) * (Vector(loc) * dist).length ** 2  # same look at any size
        l.rotation_euler = (center - l.location).to_track_quat('-Z', 'Y').to_euler()


def render(path, transparent=False, view='Standard'):
    sc.render.film_transparent = transparent
    sc.render.image_settings.color_mode = 'RGBA' if transparent else 'RGB'
    sc.view_settings.view_transform = view
    sc.view_settings.look = 'None'
    if view == 'AgX':
        for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
            try:
                sc.view_settings.look = look
                break
            except TypeError:
                pass
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


manifest = {'product': spec.get('name'), 'materials': PART_COLORS, 'format': FMT, 'size_px': [W_PX, H_PX], 'headroom': HEADROOM, 'resolution': RES, 'lens_mm': LENS, 'center': list(center), 'radius': radius,
            'size_m': list(hi - lo), 'views': {}, 'colorways': list(spec['colorways'])}
colorways = list(spec['colorways'])[:1] if QUICK else list(spec['colorways'])
for view, (az, el) in VIEWS.items():
    if ONLY and view != ONLY:
        continue
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
                     ('mask_protected', lambda o: white if is_protected(o) else black),
                     ('mask_exact', lambda o: white if exact and is_protected(o, exact) else black),
                     ('mask_parts', part_material)):
        paint(fn)
        render(os.path.join(d, f'{name}.png'), view='Raw')  # data, not a picture: no tone mapping
        restore()
    if MASKS_ONLY:
        manifest['views'][view] = {'azimuth': az, 'elevation': el, 'camera': list(cam.location), 'distance': used}
        continue
    # beauty: the real materials in a studio, one per colourway, with a contact shadow on a transparent background
    use_engine('CYCLES')
    lights(True)
    world.node_tree.links.new(hdri.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = RENDER.get('hdri_strength', 0.45)
    floor.hide_render = False
    for cw in colorways:
        apply_colorway(cw)
        render(os.path.join(d, f'beauty_{cw}.png'), transparent=True, view='AgX')
    floor.hide_render = True
    for l in list(bg.inputs['Color'].links):
        world.node_tree.links.remove(l)
    use_engine(EEVEE)
    manifest['views'][view] = {'azimuth': az, 'elevation': el, 'camera': list(cam.location), 'distance': used}
    print('view done', view)

json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=2)
print('passes done', OUT)
