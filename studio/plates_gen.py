#!/usr/bin/env python3
"""The plate library: still pictures for backgrounds, made by an open image model on Kaggle's free GPUs.

    python studio/plates_gen.py run [--plates N] [--hours H] [--steps S] [--themes a,b]   (Actions: make plates, add them)
    python studio/plates_gen.py collect                                                    (add the last run's plates)
    python studio/plates_gen.py pull [THEME ...]                                           (download into studio/plates/cache)
    python studio/plates_gen.py quota                                                      (Kaggle GPU hours left this week)

Nothing here costs money, like studio/retro_gen.py, which this follows: GitHub Actions writes studio/plates/kernel.py
with the run's jobs (scene + look + seed, from studio/plates/prompts.json), pushes it to Kaggle as a private GPU
script, waits, then uploads the good pictures to the GitHub release "plates-library" and records them in
studio/plates/index.json. Renderers only ever read the library (pull()), so Kaggle being slow never stops a night.
The model is SDXL base 1.0 (CreativeML Open RAIL++-M, commercial use allowed). Places only: no people, no text, no
brands (see prompts.json).

Needs KAGGLE_USERNAME and KAGGLE_KEY in the environment (as retro_gen.py).
"""
import hashlib, json, os, random, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'plates')
INDEX = os.path.join(DIR, 'index.json'); PROMPTS = os.path.join(DIR, 'prompts.json'); KERNEL = os.path.join(DIR, 'kernel.py')
CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'plates-library'
SLUG = 'close-quarters-plates-gen'
sys.path.insert(0, HERE)
from retro_gen import kaggle, status, wait               # the same Kaggle plumbing


def index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {'plates': [], 'batches': []}


def save(idx):
    json.dump(idx, open(INDEX, 'w'), indent=1, ensure_ascii=False); open(INDEX, 'a').write('\n')


def kernel_id():
    user = os.environ.get('KAGGLE_USERNAME', '').strip()
    if not user: sys.exit('KAGGLE_USERNAME is not set')
    return '%s/%s' % (user, SLUG)


def plan(n, rng, themes=None):
    """n jobs over the themes with the fewest plates; in a theme its least-used scene and look."""
    bank = json.load(open(PROMPTS)); idx = index()
    have, used = {}, {}
    for c in idx['plates']:
        have[c['theme']] = have.get(c['theme'], 0) + 1; used[(c['theme'], c['scene'], c['look'])] = used.get((c['theme'], c['scene'], c['look']), 0) + 1
    names = [t for t in bank['themes'] if not themes or t in themes]; jobs = []
    for _ in range(n):
        th = min(names, key=lambda t: (have.get(t, 0), rng.random())); T = bank['themes'][th]
        sc, lk = min(((s, l) for s in range(len(T['scenes'])) for l in T['looks']), key=lambda sl: (used.get((th, sl[0], sl[1]), 0), rng.random()))
        have[th] = have.get(th, 0) + 1; used[(th, sc, lk)] = used.get((th, sc, lk), 0) + 1
        jobs.append(dict(id='%s-%d-%s-%04d' % (th, sc, lk, rng.randrange(10 ** 4)), theme=th, scene=sc, look=lk,
                         prompt='%s. %s' % (T['scenes'][sc], T['looks'][lk]), seed=rng.randrange(2 ** 31)))
    return jobs, bank


def push(api, jobs, bank, hours, steps):
    batch = time.strftime('%Y%m%d-%H%M%S')
    cfg = dict(batch=batch, hours=hours, steps=steps, width=bank.get('width', 832), height=bank.get('height', 1216), guidance=6.0,
               negative=bank['negative'])
    src = open(KERNEL).read().replace('JOBS = []', 'JOBS = ' + json.dumps(jobs), 1).replace('CFG = {}', 'CFG = ' + json.dumps(cfg), 1)
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


def collect(api, kid, want_batch=None):
    """Download the kernel's latest output and add its good plates to the library. Returns how many were added."""
    d = tempfile.mkdtemp()
    api.kernels_output(kid, d, force=True, quiet=True)
    for f in sorted(os.listdir(d)):
        if f.endswith('.log'): print(''.join(open(os.path.join(d, f), errors='replace').readlines()[-25:])[-3000:])
    man = os.path.join(d, 'manifest.json')
    if not os.path.exists(man): print('the run left no manifest: nothing to add'); return 0
    m = json.load(open(man)); idx = index()
    if m['batch'] in idx['batches']: print('batch %s is already in the library' % m['batch']); return 0
    if want_batch and m['batch'] != want_batch: print('the output is batch %s, not %s' % (m['batch'], want_batch))
    new, files = [], []
    for c in m['plates']:
        if not c.get('ok') or not c.get('file'): continue
        src = os.path.join(d, 'plates', c['file'])
        if not os.path.exists(src): continue
        name = hashlib.sha1(open(src, 'rb').read()).hexdigest()[:16] + '.jpg'; out = os.path.join(d, name); shutil.copy(src, out)
        files.append(out)
        new.append(dict(asset=name, theme=c['theme'], scene=c['scene'], look=c['look'], seed=c['seed'], prompt=c['prompt'],
                        model=c.get('model', m.get('model')), steps=c.get('steps'), batch=m['batch']))
        print('+ %-8s %-6s %s' % (c['theme'], c['look'], c['prompt'][:80]))
    if files:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Background plates (generated)', '--notes',
                            'Still pictures made with SDXL base 1.0 (CreativeML Open RAIL++-M) on Kaggle. Prompts and seeds: studio/plates/index.json'], check=True)
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    idx['plates'] += new; idx['batches'].append(m['batch']); save(idx)
    took = [c['seconds'] for c in m['plates'] if c.get('seconds')]
    print('added %d plates (batch %s; %.0f s a plate on %s)' % (len(new), m['batch'], sum(took) / max(1, len(took)), m.get('gpus')))
    for e in m.get('errors', []): print('kernel error:', str(e)[-1500:])
    shutil.rmtree(d, ignore_errors=True); return len(new)


def pull(themes=()):
    """Download the library's plates (all, or the given themes) that are not cached yet; returns their index entries."""
    os.makedirs(CACHE, exist_ok=True); want = [e for e in index().get('plates', []) if not themes or e['theme'] in themes]
    miss = [e['asset'] for e in want if not os.path.exists(os.path.join(CACHE, e['asset']))]
    for k in range(0, len(miss), 30):
        subprocess.run(['gh', 'release', 'download', RELEASE, '-R', REPO, '-D', CACHE, '--clobber'] + sum((['-p', a] for a in miss[k:k + 30]), []), check=True)
    return [e for e in want if os.path.exists(os.path.join(CACHE, e['asset']))]


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'pull': print(len(pull(tuple(sys.argv[2:]))), 'plates cached')
    elif cmd == 'quota': kaggle().quota_view_cli()
    elif cmd == 'collect':
        api = kaggle(); collect(api, kernel_id())
    elif cmd == 'run':
        api = kaggle(); kid = kernel_id(); hours = arg('--hours', 1.5)
        try:                                                     # a run the last job gave up waiting for: take its plates first
            st, _ = status(api, kid)
            if st == 'COMPLETE': collect(api, kid)
            elif st in ('RUNNING', 'QUEUED'): print('a run is still going on Kaggle; this one waits for it'); wait(api, kid, hours * 3600 + 2400); collect(api, kid)
        except SystemExit: raise
        except Exception as exc: print('no earlier run (%s)' % str(exc)[:120])
        themes = [t for t in arg('--themes', '').split(',') if t]
        jobs, bank = plan(arg('--plates', 120), random.Random(), themes)
        batch, ver = push(api, jobs, bank, hours, arg('--steps', 30))
        time.sleep(30)
        st, msg = wait(api, ver, min(hours * 3600 + 2400, 5.6 * 3600))
        if st == 'TIMEOUT': sys.exit('still running on Kaggle; the next run collects it')
        added = collect(api, ver, batch)
        if st != 'COMPLETE' and not added: sys.exit('the Kaggle run ended %s: %s' % (st, msg))
    else:
        print(__doc__)
