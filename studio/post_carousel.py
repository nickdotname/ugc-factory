#!/usr/bin/env python3
"""Make one information carousel and hand it to the publisher.

    python studio/post_carousel.py [--spec studio/carousels/<name>.json] [--account NAME]

Without --spec it takes, for every account that has one waiting, the next carousel under
studio/carousels/ (subfolders included) that has not been posted (posted ones are listed in
studio/carousels/posted.json). Specs for an account not yet in accounts.yaml wait. A spec with
"theme": "retro" is drawn by carousel_retro.py, the rest by carousel.py.

It draws the slides (studio/carousel.py), uploads them to a release the site serves without
a login (Instagram fetches each slide by URL), and writes a held post into outbox/ that is
due now. `ugc publish-due` then sends it like any other held post.
"""
import argparse, datetime, glob, hashlib, json, os, subprocess, sys, tempfile, uuid
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); CDIR = os.path.join(HERE, 'carousels'); POSTED = os.path.join(CDIR, 'posted.json')
ap = argparse.ArgumentParser(); ap.add_argument('--spec', default=''); ap.add_argument('--account', default=''); a = ap.parse_args()
posted = json.load(open(POSTED)) if os.path.exists(POSTED) else []
done = {p['slug'] for p in posted}
ACCTS = {x['name']: x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts']}
SKIP = ('posted.json', 'reeled.json')

def waiting():
    """Every unposted spec, in folder then name order, with the account it is for."""
    out = []
    for f in sorted(glob.glob(os.path.join(CDIR, '**', '*.json'), recursive=True)):
        if os.path.basename(f) in SKIP: continue
        sp = json.load(open(f))
        if sp['slug'] not in done: out.append((f, sp.get('account', '')))
    return out

def make(path, name):
    spec = json.load(open(path)); acct = ACCTS.get(name)
    if not acct: print('skip %s: account %r is not set up yet' % (spec['slug'], name)); return None
    now = datetime.datetime.now(datetime.timezone.utc); tag = 'render-carousels-' + now.strftime('%Y-%m-%d')
    tmp = tempfile.mkdtemp(); seed = int(hashlib.sha1(spec['slug'].encode()).hexdigest()[:6], 16) % 9973
    drawer = 'carousel_retro.py' if spec.get('theme') == 'retro' else 'carousel.py'
    subprocess.run([sys.executable, os.path.join(HERE, drawer), path, str(seed), tmp], check=True)
    base = yaml.safe_load(open(os.path.join(REPO, 'site.yaml')))['media_base_url'].rstrip('/'); uid = str(uuid.uuid4()); files, urls = [], []
    for i, f in enumerate(sorted(glob.glob(os.path.join(tmp, '*.jpg'))), 1):
        n = '%s-s%02d.jpg' % (uid, i); os.rename(f, os.path.join(tmp, n)); files.append(os.path.join(tmp, n)); urls.append('%s/%s/%s' % (base, tag, n))
    if subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=REPO).returncode != 0:
        subprocess.run(['gh', 'release', 'create', tag, '--title', tag, '--notes', 'Carousel slides, served to Instagram by the site.'], check=True, cwd=REPO)
    subprocess.run(['gh', 'release', 'upload', tag, *files], check=True, cwd=REPO)
    pid = 'igo-' + str(uuid.uuid4())
    item = dict(id=pid, channel_id=str(acct['channel_id']), status='queued', video_url=None, image_urls=urls, caption=spec['caption'], first_comment=None,
                share_to_feed=True, trial=False, trial_graduation=None, audio_id=None, audio_volume=None, video_volume=None,
                scheduled_for=now.isoformat(), created_at=now.isoformat(), attempts=0)
    os.makedirs(os.path.join(REPO, 'outbox'), exist_ok=True); json.dump(item, open(os.path.join(REPO, 'outbox', pid + '.json'), 'w'), indent=2, sort_keys=True)
    posted.append(dict(slug=spec['slug'], date=now.strftime('%Y-%m-%d'), post=pid, account=name, slides=len(urls))); json.dump(posted, open(POSTED, 'w'), indent=1)
    print('held', pid, 'for', name, '(%d slides)' % len(urls)); return name

if a.spec:
    path = a.spec if os.path.exists(a.spec) else os.path.join(CDIR, a.spec + '.json')
    made = [make(path, a.account or json.load(open(path)).get('account', ''))]
else:
    # one carousel per account per run: the oldest waiting spec for each account that exists
    first = {}
    for f, n in waiting():
        if (not a.account or n == a.account) and n in ACCTS: first.setdefault(n, f)
    if not first: print('no carousel waiting'); sys.exit(0)
    made = [make(f, n) for n, f in sorted(first.items())]
made = [m for m in made if m]
if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('accounts=%s\n' % ' '.join(made))
