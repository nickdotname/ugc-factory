#!/usr/bin/env python3
"""Everything the Close Quarters dashboard (cqdash/) shows, in one file.

    python scripts/dash_data.py [OUT]        (default cqdash/data.json)

Run by the publish job every 15 minutes. Reads only what the repository already holds:
  outbox/igo-*.json            every post to an account that posts to Instagram directly: when it is due, whether it
                               went out, the video
  campaigns/*/queue.json       what is lined up, per campaign and account (Buffer accounts too)
  campaigns/*/history.json     which song and clip each post was, and which lineup entry if any
  campaigns/*/posts.json       each post's numbers (views, reach, likes, comments, shares, saves, watch time)
  campaigns/*/recipes.json     what each studio video is (its style and the knobs that say what it is about)
and, once a day, each account's profile picture from Instagram (with the IG_TOKEN* secrets in the environment).
"""
from pathlib import Path
import base64, glob, io, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLES = {'close_quarters_ig': 'close__quarters', 'dylancantor23_ig': 'dylancantor23', 'psychedelic_station_ig': 'psychedelic.station',
           'nostalgia_ig': 'nostalgia.hub.vhs', 'math_ig': 'math.explainers', 'glitch_ig': 'glitch.archive.exe',
           'ascii_ig': 'ascii.terminal.dreams', 'physics_ig': 'physics.bounce.lab', 'earth_ig': 'earth.data.live',
           'retro_ig': 'retro.vibes.arcade', 'rocket_ig': 'rocket.league.lit', 'nickdotname_ig': 'the.loose.change',
           'vintage_ig': 'vintage.media.archive', 'nyc_ig': 'nyc.daily.aesthetic', 'tinycode_ig': 'tiny.code.loops',
           'cinema_ig': 'ascii.cinema.tty', 'petri_ig': 'digital.petri.dish',
           'illusions_ig': 'rotation.illusions', 'races_ig': 'algorithm.races', 'tests8_ig': '8bit.tests', 'notes_ig': 'moth.ate.my.notes', 'toon_ig': 'rubberhose.radio', 'zoom_ig': 'zoom.into.art', 'date_ig': 'situationship.notes', 'lowpoly_ig': 'what.if.town', 'college_ig': 'dining.hall.philosopher', 'eyetrick_ig': 'eye.trick.lab', 'fourier_ig': 'fourier.reveal', 'her_ig': 'crying.in.trader.joes', 'him_ig': 'grip.tape.thoughts'}
NOT_CQ = {'clubs'}                   # campaigns that are not Close Quarters (the Clubs app's own posts)
# Accounts that posted other things before they were Close Quarters accounts: only the posts one of our campaigns made
# are shown (the.loose.change was nickdotname, the Clubs account, until mid-November).
OURS_ONLY = {'nickdotname_ig'}
METRICS = {'views': 'views', 'reach': 'reach', 'reactions': 'likes', 'comments': 'comments', 'shares': 'shares',
           'saves': 'saves', 'averageTimeWatched': 'watch', 'skipRate': 'skip', 'follows': 'follows'}
# the knobs that say what a studio video is about, per style (same idea as studio/nightly.py's SUBJECT)
WHAT = {'math': ['topic', 'subject', 'lineup', 'maze'], 'physics': ['scene', 'rule'], 'fluid': ['obstacle', 'view'], 'ascii': ['scene'],
        'psy': ['field'], 'collage': ['palette'], 'liminal': ['place'], 'earth': ['scene'], 'glitch': ['source'],
        'retro': ['theme', 'hook'], 'rocket': ['format'], 'type': ['layout'], 'band': ['wall'], 'producer': ['layout'],
        'lofi': ['theme', 'pop'], 'cursor': ['world'], 'growth': ['look'], 'vintage': ['tint', 'trip'], 'nyc': ['kind'], 'cutout': ['stage', 'bg'], 'tinycode': ['program'], 'cinema': ['look', 'cell'], 'alife': ['start', 'palette'], 'scene': ['scene', 'place'], 'illusion': ['kind', 'shape'], 'reveal': ['country'], 'stare': ['kind', 'scene'], 'ebru': ['pattern', 'palette'], 'measure': ['kind', 'palette'], 'hue': ['kind', 'set'], 'angle': ['kind', 'orient'], 'depth': ['shape', 'texture'], 'stopit': ['thing', 'ask']}


def read_yaml(path):
    """A YAML file, read and closed (a file left open for the collector to close is an error under the tests)."""
    with open(path) as f: return yaml.safe_load(f)


def load(path, default):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError):
        return default


GRAPH = 'https://graph.facebook.com/v27.0/'
PFP_EVERY = 86400                                 # seconds between fetches of an account's profile picture


def _get(url, token=None):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token} if token else {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _small(raw):
    """A profile picture as a small data: URL. Instagram's own picture links expire and refuse to load on other
    sites, so the picture itself goes in data.json (about 3 kB each at 96 px)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert('RGB'); im.thumbnail((96, 96))
        buf = io.BytesIO(); im.save(buf, 'JPEG', quality=82); raw = buf.getvalue()
    except Exception:
        pass                                         # no Pillow: the picture as Instagram sent it
    return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()


def pfps(accounts, old, campaign_of_account):
    """{account: (picture, when fetched)}: each Instagram account's profile picture, fetched again once a day. Accounts
    posted to directly ask for their own; one that is only on Buffer (the.loose.change) is looked up by its handle
    through one of ours (business discovery). A failed fetch keeps yesterday's picture, or the campaign's
    brand/profile.jpg if there has never been one."""
    prev = {a.get('name'): a for a in old.get('accounts') or []}
    now = datetime.now(timezone.utc)
    direct = {a['name']: a for a in accounts if a.get('provider') == 'instagram' and a.get('channel_id')
              and os.environ.get(a.get('api_key_secret') or '')}
    asker = next(iter(direct.values()), None)
    out = {}
    for name, handle in HANDLES.items():
        p = prev.get(name) or {}
        at = p.get('pfp_at')
        if p.get('pfp') and at and (now - datetime.fromisoformat(at.replace('Z', '+00:00'))).total_seconds() < PFP_EVERY:
            out[name] = (p['pfp'], at); continue
        a = direct.get(name)
        if a or asker:
            stamp = now.isoformat().replace('+00:00', 'Z')
            try:
                if a:
                    url = json.loads(_get(GRAPH + str(a['channel_id']) + '?fields=profile_picture_url', os.environ[a['api_key_secret']])).get('profile_picture_url')
                else:
                    f = urllib.parse.quote('business_discovery.username(%s){profile_picture_url}' % handle)
                    url = (json.loads(_get(GRAPH + str(asker['channel_id']) + '?fields=' + f, os.environ[asker['api_key_secret']]))
                           .get('business_discovery') or {}).get('profile_picture_url')
                if url:
                    out[name] = (_small(_get(url)), stamp); continue
            except Exception as e:                   # never the token: only what Instagram answered
                print('profile picture for %s: %s' % (handle, str(e)[:160]))
            if p.get('pfp'):
                out[name] = (p['pfp'], stamp); continue      # keep the old one; try again tomorrow
        brand = os.path.join(ROOT, 'campaigns', campaign_of_account.get(name) or '-', 'brand', 'profile.jpg')
        if p.get('pfp'): out[name] = (p['pfp'], at)
        elif os.path.exists(brand): out[name] = (_small(Path(brand).read_bytes()), None)
    return out


def iso(s):
    if not s: return None
    try:
        d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError:
        return None


def main(out):
    accounts = read_yaml(os.path.join(ROOT, 'accounts.yaml'))['accounts']
    by_channel = {str(a.get('channel_id')): a['name'] for a in accounts if a.get('channel_id')}
    posts = {}                                   # post id -> row
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    campaign_of_account = {}

    def row(pid):
        return posts.setdefault(pid, dict(id=pid, account=None, campaign=None, song=None, creative=None, clip=None, what=None,
                                          style=None, lineup=None, status=None, due=None, posted=None, caption='', video=None,
                                          trial=None, m={}, mt=None, via=None, error=None, image=None))

    for cdir in sorted(glob.glob(os.path.join(ROOT, 'campaigns', '*'))):
        camp = os.path.basename(cdir)
        if camp.startswith('_') or not os.path.exists(os.path.join(cdir, 'config.yaml')): continue
        cfg = read_yaml(os.path.join(cdir, 'config.yaml')) or {}
        if (cfg.get('posting') or {}).get('paused'): pass
        titles = {c['name']: c.get('title') or c['name'] for c in cfg.get('creatives') or []}
        acc_cfg = cfg.get('accounts') or {}
        names = [] if acc_cfg.get('mode') == 'block' else (acc_cfg.get('names') or [])   # a block list names where it does NOT post
        for n in names: campaign_of_account.setdefault(n, camp)
        rec = load(os.path.join(cdir, 'recipes.json'), {})
        recipe = {}
        for e in rec.get('nightly', []) if isinstance(rec, dict) else []:
            if e.get('clip'):
                kn = e.get('knobs') or {}
                what = [str(kn[k]) for k in WHAT.get(e.get('style'), []) if kn.get(k) not in (None, '')]
                recipe[(e.get('creative'), e['clip'])] = (e.get('style'), ' · '.join(what) or None)

        def fill(r, item, creative, clip):
            r['campaign'] = camp; r['creative'] = creative; r['song'] = titles.get(creative, creative); r['clip'] = clip
            r['lineup'] = item.get('lineup_id') or r['lineup']
            st, what = recipe.get((creative, clip), (None, None)); r['style'] = r['style'] or st; r['what'] = r['what'] or what

        for e in load(os.path.join(cdir, 'history.json'), {}).get('entries', []):
            for acc, pid in (e.get('post_ids') or {}).items():
                if not pid: continue
                r = row(pid); r['account'] = acc; fill(r, e, e.get('creative'), e.get('hook'))
                r['caption'] = r['caption'] or (e.get('caption') or '')
        q = load(os.path.join(cdir, 'queue.json'), {})
        for it in (q.get('items') if isinstance(q, dict) else q) or []:
            if not isinstance(it, dict): continue
            hook = (it.get('parts') or {}).get('hook')
            for p in it.get('posts') or []:
                pid = p.get('buffer_post_id') or 'q-%s-%s' % (it.get('id'), p.get('account'))
                r = row(pid); r['account'] = p.get('account'); fill(r, it, it.get('creative'), hook)
                r['due'] = r['due'] or iso(p.get('scheduled_for') or it.get('scheduled_for'))
                st = p.get('status')
                if st == 'pushed' and not str(pid).startswith('igo-'):        # handed to Buffer: Buffer posts it at its time
                    st = 'published' if r['due'] and r['due'] < now else 'scheduled'
                    if st == 'published': r['posted'] = r['posted'] or r['due']
                    r['via'] = 'buffer'
                r['status'] = r['status'] or st
                r['caption'] = (it.get('captions') or {}).get('instagram') or it.get('caption') or r['caption']
                r['video'] = r['video'] or it.get('video_url')
            if not it.get('posts') and it.get('status') == 'pending':             # rendered, not yet offered to any account
                for acc in names:                                                 # (a Buffer campaign waiting for room in the queue)
                    if acc not in HANDLES: continue
                    r = row('q-%s-%s' % (it.get('id'), acc)); r['account'] = acc; fill(r, it, it.get('creative'), hook)
                    r['due'] = r['due'] or iso(it.get('scheduled_for')); r['status'] = r['status'] or 'pending'
                    r['caption'] = (it.get('captions') or {}).get('instagram') or it.get('caption') or r['caption']
                    r['video'] = r['video'] or it.get('video_url')
        # What the scheduling backend (Buffer) holds for this campaign: the queue forgets a pushed item at the next
        # render, long before Buffer posts it, so half of the.loose.change's booked posts were on no page.
        for pid, b in (load(os.path.join(cdir, 'backend_queue.json'), {}).get('posts') or {}).items():
            r = row(pid); r['account'] = r['account'] or b.get('account'); r['campaign'] = r['campaign'] or camp
            r['due'] = r['due'] or iso(b.get('due')); r['via'] = r['via'] or 'buffer'
            if not r['status']:
                r['status'] = 'published' if r['due'] and r['due'] < now else 'scheduled'
                if r['status'] == 'published': r['posted'] = r['posted'] or r['due']
        for pid, p in (load(os.path.join(cdir, 'posts.json'), {}).get('posts') or {}).items():
            r = row(pid); r['account'] = r['account'] or p.get('account'); r['campaign'] = r['campaign'] or camp
            r['posted'] = r['posted'] or iso(p.get('sent_at')); r['status'] = 'published'
            r['mt'] = iso(p.get('fetched_at')) or r['mt']                      # when these numbers were read
            if r['via'] == 'buffer': r['via'] = 'buffer-confirmed'               # Buffer says it went out
            for m in p.get('metrics') or []:
                k = METRICS.get(m.get('type'))
                if k and m.get('value') is not None: r['m'][k] = round(float(m['value']), 2)

    for f in glob.glob(os.path.join(ROOT, 'outbox', 'igo-*.json')):
        d = load(f, {})
        if not d.get('id'): continue
        r = row(d['id'])
        r['account'] = by_channel.get(str(d.get('channel_id')), r['account'])
        r['status'] = d.get('status') or r['status']; r['due'] = iso(d.get('scheduled_for')) or r['due']
        r['posted'] = iso(d.get('published_at')) or r['posted']; r['caption'] = d.get('caption') or r['caption']
        r['video'] = d.get('video_url') or r['video']; r['trial'] = d.get('trial')
        if not r['video'] and d.get('image_urls'): r['image'] = (d.get('image_urls') or [None])[0]   # a carousel: its first picture
        if not r['campaign']: r['campaign'] = campaign_of_account.get(r['account'])
        if not r['song'] and d.get('audio_name'):                        # posts from before history kept their song
            r['song'] = str(d['audio_name']).split(' – ')[0]
        if r['status'] == 'failed': r['error'] = str(d.get('error') or d.get('last_error') or '')[:200] or None

    rows = []
    since = datetime.now(timezone.utc).timestamp() - 60 * 86400
    for r in posts.values():
        if r['account'] not in HANDLES or not r['status']: continue          # the Instagram accounts only (not old Buffer TikTok/YouTube)
        if r['campaign'] in NOT_CQ: continue                                 # Close Quarters only: not the Clubs app's posts
        if r['account'] in OURS_ONLY and not r['song']: continue            # posts from before the account was ours
        when = r['posted'] or r['due']
        if when and datetime.fromisoformat(when.replace('Z', '+00:00')).timestamp() < since: continue
        r['handle'] = HANDLES.get(r['account'], r['account'])
        r['caption'] = (r['caption'] or '').strip()[:400]
        rows.append(r)
    rows.sort(key=lambda r: r['posted'] or r['due'] or '', reverse=True)
    accs = list(HANDLES)
    old = load(out, {})
    pics = pfps(accounts, old, campaign_of_account)
    data = dict(generated=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                accounts=[dict(name=a, handle=HANDLES.get(a, a), campaign=campaign_of_account.get(a),
                               pfp=(pics.get(a) or (None, None))[0], pfp_at=(pics.get(a) or (None, None))[1],
                               numbers_at=max((r['mt'] for r in rows if r['account'] == a and r['mt']), default=None))
                          for a in accs],
                posts=rows)
    if old.get('posts') == json.loads(json.dumps(rows)) and old.get('accounts') == data['accounts']:
        print('no change since %s' % old.get('generated')); return      # nothing new: leave the file (and the repo) alone
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + '.tmp'
    with open(tmp, 'w') as f: json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(tmp, out)
    print('%d posts, %d accounts -> %s' % (len(rows), len(accs), out))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'cqdash', 'data.json'))
