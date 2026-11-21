#!/usr/bin/env python3
"""Make one fact reel and hand it to the publisher.

    python studio/post_factreel.py [--spec <carousel slug>] [--account NAME] [--no-post]

A fact reel is a carousel told in 15 seconds: the headline and three of its slides as text cards over
the audio-reactive visuals, with a stretch of a Close Quarters song under it, ending on a pointer to the
full carousel. It takes the oldest carousel already posted that has no reel yet, so every reel has a
carousel on the profile to send people to. Recorded in studio/carousels/reeled.json.
"""
import argparse, datetime, glob, json, os, random, subprocess, sys, tempfile, uuid
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); CDIR = os.path.join(HERE, 'carousels')
ap = argparse.ArgumentParser(); ap.add_argument('--spec', default=''); ap.add_argument('--account', default=''); ap.add_argument('--no-post', action='store_true'); a = ap.parse_args()
posted = json.load(open(os.path.join(CDIR, 'posted.json'))) if os.path.exists(os.path.join(CDIR, 'posted.json')) else []
RP = os.path.join(CDIR, 'reeled.json'); reeled = json.load(open(RP)) if os.path.exists(RP) else []
specs = {json.load(open(f))['slug']: f for f in glob.glob(os.path.join(CDIR, '*.json')) if os.path.basename(f) not in ('posted.json', 'reeled.json')}
if a.spec: slug = a.spec
else:
    done = {r['slug'] for r in reeled}; todo = [p['slug'] for p in posted if p['slug'] not in done and p['slug'] in specs]
    if not todo: print('no carousel waiting for a reel'); sys.exit(0)
    slug = todo[0]
spec = json.load(open(specs[slug])); name = a.account or spec.get('account') or ''
acct = next((x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts'] if x['name'] == name), None)
if not acct: sys.exit('no such account: %r' % name)
rng = random.Random(slug + datetime.date.today().isoformat())

# the cards: hook, three slides, the pointer. ~3.3s each, so ~16.5s and it loops.
slides = spec['slides'][:3]; D = 3.3
cards = [[0, D, '', spec['headline']]] + [[D * (k + 1), D * (k + 2), b, t] for k, (b, t) in enumerate(slides)]
cards.append([D * 4, D * 5, 'swipe the full story', 'it is on our page. 6 slides, sources on the last one.'])
dur = D * 5

# the music: a stretch of a song with drums under it, from the songs the account uses
sys.path.insert(0, HERE); import importlib.util
songs = []
for sd in sorted(glob.glob(os.path.join(HERE, 'songs', '*'))):
    sj = os.path.join(sd, 'song.json')
    if not os.path.exists(sj): continue
    s = json.load(open(sj))
    for sec in s.get('sections', []):
        if sec['end'] - sec['start'] >= dur + 1: songs.append((sd, s.get('title') or os.path.basename(sd), sec))
if not songs: sys.exit('no song stretch long enough')
sd, title, sec = rng.choice(songs); t0 = round(sec['start'] + rng.uniform(0, sec['end'] - sec['start'] - dur), 2)

tmp = tempfile.mkdtemp(); cj = os.path.join(tmp, 'cards.json'); json.dump(cards, open(cj, 'w'))
out = os.path.join(tmp, 'factreel.mp4'); seed = rng.randrange(1000, 10 ** 6)
env = dict(os.environ, CQ_WINDOW='%s,%s' % (t0, round(t0 + dur, 2)), CQ_CARDS=cj, CQ_LYRICS='none', CQ_HOOK='none', CQ_CRF='23', CQ_PRESET='medium', CQ_MAXRATE='6M', CQ_BUFSIZE='12M')
r = subprocess.run([sys.executable, os.path.join(HERE, 'psy_video.py'), sd, str(seed), out], env=env, capture_output=True, text=True)
if r.returncode or not os.path.exists(out): sys.exit('render failed:\n' + r.stderr[-800:])
print('rendered', out, 'from', title, t0)
if a.no_post: sys.exit(0)

now = datetime.datetime.now(datetime.timezone.utc); tag = 'render-factreels-' + now.strftime('%Y-%m-%d')
nm = '%s.mp4' % uuid.uuid4(); os.rename(out, os.path.join(tmp, nm))
if subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=REPO).returncode != 0:
    subprocess.run(['gh', 'release', 'create', tag, '--title', tag, '--notes', 'Fact reels, served to Instagram by the site.'], check=True, cwd=REPO)
subprocess.run(['gh', 'release', 'upload', tag, os.path.join(tmp, nm)], check=True, cwd=REPO)
base = yaml.safe_load(open(os.path.join(REPO, 'site.yaml')))['media_base_url'].rstrip('/')
first = spec['caption'].split('\n')[0]
caption = '%s\nthe full story is the carousel on our page\n🎧 %s – @close__quarters #psychedelic #declassified #rabbithole #conspiracy #history' % (first, title)
pid = 'igo-' + str(uuid.uuid4())
item = dict(id=pid, channel_id=str(acct['channel_id']), status='queued', video_url='%s/%s/%s' % (base, tag, nm), caption=caption, first_comment=None,
            share_to_feed=True, trial=False, trial_graduation=None, audio_id=None, audio_volume=None, video_volume=None,
            audio_name='%s – Close Quarters' % title, scheduled_for=now.isoformat(), created_at=now.isoformat(), attempts=0)
json.dump(item, open(os.path.join(REPO, 'outbox', pid + '.json'), 'w'), indent=2, sort_keys=True)
reeled.append(dict(slug=slug, date=now.strftime('%Y-%m-%d'), post=pid, account=name, song=os.path.basename(sd), window=[t0, round(t0 + dur, 2)], seed=seed))
json.dump(reeled, open(RP, 'w'), indent=1)
print('held', pid, 'for', name)
if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('account=%s\n' % name)
