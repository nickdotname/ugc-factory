#version 330
// psychedelic.station: every field drawn at full size, per pixel, from the song's stems.
// Written for this repo (no third-party shader code). The numpy fields in psy_video.py are the
// fallback and the reference for what each field is; these are the same ideas, finer and lit.
in vec2 uv; out vec4 o;
uniform vec2 uR;
uniform float uT, uBass, uDrum, uVox, uOth, uHue, uOnset;
uniform int uField, uSecond, uSym, uPoster, uContour, uStrobe, uMirror, uRelief;
uniform float uMix, uScale, uSpin, uWarp;
uniform vec3 pa, pb, pc, pd;          // the cosine palette: a + b cos(2pi (c t + d))
uniform vec4 uBlobs[7];
uniform vec4 uSites[14];

const float TAU = 6.2831853;
vec3 pal(float t) { return pa + pb * cos(TAU * (pc * t + pd)); }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
    float s = 0., a = .5; mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int k = 0; k < 6; k++) { s += a * noise(p); p = m * p; a *= .5; }
    return s;
}

// p: centred, x in -1..1 across the width. Returns the field in about -1..1.
float field(int kind, vec2 p, float T) {
    float R = length(p) + 1e-6, A = atan(p.y, p.x);
    float sc = uScale * (1. - .22 * uBass);
    float ang = A + T * uSpin * TAU + .5 * uVox * sin(R * 3. - T);
    if (kind == 0) {                       // kaleido: a folded wedge, with a fractal grown inside it
        float s = float(uSym), w = TAU / s;
        float a = abs(mod(ang, w) - w * .5);
        vec2 q = R * vec2(cos(a), sin(a)) * (1.2 + .6 * uWarp);
        float acc = 0.;
        for (int k = 0; k < 7; k++) { q = abs(q) / dot(q, q) - vec2(.78 + .06 * sin(T * .3), .52 + .1 * uOth); acc += exp(-1.6 * length(q)); }
        return sin(R * sc * 3. - T * 1.3 + a * 4. * uWarp) * .35 + sin(acc * 2.2 - T * .8) * .65;
    }
    if (kind == 1) {                       // tunnel: a textured pipe flown down, the far end glowing
        float d = 1. / (R + .08);
        float z = d * .35 * sc + T * 1.1 + uBass * .6;            // texture read round the pipe's wall, so it has no seam
        float n = fbm(vec2(cos(ang), sin(ang)) * (.6 + .25 * float(uSym)) + vec2(z * 1.7, -z * 1.1)) * 2. - 1.;
        return (sin(d * sc * .8 + T * 2.2 + uBass * 2.) * .45 + sin(ang * float(uSym) + d * 1.5 - T) * .3 + n * .45) * clamp(R * 3.5, 0., 1.);
    }
    if (kind == 2) {                       // marble: noise warped by noise warped by noise
        vec2 q = p * sc * .55;
        vec2 a1 = vec2(fbm(q + vec2(0., T * .05)), fbm(q + vec2(5.2, 1.3) - T * .04));
        vec2 a2 = vec2(fbm(q + 3. * uWarp * a1 + vec2(1.7, 9.2) + .15 * T), fbm(q + 3. * uWarp * a1 + vec2(8.3, 2.8) + .126 * T + uVox));
        return fbm(q + 3.5 * a2) * 2.4 - 1.2 + .25 * sin(a2.x * 6. + T);
    }
    if (kind == 3) {                       // rings
        float wob = sin(ang * float(uSym) + T * 1.5) * (.15 + .5 * uVox);
        return sin((R + wob * .2) * sc * 6. - T * 2.5 - uBass * 3.);
    }
    if (kind == 4) {                       // oil: blobs of dye that merge and part
        float pot = 0.;
        for (int k = 0; k < 7; k++) {
            vec4 b = uBlobs[k]; float fk = float(k);
            vec2 c = vec2(.75 * sin(T * (.21 + .1 * b.z) + fk * 1.7 + b.x * 3.), 1.4 * sin(T * (.17 + .08 * b.w) + fk * 2.3 + b.y * 3.));
            float rr = (.18 + .05 * mod(fk, 3.)) * (1. + .5 * uBass + .3 * uVox);
            pot += rr * rr / (dot(p - c, p - c) + .02);
        }
        return sin(log(pot + 1e-3) * 2.2 - T * .6) * .7 + tanh(pot - 1.2) * .5;
    }
    if (kind == 5) {                       // julia, smooth-coloured, deep
        vec2 z = p * (1.25 / (1. + .25 * uBass));
        float cs = cos(T * uSpin * 2.), sn = sin(T * uSpin * 2.); z = mat2(cs, sn, -sn, cs) * z;
        float th = T * .11 + .35 * uVox + 2.; vec2 c = .7885 * vec2(cos(th), sin(th));
        float n = 0., trap = 9.;
        for (int k = 0; k < 160; k++) {
            z = vec2(z.x * z.x - z.y * z.y, 2. * z.x * z.y) + c; trap = min(trap, abs(z.y));
            if (dot(z, z) > 256.) break; n += 1.;
        }
        float sm = n - log2(log2(max(dot(z, z), 1.0001))) + 4.;
        return sin(sm * .18 - T * 1.5) * .7 + exp(-trap * 6.) * .6 - (n >= 159. ? .8 : 0.);
    }
    if (kind == 6) {                       // spiral
        float s = float(uSym); return sin(s * ang + log(R) * sc * 2.2 - T * 3. - uBass * 2.) * .7 + sin(R * sc * 2. - T) * .3;
    }
    if (kind == 7) {                       // moire: two sets of rings sliding over each other
        float a1 = .3 * sin(T * .3), a2 = .3 * cos(T * .23), k1 = sc * 9. * (1. + .1 * uVox);
        return sin(length(p - vec2(a1, .6 - a2)) * k1 - T * 2.) * sin(length(p + vec2(a1, .6 - a2)) * k1 + T * 1.7 + uBass * 2.);
    }
    if (kind == 8) {                       // warp: smoke folded into itself
        vec2 q = p * sc * .7;
        for (int k = 0; k < 4; k++) { float fk = float(k); q += uWarp * .5 * vec2(sin(q.y * 1.7 + T * (.25 + .1 * fk) + fk), cos(q.x * 1.3 - T * (.2 + .1 * fk) + uVox)); }
        return sin(q.x * 1.3 + cos(q.y * 1.1 + T * .4)) * .5 + (fbm(q * .8) - .5) * 1.2;
    }
    if (kind == 9) {                       // voronoi: cells with bright seams
        float d1 = 9., d2 = 9.;
        for (int k = 0; k < 14; k++) {
            vec4 s = uSites[k]; float fk = float(k);
            vec2 c = vec2(s.x * .9 + .15 * sin(T * (.3 + .2 * s.z) + fk), s.y * 1.6 + .15 * cos(T * (.25 + .2 * s.w) + fk));
            float d = length(p - c); d2 = min(d2, max(d1, d)); d1 = min(d1, d);
        }
        return clamp(1. - (d2 - d1) * (6. + 6. * uDrum), -1., 1.) * .8 + sin(d1 * sc * 6. - T * 2.) * .3;
    }
    vec2 q = p * sc + vec2(sin(T * .4), cos(T * .3));             // cells
    return sin(q.x * 2. + sin(q.y * 2. + T)) * cos(q.y * 2. + cos(q.x * 2. - T * .8)) + .3 * sin(R * sc * 4. - T * 2.);
}

float both(vec2 p, float T) {
    float f = field(uField, p, T);
    if (uSecond >= 0 && uMix > 0.) f = f * (1. - uMix * .6) + field(uSecond, p, T * 1.1) * uMix * .6;
    return f;
}

void main() {
    vec2 p = (uv * uR - .5 * uR) / (.5 * uR.x);
    if (uMirror == 1) p.x = -abs(p.x);
    float T = uT, R = length(p);
    float f = both(p, T);
    float t = f * .28 + T * .035 + uHue + R * .12;
    if (uPoster == 1) t = floor(t * 9.) / 9.;
    vec3 col = pal(t);
    if (uContour == 1) col *= .72 + .28 * cos(f * 16. + T * 2.);
    if (uRelief == 1) {                    // light the pattern as if it were a raised surface: a sheen that slides as it moves
        vec2 e = vec2(1.5 / (.5 * uR.x), 0.);
        vec3 n = normalize(vec3(both(p + e.xy, T) - f, both(p + e.yx, T) - f, 6. * e.x));
        vec3 l = normalize(vec3(-.5, .6, .8));
        float dif = clamp(dot(n, l), 0., 1.), spec = pow(clamp(dot(reflect(-l, n), vec3(0, 0, 1)), 0., 1.), 28.);
        col = col * (.55 + .6 * dif) + spec * (.35 + .5 * uDrum);
    }
    col *= .55 + .45 * clamp(1.25 - R * .55, 0., 1.);
    col *= .8 + .5 * uDrum;
    if (uStrobe == 1 && uOnset > .6) col = 1. - col;
    o = vec4(clamp(col, 0., 1.), 1.);
}
