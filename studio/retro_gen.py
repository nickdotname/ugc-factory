#!/usr/bin/env python3
"""retro.vibes.arcade's clip library: retro CGI scenes made by an open video model on Kaggle's free GPUs.

    python studio/retro_gen.py run [--clips N] [--hours H] [--steps S]   (GitHub Actions: make clips, add them to the library)
    python studio/retro_gen.py collect                                   (add the last Kaggle run's clips, if they are not in yet)
    python studio/retro_gen.py pull [THEME ...]                          (download the library into studio/retro/cache)
    python studio/retro_gen.py quota                                     (Kaggle's GPU hours left this week)

Nothing here costs money. GitHub Actions only orchestrates: it writes studio/retro/kernel.py with the night's jobs
(scene + look + seed, from studio/retro/prompts.json) and pushes it to Kaggle as a private GPU script kernel
(free: about 30 GPU hours a week on two T4s). There Wan 2.1 (Apache 2.0) renders 5-second vertical clips. Back
here they are checked, smoothed to 30 fps, uploaded as assets of the GitHub release "retro-library" and recorded
in studio/retro/index.json with their scene, look, seed and model. The renderer (studio/retro_video.py) only ever
reads that library, so Kaggle being slow or out of hours never stops a night's videos.

Needs KAGGLE_USERNAME and KAGGLE_KEY (an API key, or one of Kaggle's newer KGAT_ access tokens) in the environment.
"""
import hashlib, json, os, random, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'retro')
INDEX = os.path.join(DIR, 'index.json'); PROMPTS = os.path.join(DIR, 'prompts.json'); KERNEL = os.path.join(DIR, 'kernel.py')
CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'retro-library'
SLUG = 'retro-vibes-arcade-gen'


def index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {'clips': [], 'batches': []}


def save(idx):
    json.dump(idx, open(INDEX, 'w'), indent=1, ensure_ascii=False); open(INDEX, 'a').write('\n')


# ------------------------------------------------------------------ Kaggle
def kaggle():
    """An authenticated Kaggle client. A KGAT_ token in KAGGLE_KEY is moved to KAGGLE_API_TOKEN, where the client looks for it."""
    k = os.environ.get('KAGGLE_KEY', '')
    if k.startswith('KGAT_') and not os.environ.get('KAGGLE_API_TOKEN'):
        os.environ['KAGGLE_API_TOKEN'] = k; os.environ.pop('KAGGLE_KEY')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi(); api.authenticate(); return api


def kernel_id():
    user = os.environ.get('KAGGLE_USERNAME', '').strip()
    if not user: sys.exit('KAGGLE_USERNAME is not set')
    return '%s/%s' % (user, SLUG)


def status(api, kid):
    s = api.kernels_status(kid); return str(getattr(s, 'status', s)).split('.')[-1].upper(), getattr(s, 'failure_message', '') or ''


# ------------------------------------------------------------------ what to make
def plan(n, rng):
    """n jobs, spread over the themes with the fewest clips so far; in a theme the least-used scene, in a look it has used least."""
    bank = json.load(open(PROMPTS)); idx = index()
    have = {}; used = {}
    for c in idx['clips']:
        have[c['theme']] = have.get(c['theme'], 0) + 1; used[(c['theme'], c['scene'], c['look'])] = used.get((c['theme'], c['scene'], c['look']), 0) + 1
    themes = list(bank['themes']); looks = list(bank['looks']); jobs = []
    for k in range(n):
        th = min(themes, key=lambda t: (have.get(t, 0), rng.random()))
        scenes = range(len(bank['themes'][th]))
        sc, lk = min(((s, l) for s in scenes for l in looks), key=lambda sl: (used.get((th, sl[0], sl[1]), 0), rng.random()))
        have[th] = have.get(th, 0) + 1; used[(th, sc, lk)] = used.get((th, sc, lk), 0) + 1
        prompt = '%s. %s' % (bank['themes'][th][sc], bank['looks'][lk])
        jobs.append(dict(id='%s-%d-%s-%04d' % (th, sc, lk, rng.randrange(10 ** 4)), theme=th, scene=sc, look=lk, prompt=prompt,
                         seed=rng.randrange(2 ** 31)))
    # A third of a run makes single subjects for ascii.terminal.dreams (bank['subjects']): its own look, its own themes
    # (subject-koi, ...), the least-made first. They replace the last jobs of the plan, so the run is no longer.
    sub = bank.get('subjects', {}).get('scenes', {})
    for k in range(min(len(jobs), n // 3) if sub else 0):
        name = min(sub, key=lambda s: (have.get('subject-' + s, 0), rng.random())); th = 'subject-' + name
        sc = min(range(len(sub[name])), key=lambda c: (used.get((th, c, 'subject'), 0), rng.random()))
        have[th] = have.get(th, 0) + 1; used[(th, sc, 'subject')] = used.get((th, sc, 'subject'), 0) + 1
        jobs[-1 - k] = dict(id='%s-%d-subject-%04d' % (th, sc, rng.randrange(10 ** 4)), theme=th, scene=sc, look='subject',
                            prompt='%s. %s' % (sub[name][sc], bank['subjects']['look']), seed=rng.randrange(2 ** 31))
    return jobs, bank['negative']


def push(api, jobs, negative, hours, steps):
    batch = time.strftime('%Y%m%d-%H%M%S')
    # 49 frames (3 s at 16 fps) is enough for a cut that lasts a bar or two, and costs about a third of 81 frames on a T4
    cfg = dict(batch=batch, hours=hours, steps=steps, frames=49, width=480, height=832, fps=16, guidance=5.0, negative=negative)
    model = os.environ.get('RETRO_MODEL', '')                  # 'fastwan': Wan 2.2 5B in 3 steps at 704x1280 (see kernel.py)
    if model: cfg['model'] = model
    if model == 'fastwan' and os.environ.get('RETRO_AB'):       # a test: every prompt twice, the two ways of reading DMD's timesteps
        jobs[:] = [dict(j, id=j['id'] + ('-w' if w else '-p'), warp=w) for j in jobs for w in (False, True)]
    src = open(KERNEL).read()
    src = src.replace('JOBS = []', 'JOBS = ' + json.dumps(jobs), 1).replace('CFG = {}', 'CFG = ' + json.dumps(cfg), 1)
    d = tempfile.mkdtemp(); open(os.path.join(d, 'kernel.py'), 'w').write(src)
    kid = kernel_id()
    json.dump(dict(id=kid, title=SLUG, code_file='kernel.py', language='python', kernel_type='script', is_private=True,
                   enable_gpu=True, enable_internet=True, machine_shape='NvidiaTeslaT4', dataset_sources=[], competition_sources=[],
                   kernel_sources=[], model_sources=[]), open(os.path.join(d, 'kernel-metadata.json'), 'w'))
    r = api.kernels_push(d, timeout=str(int(hours * 3600 + 2400)), acc='NvidiaTeslaT4')
    err = getattr(r, 'error', None)
    if err: sys.exit('Kaggle refused the kernel: %s' % err)
    v = getattr(r, 'version_number', None)
    print('pushed %s version %s (%d jobs, batch %s): %s' % (kid, v, len(jobs), batch, getattr(r, 'url', '')), flush=True)
    return batch, ('%s/%s' % (kid, v) if v else kid)


def wait(api, kid, limit_sec):
    t0 = time.time(); last = None
    while time.time() - t0 < limit_sec:
        try: st, msg = status(api, kid)
        except Exception as exc: st, msg = 'UNKNOWN', str(exc)[:200]
        if st != last: print('%5.0f min  %s %s' % ((time.time() - t0) / 60, st, msg), flush=True); last = st
        if st in ('COMPLETE', 'ERROR', 'CANCEL_REQUESTED', 'CANCEL_ACKNOWLEDGED'): return st, msg
        time.sleep(60)
    return 'TIMEOUT', ''


# ------------------------------------------------------------------ into the library
def motion(path):
    import cv2, numpy as np
    cap = cv2.VideoCapture(path); prev = None; d = []
    while True:
        ok, f = cap.read()
        if not ok: break
        g = cv2.cvtColor(cv2.resize(f, (120, 208)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None: d.append(float(np.abs(g - prev).mean()))
        prev = g
    cap.release(); return round(sum(d) / max(1, len(d)), 2)


def collect(api, kid, want_batch=None):
    """Download the kernel's latest output and add its good clips to the library. Returns how many were added."""
    d = tempfile.mkdtemp()
    api.kernels_output(kid, d, force=True, quiet=True)
    man = os.path.join(d, 'manifest.json')
    for f in sorted(os.listdir(d)):
        if f.endswith('.log'):
            print(''.join(open(os.path.join(d, f), errors='replace').readlines()[-25:])[-3000:])
    if not os.path.exists(man): print('the run left no manifest: nothing to add'); return 0
    m = json.load(open(man)); idx = index()
    if m['batch'] in idx['batches']: print('batch %s is already in the library' % m['batch']); return 0
    if want_batch and m['batch'] != want_batch: print('the output is batch %s, not %s' % (m['batch'], want_batch))
    new, files = [], []
    for c in m['clips']:
        if not c.get('ok') or not c.get('file'): continue
        src = os.path.join(d, 'clips', c['file'])
        if not os.path.exists(src): continue
        name = hashlib.sha1(open(src, 'rb').read()).hexdigest()[:16] + '.mp4'; out = os.path.join(d, name)
        # Wan makes 16 fps; motion-compensated in-betweens bring it to 30 so it moves like the rest of the video
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-vf', 'minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1',
                            '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-an', '-movflags', '+faststart', out])
        if r.returncode: print('could not smooth', c['file']); continue
        files.append(out)
        new.append(dict(asset=name, theme=c['theme'], scene=c['scene'], look=c['look'], seed=c['seed'], prompt=c['prompt'],
                        model=c.get('model', m.get('model')), steps=c.get('steps'), batch=m['batch'], motion=motion(out)))
        print('+ %-11s %-7s %s' % (c['theme'], c['look'], c['prompt'][:70]))
    if files:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Retro clip library (generated)', '--notes',
                            'Clips for retro.vibes.arcade, made with Wan (Apache 2.0) on Kaggle. Prompts and seeds: studio/retro/index.json'], check=True)
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    idx['clips'] += new; idx['batches'].append(m['batch']); save(idx)
    took = [c['seconds'] for c in m['clips'] if c.get('seconds')]
    print('added %d clips (batch %s, %s; %.0f s per clip on %s)' % (len(new), m['batch'], m.get('model'), sum(took) / max(1, len(took)), m.get('gpus')))
    for e in m.get('errors', []): print('kernel error:', str(e)[-1500:])
    shutil.rmtree(d, ignore_errors=True); return len(new)


def pull(themes=()):
    """Download the library's clips (all, or the given themes) that are not cached yet; returns their index entries.
    All means all of retro's: the ASCII account's single subjects (theme subject-...) only come when asked for."""
    os.makedirs(CACHE, exist_ok=True)
    want = [e for e in index().get('clips', []) if (e['theme'] in themes if themes else not e['theme'].startswith('subject-'))]
    miss = [e['asset'] for e in want if not os.path.exists(os.path.join(CACHE, e['asset']))]
    if miss:
        for k in range(0, len(miss), 30):
            subprocess.run(['gh', 'release', 'download', RELEASE, '-R', REPO, '-D', CACHE, '--clobber'] + sum((['-p', a] for a in miss[k:k + 30]), []), check=True)
    return [e for e in want if os.path.exists(os.path.join(CACHE, e['asset']))]


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'pull': print(len(pull(tuple(sys.argv[2:]))), 'clips cached')
    elif cmd == 'quota': kaggle().quota_view_cli()
    elif cmd == 'collect':
        api = kaggle(); collect(api, kernel_id())
    elif cmd == 'run':
        api = kaggle(); kid = kernel_id(); hours = arg('--hours', 3.0)
        try:                                                     # a run the last job gave up waiting for: take its clips first
            st, _ = status(api, kid)
            if st == 'COMPLETE': collect(api, kid)
            elif st in ('RUNNING', 'QUEUED'): print('a run is still going on Kaggle; this one waits for it'); wait(api, kid, hours * 3600 + 2400); collect(api, kid)
        except SystemExit: raise
        except Exception as exc: print('no earlier run (%s)' % str(exc)[:120])
        jobs, neg = plan(arg('--clips', 24), random.Random())
        batch, ver = push(api, jobs, neg, hours, arg('--steps', 25))     # this version's status and output, never the last one's
        time.sleep(30)
        st, msg = wait(api, ver, min(hours * 3600 + 2400, 5.6 * 3600))
        if st == 'TIMEOUT': sys.exit('still running on Kaggle; the next run collects it')
        added = collect(api, ver, batch)
        if st != 'COMPLETE' and not added: sys.exit('the Kaggle run ended %s: %s' % (st, msg))
    else:
        print(__doc__)
