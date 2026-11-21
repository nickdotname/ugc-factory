#!/usr/bin/env python3
"""Make one information carousel and hand it to the publisher.

    python studio/post_carousel.py [--spec studio/carousels/<name>.json] [--account NAME]

Without --spec it takes the next carousel in studio/carousels/ that has not been posted
(alphabetical; posted ones are listed in studio/carousels/posted.json), so the daily job
works through them one at a time and stops when there are none left.

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
if a.spec: path = a.spec if os.path.exists(a.spec) else os.path.join(CDIR, a.spec + '.json')
else:
    todo = [f for f in sorted(glob.glob(os.path.join(CDIR, '*.json'))) if os.path.basename(f) != 'posted.json' and json.load(open(f))['slug'] not in done]
    if not todo: print('no carousel waiting'); sys.exit(0)
    path = todo[0]
spec = json.load(open(path)); name = a.account or spec.get('account') or ''
acct = next((x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts'] if x['name'] == name), None)
if not acct: sys.exit('no such account: %r' % name)
now = datetime.datetime.now(datetime.timezone.utc); tag = 'render-carousels-' + now.strftime('%Y-%m-%d')
tmp = tempfile.mkdtemp(); seed = int(hashlib.sha1(spec['slug'].encode()).hexdigest()[:6], 16) % 9973
subprocess.run([sys.executable, os.path.join(HERE, 'carousel.py'), path, str(seed), tmp], check=True)
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
print('held', pid, 'for', name, '(%d slides)' % len(urls))
if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('account=%s\n' % name)
