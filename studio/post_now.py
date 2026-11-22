#!/usr/bin/env python3
"""Make one video in a given style right now and hand it to the publisher, to try a new look without
waiting for the nightly batch.

    python studio/post_now.py --campaign cq_band [--faces 1] [--song talk] [--no-post]

It picks a stretch of a song whose lyric timing is proven, renders it (studio/lyric_video.py in the
campaign's style), uploads it where Instagram can fetch it, and holds a post for the campaign's account
that is due now, with a caption from that song's own caption bank and the song's name as the sound.
Recorded in studio/tried.json.
"""
import argparse, datetime, glob, json, os, random, subprocess, sys, tempfile, uuid
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
STYLE = {'cq_band': 'band', 'cq_producer': 'producer'}
ap = argparse.ArgumentParser(); ap.add_argument('--campaign', required=True); ap.add_argument('--faces', default='1')
ap.add_argument('--song', default=''); ap.add_argument('--seed', type=int, default=0); ap.add_argument('--no-post', action='store_true'); a = ap.parse_args()
style = STYLE[a.campaign]
cfg = yaml.safe_load(open(os.path.join(REPO, 'campaigns', a.campaign, 'config.yaml')))
names = (cfg.get('accounts') or {}).get('names') or []
ACCTS = {x['name']: x for x in yaml.safe_load(open(os.path.join(REPO, 'accounts.yaml')))['accounts']}
acct = ACCTS[names[0]]
creatives = {c['name']: c for c in cfg.get('creatives') or []}
seed = a.seed or random.randrange(1000, 10 ** 6); rng = random.Random(seed)

# a proven stretch: a section whose every lyric line passed the timing checks, 12-18 seconds of it
cands = []
for sd in sorted(glob.glob(os.path.join(HERE, 'songs', '*'))):
    slug = os.path.basename(sd); cr = slug.replace('-', '_')
    if cr not in creatives or (a.song and a.song not in (slug, cr)) or not os.path.exists(os.path.join(sd, 'song.json')): continue
    song = json.load(open(os.path.join(sd, 'song.json')))
    for sec in song.get('sections', []):
        if sec.get('confidence', 0) >= 0.8 and sec['end'] - sec['start'] >= 10: cands.append((sd, slug, cr, song, sec))
if not cands: sys.exit('no proven stretch to use')
sd, slug, cr, song, sec = rng.choice(cands)
t0 = sec['start']; t1 = round(min(sec['end'], t0 + rng.uniform(12, 18)), 2)

tmp = tempfile.mkdtemp(); out = os.path.join(tmp, 'try.mp4')
env = dict(os.environ, CQ_WINDOW='%s,%s' % (t0, t1), CQ_FACES=a.faces, CQ_CRF='24', CQ_PRESET='medium', CQ_MAXRATE='4M', CQ_BUFSIZE='8M')
r = subprocess.run([sys.executable, os.path.join(HERE, 'lyric_video.py'), sd, style, str(seed), out], env=env, capture_output=True, text=True)
if r.returncode or not os.path.exists(out): sys.exit('render failed:\n' + r.stderr[-800:])
recipe = json.load(open(out[:-4] + '.json')) if os.path.exists(out[:-4] + '.json') else {}
print('rendered', slug, sec['id'], (t0, t1), 'faces', (recipe.get('plan') or {}).get('faces'))
if a.no_post: sys.exit(0)

now = datetime.datetime.now(datetime.timezone.utc); tag = 'render-tries-' + now.strftime('%Y-%m-%d'); nm = '%s.mp4' % uuid.uuid4()
os.rename(out, os.path.join(tmp, nm))
if subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=REPO).returncode != 0:
    subprocess.run(['gh', 'release', 'create', tag, '--title', tag, '--notes', 'Videos made to try a new style, served to Instagram by the site.'], check=True, cwd=REPO)
subprocess.run(['gh', 'release', 'upload', tag, os.path.join(tmp, nm)], check=True, cwd=REPO)
base = yaml.safe_load(open(os.path.join(REPO, 'site.yaml')))['media_base_url'].rstrip('/')
title = creatives[cr].get('title') or song.get('title') or slug
bank = os.path.join(REPO, 'campaigns', a.campaign, 'creatives', cr, 'captions.txt')
caps = [c.strip() for c in open(bank).read().split('\n---\n') if c.strip()] if os.path.exists(bank) else ['{name} – Close Quarters']
caption = rng.choice(caps).replace('{name}', title)
pid = 'igo-' + str(uuid.uuid4())
item = dict(id=pid, channel_id=str(acct['channel_id']), status='queued', video_url='%s/%s/%s' % (base, tag, nm), caption=caption, first_comment=None,
            share_to_feed=True, trial=bool(acct.get('trial_reels')), trial_graduation=acct.get('trial_graduation') if acct.get('trial_reels') else None,
            audio_id=None, audio_volume=None, video_volume=None, audio_name='%s – Close Quarters' % title,
            scheduled_for=now.isoformat(), created_at=now.isoformat(), attempts=0)
json.dump(item, open(os.path.join(REPO, 'outbox', pid + '.json'), 'w'), indent=2, sort_keys=True)
TP = os.path.join(HERE, 'tried.json'); tried = json.load(open(TP)) if os.path.exists(TP) else []
tried.append(dict(date=now.strftime('%Y-%m-%d'), campaign=a.campaign, account=names[0], post=pid, song=slug, section=sec['id'], window=[t0, t1], seed=seed, plan=recipe.get('plan')))
json.dump(tried, open(TP, 'w'), indent=1)
print('held', pid, 'for', names[0])
if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('account=%s\n' % names[0])
