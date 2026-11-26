"""Real GLSL fragment shaders, drawn off-screen with no display and no GPU.

    sh = gl.Shader(open('studio/shaders/psy.glsl').read(), (1080, 1920), ss=1.5)
    img = sh.render(uT=1.2, uBass=.4)          # float32 HxWx3 in 0..1, top row first

Runs on the GitHub runners through EGL and Mesa's llvmpipe (software): about 30 frames a second at
1080x1920 for a light shader on two cores, so a 30 s video costs well under a minute. `ss` draws
bigger and shrinks with area averaging, which is the anti-aliasing (ss=1.5 is about 2.3x the cost).
Every shader gets `uR` (the size it is drawn at, in pixels) and `uv` (0..1, y up). Anything else is
a uniform the caller sets by name; names the compiler dropped as unused are skipped quietly.

Needs `pip install moderngl` and, on Ubuntu, libegl1 + libgl1-mesa-dri (studio.yml installs them).
`available()` says whether it works here; renderers fall back to numpy when it does not.
"""
import numpy as np

VERT = """#version 330
in vec2 p; out vec2 uv;
void main() { uv = p * .5 + .5; gl_Position = vec4(p, 0., 1.); }"""

_CTX = None
def context():
    global _CTX
    if _CTX is None:
        import moderngl
        try: _CTX = moderngl.create_standalone_context(backend='egl')
        except Exception: _CTX = moderngl.create_standalone_context()
    return _CTX

def available():
    try: context(); return True
    except Exception: return False

class Shader:
    def __init__(self, frag, size, ss=1.0):
        import moderngl
        self.W, self.H = size; self.ss = ss
        self.w, self.h = int(round(self.W * ss / 2)) * 2, int(round(self.H * ss / 2)) * 2
        ctx = context(); self.ctx = ctx
        if not frag.lstrip().startswith('#version'): frag = '#version 330\n' + frag
        self.prog = ctx.program(vertex_shader=VERT, fragment_shader=frag)
        vbo = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], 'f4'))
        self.vao = ctx.vertex_array(self.prog, [(vbo, '2f', 'p')])
        self.fbo = ctx.framebuffer(color_attachments=[ctx.texture((self.w, self.h), 4, dtype='f2')])
        self.textures = {}
        self.set(uR=(self.w, self.h))
        self._mgl = moderngl

    def set(self, **u):
        for k, v in u.items():
            if k not in self.prog: continue
            if isinstance(v, np.ndarray) and v.ndim >= 2: self.texture(k, v); continue
            if isinstance(v, (list, tuple, np.ndarray)): v = tuple(float(x) for x in np.ravel(v))
            self.prog[k].value = v

    def texture(self, name, img, unit=None):
        """Bind an HxWxC float or uint8 image (top row first) as sampler `name`."""
        a = np.ascontiguousarray(np.asarray(img)[::-1]); c = 1 if a.ndim == 2 else a.shape[2]
        a = (a.astype('f4') / 255 if a.dtype == np.uint8 else a.astype('f4'))
        t = self.textures.get(name)
        if t is None or t.size != (a.shape[1], a.shape[0]) or t.components != c:
            if t is not None: t.release()
            t = self.ctx.texture((a.shape[1], a.shape[0]), c, dtype='f4'); t.repeat_x = t.repeat_y = False
            t.filter = (self._mgl.LINEAR, self._mgl.LINEAR); self.textures[name] = t
        t.write(a.tobytes())
        if unit is None: unit = list(self.textures).index(name)
        t.use(unit)
        if name in self.prog: self.prog[name].value = unit

    def render(self, **u):
        self.set(**u); self.fbo.use(); self.vao.render(self._mgl.TRIANGLE_STRIP)
        a = np.frombuffer(self.fbo.read(components=3, dtype='f2'), np.float16).reshape(self.h, self.w, 3)[::-1].astype(np.float32)
        if (self.w, self.h) != (self.W, self.H):
            import cv2; a = cv2.resize(a, (self.W, self.H), interpolation=cv2.INTER_AREA)
        return np.clip(a, 0, 1)
