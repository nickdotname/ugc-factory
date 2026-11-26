#!/usr/bin/env python3
"""Make one fact reel and hand it to the publisher.

    python studio/post_factreel.py [--spec <carousel slug>] [--account NAME] [--no-post]

A fact reel is a carousel told in 15 seconds: the headline and three of its slides as text cards over
the audio-reactive visuals, with a stretch of a Close Quarters song under it, ending on a pointer to the
full carousel. For every account, it takes the oldest carousel already posted that has no reel yet, so every reel has a
carousel on the profile to send people to. Recorded in studio/carousels/reeled.json.
"""
import argparse, datetime, glob, json, os, random, re, subprocess, sys, tempfile, uuid
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); CDIR = os.path.join(HERE, 'carousels')
ap = argparse.ArgumentParser(); ap.add_argument('--spec', default=''); ap.add_argument('--account', default=''); ap.add_argument('--no-post', action='store_true'); a = ap.parse_args()
posted = json.load(open(os.path.join(CDIR, 'posted.json'))) if os.path.exists(os.path.join(CDIR, 'posted.json')) else []
RP = os.path.join(CDIR, 'reeled.json'); reeled = json.load(open(RP)) if os.path.exists(RP) else []
specs = {json.load(open(f))['slug']: f for f in glob.glob(os.path.join(CDIR, '**', '*.json'), recursive=True) if os.path.basename(f) not in ('posted.json', 'reeled.json') and json.load(open(f)).get('theme') != 'band'}
ACCTS = {x['name']: x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts']}
# Per look: the renderer that draws the visuals and the tags the caption ends on.
LOOKS = {'retro': ('liminal_video.py', '#nostalgia #2000s #90skids #liminalspaces #y2k'),
         '':      ('psy_video.py',     '#psychedelic #declassified #rabbithole #conspiracy #history')}
OPEN_S, END_S = 2.8, 2.4

def read_time(text):
    """Seconds a slide stays up: a beat for the big word, then ~4 words a second, kept between 3 and 5.5 s."""
    return min(5.5, max(3.0, 1.2 + 0.26 * len(text.split())))

def reel_line(spec):
    """The caption's first line for a reel: the carousel's hook without its 'slide 5 is ...' sentence (there are no
    slides in a reel), or the spec's own reel_hook when it has one."""
    if spec.get('reel_hook'): return spec['reel_hook']
    first = spec['caption'].split('\n')[0]
    kept = [x for x in re.split(r'(?<=[.!?])\s+', first) if not re.search(r'\b(slide|swipe)\b', x, re.I)]
    return ' '.join(kept).strip() or spec['headline'].rstrip('.').lower()

count = {}
for r in reeled: count[r['slug']] = count.get(r['slug'], 0) + 1

def clear_slot(channel_id, now, gap_min=60):
    """The first minute from now at least gap_min from every post the account holds or has sent (outbox/). topup keeps
    its own slots an hour apart and the publisher holds a post that follows another within MIN_GAP, but a post due
    'now' from this job landed beside whatever topup had already booked for the next hour: psychedelic.station had 62
    of 88 posts within 45 minutes of another (docs/brain/reviews/2026-11-26). The same helper is in post_carousel.py."""
    times = []
    for f in glob.glob(os.path.join(REPO, 'outbox', '*.json')):
        it = json.load(open(f))
        if str(it.get('channel_id')) != str(channel_id) or it.get('status') not in ('queued', 'publishing', 'published'): continue
        try: t = datetime.datetime.fromisoformat(it.get('published_at') if it.get('status') == 'published' else it.get('scheduled_for'))
        except (TypeError, ValueError): continue
        times.append(t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc))
    gap, when = datetime.timedelta(minutes=gap_min), now
    while when < now + datetime.timedelta(hours=24) and any(abs(when - t) < gap for t in times): when += datetime.timedelta(minutes=5)
    return when

def reel(slug, name):
    """Each posted carousel gets two reels: part 1 tells slides 1-3, part 2 picks up at slide 4 for people who
    saw part 1 (and its own hook for people who didn't)."""
    part = count.get(slug, 0) + 1
    spec = json.load(open(specs[slug])); acct = ACCTS.get(name)
    if not acct: print('skip %s: account %r is not set up yet' % (slug, name)); return None
    renderer, tags = LOOKS.get(spec.get('theme', ''), LOOKS[''])
    rng = random.Random(slug + datetime.date.today().isoformat() + str(part))

    # the cards: hook, three slides, the pointer. The headline is on screen from frame 0 (it is the cover and the
    # hook); each slide stays long enough to read at a comfortable pace (about 4 words a second plus a beat for the
    # big word), instead of the old flat 3.3 s that cut 25-word slides off mid-sentence. ~15-20 s in all.
    slides = spec['slides'][:3] if part == 1 else spec['slides'][3:6]
    opener = spec['headline'] if part == 1 else 'Part 2: ' + spec['headline'][0].lower() + spec['headline'][1:]
    cards = [[0, OPEN_S, '', opener]]; t = OPEN_S
    for b, txt, *_ in slides:                                                                 # a slide may also name its pictures
        d = read_time(txt); cards.append([round(t, 2), round(t + d, 2), b, txt]); t += d
    cards.append([round(t, 2), round(t + END_S, 2), 'the full story', 'all 6 slides and the sources are in the carousel on our page.'])
    dur = round(t + END_S, 2)

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
    if spec.get('place'): env['CQ_PLACE'] = spec['place']          # a retro reel's room matches its story (a mall for Blockbuster)
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
    first = reel_line(spec) if part == 1 else 'part 2 of ' + spec['headline'].rstrip('.').lower()
    caption = '%s\nthe full story, with sources, is the carousel on our page\n🎧 %s – @close__quarters %s' % (first, title, tags)
    pid = 'igo-' + str(uuid.uuid4()); due = clear_slot(acct['channel_id'], now)
    import collabs                                   # one collab post a day brings the band account in
    collab = collabs.invite(name, sum(1 for r in reeled if r.get('account') == name and r.get('date') == now.strftime('%Y-%m-%d') and r.get('collab')))
    item = dict(id=pid, channel_id=str(acct['channel_id']), status='queued', video_url='%s/%s/%s' % (base, tag, nm), caption=caption, first_comment=None,
                collaborators=collab or None,
                share_to_feed=True, trial=False, trial_graduation=None, audio_id=None, audio_volume=None, video_volume=None,
                audio_name='%s – Close Quarters' % title, scheduled_for=due.isoformat(), created_at=now.isoformat(), attempts=0)
    json.dump(item, open(os.path.join(REPO, 'outbox', pid + '.json'), 'w'), indent=2, sort_keys=True)
    reeled.append(dict(slug=slug, part=part, date=now.strftime('%Y-%m-%d'), post=pid, account=name, song=os.path.basename(sd), window=[t0, round(t0 + dur, 2)], seed=seed, collab=collab))
    count[slug] = part; json.dump(reeled, open(RP, 'w'), indent=1)
    print('held', pid, 'for', name, 'due', due.strftime('%H:%M UTC')); return name

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
