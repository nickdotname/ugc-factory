"""Render one low-poly story's frames in Blender (bpy, the Workbench engine: flat colours, soft shadows; no GPU).

    python studio/lowpoly/scene.py PLAN.json OUT_DIR

PLAN.json (written by studio/lowpoly_video.py): {"w", "h", "fps", "seed", "shots": [{"start", "end", "kind",
"place", "effect", "beats": [frame, ...]}]}. Frames are written as OUT_DIR/00000.png ... one per frame of the video.

The people are built here from boxes (head, body, arms, legs, the face drawn on as flat boxes) and walk by swinging
their limbs, so every effect (grow, float, copies) is just a transform. Buildings, cars and furniture come from the
CC0 kits in studio/lowpoly/cache when they are there (studio/lowpoly/fetch.py); otherwise simple box houses stand in.
"""
import json, math, os, random, sys, glob
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, 'cache')
SKIN = [(0.96, 0.80, 0.62), (0.86, 0.66, 0.48), (0.62, 0.43, 0.30), (0.42, 0.28, 0.19)]
SHIRT = [(0.85, 0.15, 0.15), (0.15, 0.35, 0.85), (0.55, 0.20, 0.75), (0.15, 0.65, 0.35), (0.95, 0.60, 0.10), (0.95, 0.95, 0.95)]
PANTS = [(0.15, 0.18, 0.35), (0.80, 0.80, 0.82), (0.20, 0.20, 0.22), (0.45, 0.35, 0.25)]
HAIR = [(0.35, 0.20, 0.10), (0.10, 0.08, 0.06), (0.85, 0.70, 0.35), (0.55, 0.25, 0.10)]
WALLS = [(0.93, 0.88, 0.78), (0.78, 0.85, 0.92), (0.95, 0.80, 0.80), (0.82, 0.90, 0.80), (0.95, 0.92, 0.70)]
ROOFS = [(0.80, 0.20, 0.18), (0.20, 0.35, 0.70), (0.30, 0.30, 0.32)]
SKY = {'day': (0.45, 0.70, 1.0), 'night': (0.10, 0.08, 0.22)}


def mat(rgb):
    key = 'm_%.2f_%.2f_%.2f' % tuple(rgb)
    m = bpy.data.materials.get(key)
    if m is None:
        m = bpy.data.materials.new(key); m.diffuse_color = (*rgb, 1.0)
    return m


def box(name, size, loc, rgb, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object; o.name = name; o.scale = size; o.data.materials.append(mat(rgb))
    if parent: o.parent = parent
    return o


def empty(name, loc=(0, 0, 0), parent=None):
    o = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(o); o.location = loc
    if parent: o.parent = parent
    return o


class Person:
    """A blocky person about 1.9 units tall, feet at its origin, facing -y."""
    def __init__(self, r, loc=(0, 0, 0), old=False):
        self.root = empty('person', loc)
        skin, shirt, pants, hair = r.choice(SKIN), r.choice(SHIRT), r.choice(PANTS), r.choice(HAIR)
        if old: hair = (0.82, 0.82, 0.84)
        self.hip = empty('hip', (0, 0, 0.9), self.root)
        box('body', (0.62, 0.34, 0.66), (0, 0, 0.33), shirt, self.hip)
        self.head = empty('neck', (0, 0, 0.66), self.hip)
        box('head', (0.5, 0.48, 0.5), (0, 0, 0.27), skin, self.head)
        box('hair', (0.54, 0.56, 0.18), (0, 0.0, 0.56), hair, self.head)
        box('fringe', (0.54, 0.08, 0.12), (0, -0.25, 0.47), hair, self.head)
        for x in (-0.11, 0.11): box('eye', (0.06, 0.02, 0.11), (x, -0.245, 0.31), (0.05, 0.05, 0.06), self.head)
        self.mouth = box('mouth', (0.16, 0.02, 0.04), (0, -0.245, 0.14), (0.25, 0.08, 0.08), self.head)
        self.arms, self.legs = [], []
        for side in (-1, 1):
            a = empty('shoulder', (side * 0.40, 0, 0.62), self.hip)
            box('arm', (0.17, 0.2, 0.62), (0, 0, -0.29), shirt, a); box('hand', (0.16, 0.18, 0.12), (0, 0, -0.64), skin, a)
            self.arms.append(a)
            l = empty('leg', (side * 0.16, 0, 0.0), self.hip)
            box('leg', (0.24, 0.26, 0.86), (0, 0, -0.43), pants, l); box('shoe', (0.26, 0.34, 0.1), (0, -0.04, -0.88), (0.95, 0.95, 0.95), l)
            self.legs.append(l)

    def pose(self, t, speed=1.0, mood='walk'):
        """Swing the limbs at time t (seconds); speed 0 stands still, 2 runs."""
        w = t * 2 * math.pi * (1.1 if speed < 1.5 else 1.8)
        amp = 0.45 * min(speed, 1.0) + (0.35 if speed >= 1.5 else 0)
        for k, l in enumerate(self.legs): l.rotation_euler = (math.sin(w + k * math.pi) * amp, 0, 0)
        for k, a in enumerate(self.arms): a.rotation_euler = (math.sin(w + (1 - k) * math.pi) * amp * 0.9, 0, 0)
        self.hip.location.z = 0.9 + abs(math.sin(w)) * 0.05 * speed
        self.head.rotation_euler = (0, 0, math.sin(t * 1.3) * 0.12 if speed == 0 else 0)
        self.mouth.scale.z = 0.04 if mood != 'shout' else 0.04 + 0.12 * abs(math.sin(t * 9))


def kit_models(kinds):
    """Paths of kit models whose file name matches one of the words, from the unzipped kits in CACHE."""
    files = glob.glob(os.path.join(CACHE, '**', '*.glb'), recursive=True) + glob.glob(os.path.join(CACHE, '**', '*.gltf'), recursive=True)
    return [f for f in files if any(k in os.path.basename(f).lower() for k in kinds)]


def place_model(path, loc, rot=0.0, scale=1.0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    root = empty('kit', loc)
    for o in new:
        if o.parent is None: o.parent = root
    root.rotation_euler = (0, 0, rot); root.scale = (scale,) * 3
    return root


def house(r, loc, rot):
    models = kit_models(['building-type', 'house', 'suburban']) if r.random() < 0.95 else []
    if models: return place_model(r.choice(models), loc, rot, 2.2)
    root = empty('house', loc); root.rotation_euler = (0, 0, rot)
    wall = r.choice(WALLS); w, d, h = r.uniform(3.2, 4.4), r.uniform(3, 4), r.uniform(2.6, 3.4)
    box('walls', (w, d, h), (0, 0, h / 2), wall, root)
    roof = box('roof', (w * 1.1, d * 1.1, 0.9), (0, 0, h + 0.45), r.choice(ROOFS), root)
    bpy.ops.object.select_all(action='DESELECT'); roof.select_set(True); bpy.context.view_layer.objects.active = roof
    box('door', (0.8, 0.05, 1.4), (0, -d / 2 - 0.02, 0.7), (0.55, 0.35, 0.2), root)
    for x in (-w / 3, w / 3): box('window', (0.8, 0.05, 0.7), (x, -d / 2 - 0.02, h * 0.6), (0.6, 0.85, 1.0), root)
    return root


def street(r):
    """A straight street along y: road, sidewalks, houses both sides, trees, lamp posts."""
    box('ground', (80, 200, 0.1), (0, 40, -0.05), (0.55, 0.80, 0.40))
    box('road', (6, 200, 0.02), (0, 40, 0.0), (0.33, 0.33, 0.36))
    for x in (-4.2, 4.2): box('walk', (2.4, 200, 0.12), (x, 40, 0.04), (0.88, 0.87, 0.84))
    for y in range(-10, 100, 6): box('line', (0.15, 2.2, 0.03), (0, y, 0.02), (0.98, 0.85, 0.2))
    for k, y in enumerate(range(-6, 100, 7)):
        for side in (-1, 1):
            house(r, (side * 9.5, y + r.uniform(-1, 1), 0), math.pi / 2 * side)
            if r.random() < 0.6: tree(r, (side * 5.8, y + 3, 0))


def tree(r, loc):
    box('trunk', (0.25, 0.25, 1.4), (loc[0], loc[1], 0.7), (0.45, 0.30, 0.18))
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=r.uniform(0.9, 1.3), location=(loc[0], loc[1], 1.9))
    o = bpy.context.object; o.data.materials.append(mat((0.35, 0.72, 0.30)))


def room(kind, r):
    """Three walls and a floor, with a few things in it for the kind of room."""
    floor = {'kitchen': (0.85, 0.82, 0.75), 'bathroom': (0.92, 0.95, 0.95), 'bedroom': (0.70, 0.52, 0.36)}.get(kind, (0.8, 0.8, 0.8))
    wall = {'kitchen': (0.96, 0.93, 0.80), 'bathroom': (0.75, 0.88, 0.82), 'bedroom': (0.80, 0.82, 0.95)}.get(kind, (0.9, 0.9, 0.9))
    box('floor', (8, 8, 0.1), (0, 2, -0.05), floor); box('ceiling', (8, 8, 0.1), (0, 2, 4.0), (0.97, 0.97, 0.97))
    box('back', (8, 0.1, 4), (0, 6, 2), wall); box('left', (0.1, 8, 4), (-4, 2, 2), wall); box('right', (0.1, 8, 4), (4, 2, 2), wall)
    if kind == 'kitchen':
        box('counter', (5, 1, 1), (0, 5.4, 0.5), (0.95, 0.95, 0.95)); box('top', (5.1, 1.1, 0.08), (0, 5.4, 1.02), (0.35, 0.35, 0.38))
        box('fridge', (1.1, 1, 2.2), (3, 5.3, 1.1), (0.9, 0.92, 0.95)); box('table', (1.6, 1.2, 0.08), (-1.5, 2.5, 0.85), (0.6, 0.42, 0.25))
    elif kind == 'bathroom':
        box('sink', (1.2, 0.7, 0.9), (1.5, 5.5, 0.45), (0.97, 0.97, 0.97)); box('mirror', (1.0, 0.05, 1.0), (1.5, 5.9, 1.9), (0.75, 0.9, 1.0))
        box('tub', (2.2, 1.0, 0.7), (-2.6, 5.2, 0.35), (0.97, 0.97, 0.97))
        for k in range(8): box('tile', (8, 0.02, 0.02), (0, 5.94, 0.4 + k * 0.45), (0.65, 0.8, 0.74))
    else:
        box('bed', (2.2, 3, 0.6), (-1.8, 4.2, 0.3), (0.95, 0.95, 0.98)); box('blanket', (2.25, 2, 0.1), (-1.8, 3.7, 0.65), r.choice(SHIRT))
        box('desk', (1.6, 0.8, 0.08), (2.4, 5.3, 0.9), (0.6, 0.42, 0.25)); box('screen', (0.9, 0.05, 0.6), (2.4, 5.5, 1.3), (0.1, 0.1, 0.12))


def car(r, loc):
    models = kit_models(['sedan', 'hatchback', 'suv', 'taxi', 'van'])
    if models: return place_model(r.choice(models), loc, 0, 1.6)
    root = empty('car', loc); c = r.choice(SHIRT)
    box('body', (1.8, 4, 0.8), (0, 0, 0.7), c, root); box('cab', (1.6, 2.2, 0.7), (0, 0.2, 1.4), (0.6, 0.85, 1.0), root)
    for x in (-0.9, 0.9):
        for y in (-1.3, 1.3): box('wheel', (0.25, 0.7, 0.7), (x, y, 0.35), (0.1, 0.1, 0.1), root)
    return root


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup(plan, night):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y = plan['w'], plan['h']
    sh = sc.display.shading
    sh.light = 'STUDIO'; sh.color_type = 'MATERIAL'; sh.show_shadows = True; sh.shadow_intensity = 0.35
    sh.show_cavity = True; sh.cavity_type = 'WORLD'; sh.show_object_outline = False
    sc.display.light_direction = (0.45, -0.35, 0.82)
    w = bpy.data.worlds.new('w'); sc.world = w; w.color = SKY['night' if night else 'day']
    sh.background_type = 'WORLD'
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'Standard'; sc.view_settings.exposure = 0.35
    sc.render.image_settings.file_format = 'PNG'
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); bpy.context.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 28
    return sc, cam


def look(cam, frm, at, roll=0.0):
    cam.location = Vector(frm)
    d = Vector(at) - Vector(frm); cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler(); cam.rotation_euler.rotate_axis('Z', roll)


def shot(plan, s, out_dir):
    r = random.Random(plan['seed'] * 1000 + s['start'])
    eff = s.get('effect') or ''; night = 'night' in eff
    clear(); sc, cam = setup(plan, night)
    kind, place = s['kind'], s.get('place') or 'bedroom'
    people = []
    indoor = kind == 'room' or (kind == 'face' and s.get('setting') == 'room')
    if indoor: room(place, r)
    else: street(r)
    hero = Person(random.Random(plan['seed']), (0, 0, 0), old='old' in eff); people.append(hero)   # the same person all story
    if 'old' in eff: hero.hip.rotation_euler = (0.18, 0, 0)
    if kind == 'crowd' or 'many' in eff:
        for k in range(14 if kind == 'crowd' else 0):
            p = Person(r, (r.uniform(-4.5, 4.5), r.uniform(2, 26), 0)); p.root.rotation_euler = (0, 0, r.choice([0, math.pi])); people.append(p)
    copies = []
    if 'many' in eff:                                                   # copies of the hero appear one per beat
        rr = random.Random(plan['seed'])
        for k in range(len(s['beats']) * 6):
            p = Person(random.Random(plan['seed']), (rr.uniform(-5, 5), rr.uniform(1, 30), 0)); p.root.scale = (0.001,) * 3; copies.append(p)
    vehicle = car(r, (2, -30, 0)) if kind == 'car' else None
    debris = []
    if 'blast' in eff:
        for k in range(26): debris.append((box('bit', (0.4, 0.4, 0.4), (0, 0, 1), r.choice(WALLS + ROOFS)), Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.3, 1.2))).normalized() * r.uniform(6, 16)))
    n = s['end'] - s['start']; fps = plan['fps']
    for i in range(n):
        f = s['start'] + i; t = i / fps; u = i / max(1, n - 1)
        beat_age = min([f - b for b in s['beats'] if b <= f] or [99])
        kick = max(0.0, 1 - beat_age / 5)
        size = 1.0
        if 'grow' in eff: size = 1 + u ** 1.5 * (12 if kind == 'town' else 3)
        if 'shrink' in eff: size = max(0.08, 1 - u * 0.9)
        hero.root.scale = (size,) * 3
        z = (u ** 1.3) * 14 if 'float' in eff else 0
        speed = {'walk': 1, 'run': 2, 'crowd': 1}.get(kind, 0)
        y = -t * (1.3 if speed == 1 else 4.0) if kind != 'run' else t * 5.0
        hero.root.location = (0, y if speed else 0, z)
        hero.root.rotation_euler = (0, 0, math.pi if kind == 'run' else 0)
        hero.pose(t, speed, 'shout' if 'shake' in eff else 'walk')
        for k, p in enumerate(people[1:]):
            p.pose(t + k * 0.37, 1); p.root.location.y += (-0.04 if p.root.rotation_euler.z == 0 else 0.04)
            if 'float' in eff: p.root.location.z = (u ** 1.3) * (6 + k % 5)
        for k, p in enumerate(copies):
            on = k < (len([b for b in s['beats'] if b <= f]) * 6)
            p.root.scale = (1.0 if on else 0.001,) * 3; p.pose(t + k * 0.2, 0.6)
        for b, v in debris:
            if 'blast' in eff and u > 0.3:
                tt = (u - 0.3) * n / fps; b.location = Vector((0, 0, 1)) + v * tt + Vector((0, 0, -4.9 * tt * tt * 0.3)); b.rotation_euler = (tt * 3, tt * 2, 0)
            else: b.location = (0, 0, -5)
        if vehicle is not None: vehicle.location = (2, -30 + t * (14 + 10 * u), 0)
        hy, hz = hero.root.location.y, hero.root.location.z
        H = 1.9 * size
        shake = Vector((math.sin(f * 7.1), 0, math.cos(f * 5.3))) * 0.08 * kick * (3 if 'shake' in eff else 0.6)
        if kind in ('walk', 'crowd'):
            look(cam, Vector((0.6, hy - 5.5 - H * 0.6, 1.5 + H * 0.45 + z)) + shake, (0, hy, H * 0.55 + z))
        elif kind == 'run':
            look(cam, Vector((0.5, hy - 6, 1.8 + z)) + shake, (0, hy + 2, 1.0 + z))
        elif kind == 'face':
            look(cam, Vector((0.25, -1.25 * size - 0.4, 1.68 * size + 0.1 + z)) + shake, (0, 0, 1.6 * size + z))
        elif kind == 'room':
            look(cam, Vector((1.4, -3.4, 1.9)) + shake, (0, 0.5, 1.2 * size + z))
        elif kind == 'house':
            look(cam, Vector((-2.5, -8 - H, 2.2 + H * 0.4)) + shake, (9.5, 3, 2 + H * 0.3))
        elif kind == 'car':
            look(cam, Vector((-4.5, -8, 1.6)) + shake, (2, vehicle.location.y, 1))
        else:                                                              # town: high and slowly turning
            a = (0.6 + t * 0.15) if 'spin' in eff else 0.6
            dist = 26 + H * 2.5
            look(cam, Vector((math.sin(a) * dist, -math.cos(a) * dist + 8, 16 + H * 1.4 + z * 0.6)) + shake, (0, 8, H * 0.5 + z))
        if 'spin' in eff and kind not in ('town',):
            p = cam.location; c = Vector((0, hero.root.location.y, H * 0.6 + z)); a = t * 0.6
            v = p - c; cam.location = c + Vector((v.x * math.cos(a) - v.y * math.sin(a), v.x * math.sin(a) + v.y * math.cos(a), v.z)); look(cam, cam.location, c)
        if s.get('only') and f not in s['only']: continue                  # a contact sheet: only the frames asked for
        sc.render.filepath = os.path.join(out_dir, '%05d.png' % f)
        bpy.ops.render.render(write_still=True)


def main():
    plan = json.load(open(sys.argv[1])); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
    for s in plan['shots']:
        shot(plan, s, out); print('shot', s['kind'], s['start'], s['end'], flush=True)


if __name__ == '__main__':
    main()
