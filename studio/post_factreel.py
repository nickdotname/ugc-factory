#!/usr/bin/env python3
"""Make one fact reel and hand it to the publisher.

    python studio/post_factreel.py [--spec <carousel slug>] [--account NAME] [--no-post]

A fact reel is a carousel told in 15 seconds: the headline and three of its slides as text cards over
the audio-reactive visuals, with a stretch of a Close Quarters song under it, ending on a pointer to the
full carousel. For every account, it takes the oldest carousel already posted that has no reel yet, so every reel has a
carousel on the profile to send people to. Recorded in studio/carousels/reeled.json.
"""
import argparse, datetime, glob, json, os, random, subprocess, sys, tempfile, uuid
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); CDIR = os.path.join(HERE, 'carousels')
ap = argparse.ArgumentParser(); ap.add_argument('--spec', default=''); ap.add_argument('--account', default=''); ap.add_argument('--no-post', action='store_true'); a = ap.parse_args()
posted = json.load(open(os.path.join(CDIR, 'posted.json'))) if os.path.exists(os.path.join(CDIR, 'posted.json')) else []
RP = os.path.join(CDIR, 'reeled.json'); reeled = json.load(open(RP)) if os.path.exists(RP) else []
specs = {json.load(open(f))['slug']: f for f in glob.glob(os.path.join(CDIR, '**', '*.json'), recursive=True) if os.path.basename(f) not in ('posted.json', 'reeled.json')}
ACCTS = {x['name']: x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts']}
# Per look: the renderer that draws the visuals and the tags the caption ends on.
LOOKS = {'retro': ('liminal_video.py', '#nostalgia #2000s #90skids #childhood #liminalspaces #y2k'),
         '':      ('psy_video.py',     '#psychedelic #declassified #rabbithole #conspiracy #history')}
count = {}
for r in reeled: count[r['slug']] = count.get(r['slug'], 0) + 1

def reel(slug, name):
    """Each posted carousel gets two reels: part 1 tells slides 1-3, part 2 picks up at slide 4 for people who
    saw part 1 (and its own hook for people who didn't)."""
    part = count.get(slug, 0) + 1
    spec = json.load(open(specs[slug])); acct = ACCTS.get(name)
    if not acct: print('skip %s: account %r is not set up yet' % (slug, name)); return None
    renderer, tags = LOOKS.get(spec.get('theme', ''), LOOKS[''])
    rng = random.Random(slug + datetime.date.today().isoformat() + str(part))

    # the cards: hook, three slides, the pointer. ~3.3s each, so ~16.5s and it loops.
    slides = spec['slides'][:3] if part == 1 else spec['slides'][3:6]; D = 3.3
    opener = spec['headline'] if part == 1 else 'Part 2: ' + spec['headline'][0].lower() + spec['headline'][1:]
    cards = [[0, D, '', opener]] + [[D * (k + 1), D * (k + 2), b, t] for k, (b, t) in enumerate(slides)]
    cards.append([D * 4, D * 5, 'swipe the full story', 'it is on our page. 6 slides, sources on the last one.'])
    dur = D * 5

    # the music: a stretch of a Close Quarters song, at its own speed
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
    r = subprocess.run([sys.executable, os.path.join(HERE, renderer), sd, str(seed), out], env=env, capture_output=True, text=True)
    if r.returncode or not os.path.exists(out): sys.exit('render failed:\n' + r.stderr[-800:])
    print('rendered', out, 'from', title, t0, 'with', renderer)
    if a.no_post: return None

    now = datetime.datetime.now(datetime.timezone.utc); tag = 'render-factreels-' + now.strftime('%Y-%m-%d')
    nm = '%s.mp4' % uuid.uuid4(); os.rename(out, os.path.join(tmp, nm))
    if subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=REPO).returncode != 0:
        subprocess.run(['gh', 'release', 'create', tag, '--title', tag, '--notes', 'Fact reels, served to Instagram by the site.'], check=True, cwd=REPO)
    subprocess.run(['gh', 'release', 'upload', tag, os.path.join(tmp, nm)], check=True, cwd=REPO)
    base = yaml.safe_load(open(os.path.join(REPO, 'site.yaml')))['media_base_url'].rstrip('/')
    first = spec['caption'].split('\n')[0] if part == 1 else 'part 2 of ' + spec['headline'].rstrip('.').lower()
    caption = '%s\nthe full story is the carousel on our page\n🎧 %s – @close__quarters %s' % (first, title, tags)
    pid = 'igo-' + str(uuid.uuid4())
    item = dict(id=pid, channel_id=str(acct['channel_id']), status='queued', video_url='%s/%s/%s' % (base, tag, nm), caption=caption, first_comment=None,
                share_to_feed=True, trial=False, trial_graduation=None, audio_id=None, audio_volume=None, video_volume=None,
                audio_name='%s – Close Quarters' % title, scheduled_for=now.isoformat(), created_at=now.isoformat(), attempts=0)
    json.dump(item, open(os.path.join(REPO, 'outbox', pid + '.json'), 'w'), indent=2, sort_keys=True)
    reeled.append(dict(slug=slug, part=part, date=now.strftime('%Y-%m-%d'), post=pid, account=name, song=os.path.basename(sd), window=[t0, round(t0 + dur, 2)], seed=seed))
    count[slug] = part; json.dump(reeled, open(RP, 'w'), indent=1)
    print('held', pid, 'for', name); return name

if a.spec:
    made = [reel(a.spec, a.account or json.load(open(specs[a.spec])).get('account', ''))]
else:
    # one reel per account per run: oldest carousel first, part 1 before any part 2
    best = {}
    for i, p in enumerate(posted):
        n = p.get('account', '')
        if p['slug'] in specs and count.get(p['slug'], 0) < 2 and n in ACCTS and (not a.account or n == a.account):
            k = (count.get(p['slug'], 0), i, p['slug'])
            if n not in best or k < best[n]: best[n] = k
    if not best: print('no carousel waiting for a reel'); sys.exit(0)
    made = [reel(k[2], n) for n, k in sorted(best.items())]
made = [m for m in made if m]
if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('accounts=%s\n' % ' '.join(made))
