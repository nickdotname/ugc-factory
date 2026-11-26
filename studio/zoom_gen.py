#!/usr/bin/env python3
"""The zoom account's library: infinite-zoom chains (top-down pictures, each the middle half of the next) made with
SDXL on Kaggle's free GPUs (studio/zoom/kernel.py). Same pattern as studio/retro_gen.py: GitHub Actions only
orchestrates, Kaggle renders, the pictures land as assets of the GitHub release "zoom-library" and in
studio/zoom/index.json. The renderer (studio/zoom_video.py) only reads that library.

    python studio/zoom_gen.py run [--chains N] [--hours H] [--steps S]
    python studio/zoom_gen.py collect
    python studio/zoom_gen.py pull [THEME ...]
"""
import hashlib, json, os, random, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'zoom')
INDEX = os.path.join(DIR, 'index.json'); PROMPTS = os.path.join(DIR, 'prompts.json'); KERNEL = os.path.join(DIR, 'kernel.py')
CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'zoom-library'
SLUG = 'cq-infinite-zoom-gen'


def index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {'chains': [], 'batches': []}


def save(idx):
    json.dump(idx, open(INDEX, 'w'), indent=1, ensure_ascii=False); open(INDEX, 'a').write('\n')


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


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def plan(n, rng):
    """n chains, the themes made least so far first, each with a fresh seed."""
    bank = json.load(open(PROMPTS)); have = {}
    for c in index()['chains']: have[c['theme']] = have.get(c['theme'], 0) + 1
    jobs = []
    for _ in range(n):
        th = min(bank['chains'], key=lambda t: (have.get(t, 0), rng.random())); have[th] = have.get(th, 0) + 1
        jobs.append(dict(id='%s-%04d' % (th, rng.randrange(10 ** 4)), theme=th, prompts=bank['chains'][th], seed=rng.randrange(2 ** 31)))
    return jobs, bank


def push(api, jobs, bank, hours, steps):
    batch = time.strftime('%Y%m%d-%H%M%S')
    cfg = dict(batch=batch, hours=hours, steps=steps, width=768, height=1344, guidance=6.0, feather=40,
               style=bank['style'], negative=bank['negative'])
    src = open(KERNEL).read().replace('JOBS = []', 'JOBS = ' + json.dumps(jobs), 1).replace('CFG = {}', 'CFG = ' + json.dumps(cfg), 1)
    d = tempfile.mkdtemp(); open(os.path.join(d, 'kernel.py'), 'w').write(src); kid = kernel_id()
    json.dump(dict(id=kid, title=SLUG, code_file='kernel.py', language='python', kernel_type='script', is_private=True,
                   enable_gpu=True, enable_internet=True, machine_shape='NvidiaTeslaT4', dataset_sources=[], competition_sources=[],
                   kernel_sources=[], model_sources=[]), open(os.path.join(d, 'kernel-metadata.json'), 'w'))
    r = api.kernels_push(d, timeout=str(int(hours * 3600 + 2400)), acc='NvidiaTeslaT4')
    if getattr(r, 'error', None): sys.exit('Kaggle refused the kernel: %s' % r.error)
    v = getattr(r, 'version_number', None)
    print('pushed %s version %s (%d chains, batch %s)' % (kid, v, len(jobs), batch), flush=True)
    return batch, ('%s/%s' % (kid, v) if v else kid)


def collect(api, kid, want_batch=None):
    d = tempfile.mkdtemp(); api.kernels_output(kid, d, force=True, quiet=True)
    for f in sorted(os.listdir(d)):
        if f.endswith('.log'): print(''.join(open(os.path.join(d, f), errors='replace').readlines()[-25:])[-3000:])
    man = os.path.join(d, 'manifest.json')
    if not os.path.exists(man): print('the run left no manifest: nothing to add'); return 0
    m = json.load(open(man)); idx = index()
    if m['batch'] in idx['batches']: print('batch %s is already in the library' % m['batch']); return 0
    files, new = [], []
    for c in m['chains']:
        if not c.get('ok'): print('failed', c.get('id'), str(c.get('error'))[-300:]); continue
        cd = os.path.join(d, 'chains', c['id']); n = c['layers']
        if not all(os.path.exists(os.path.join(cd, '%d.jpg' % k)) for k in range(n)): continue
        h = hashlib.sha1(open(os.path.join(cd, '0.jpg'), 'rb').read()).hexdigest()[:12]; assets = []
        for k in range(n):
            name = 'z%s_%d.jpg' % (h, k); shutil.copy(os.path.join(cd, '%d.jpg' % k), os.path.join(d, name)); files.append(os.path.join(d, name)); assets.append(name)
        new.append(dict(id=h, theme=c['theme'], prompts=c['prompts'], seed=c['seed'], layers=n, assets=assets, batch=m['batch']))
        print('+ %-10s %d layers' % (c['theme'], n))
    if files:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Infinite-zoom library (generated)', '--notes',
                            'Zoom chains made with SDXL (OpenRAIL++) on Kaggle. Prompts and seeds: studio/zoom/index.json'], check=True)
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    idx['chains'] += new; idx['batches'].append(m['batch']); save(idx)
    for e in m.get('errors', []): print('kernel error:', str(e)[-1500:])
    print('added %d chains (batch %s)' % (len(new), m['batch'])); shutil.rmtree(d, ignore_errors=True); return len(new)


def pull(themes=()):
    os.makedirs(CACHE, exist_ok=True)
    want = [c for c in index()['chains'] if not themes or c['theme'] in themes]
    miss = [a for c in want for a in c['assets'] if not os.path.exists(os.path.join(CACHE, a))]
    for k in range(0, len(miss), 30):
        subprocess.run(['gh', 'release', 'download', RELEASE, '-R', REPO, '-D', CACHE, '--clobber'] + sum((['-p', a] for a in miss[k:k + 30]), []), check=True)
    return [c for c in want if all(os.path.exists(os.path.join(CACHE, a)) for a in c['assets'])]


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'pull': print(len(pull(tuple(sys.argv[2:]))), 'chains cached')
    elif cmd == 'collect': api = kaggle(); collect(api, kernel_id())
    elif cmd == 'run':
        api = kaggle(); kid = kernel_id(); hours = arg('--hours', 2.0)
        try:
            st, _ = status(api, kid)
            if st == 'COMPLETE': collect(api, kid)
            elif st in ('RUNNING', 'QUEUED'): print('a run is still going on Kaggle; waiting'); wait(api, kid, hours * 3600 + 2400); collect(api, kid)
        except SystemExit: raise
        except Exception as exc: print('no earlier run (%s)' % str(exc)[:120])
        jobs, bank = plan(arg('--chains', 10), random.Random())
        batch, ver = push(api, jobs, bank, hours, arg('--steps', 28)); time.sleep(30)
        st, msg = wait(api, ver, min(hours * 3600 + 2400, 5.6 * 3600))
        if st == 'TIMEOUT': sys.exit('still running on Kaggle; the next run collects it')
        added = collect(api, ver, batch)
        if st != 'COMPLETE' and not added: sys.exit('the Kaggle run ended %s: %s' % (st, msg))
    else: print(__doc__)
