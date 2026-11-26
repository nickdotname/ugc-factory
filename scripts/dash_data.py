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
and, once a day, each account's profile picture and follower count from Instagram (with the IG_TOKEN* secrets in the
environment; the counts are kept for 90 days in cqdash/followers.json), and the bio-link taps from link/worker.js.
"""
from pathlib import Path
import base64, glob, io, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDLES = {'close_quarters_ig': 'close__quarters', 'dylancantor23_ig': 'dylancantor23', 'psychedelic_station_ig': 'psychedelic.station',
           'nostalgia_ig': 'nostalgia.hub.vhs', 'math_ig': 'math.explainers', 'glitch_ig': 'glitch.archive.exe',
           'ascii_ig': 'ascii.terminal.dreams', 'physics_ig': 'physics.bounce.lab', 'earth_ig': 'earth.data.live',
           'retro_ig': 'retro.vibes.arcade', 'rocket_ig': 'rocket.league.lit', 'nickdotname_ig': 'the.loose.change',
           'vintage_ig': 'vintage.media.archive', 'nyc_ig': 'nyc.daily.aesthetic', 'tinycode_ig': 'tiny.code.loops',
           'cinema_ig': 'ascii.cinema.tty', 'petri_ig': 'digital.petri.dish',
           'illusions_ig': 'rotation.illusions', 'races_ig': 'algorithm.races', 'tests8_ig': '8bit.tests', 'notes_ig': 'moth.ate.my.notes', 'toon_ig': 'rubberhose.radio', 'zoom_ig': 'zoom.into.art', 'date_ig': 'situationship.notes', 'lowpoly_ig': 'what.if.town', 'college_ig': 'dining.hall.philosopher', 'eyetrick_ig': 'eye.trick.lab', 'fourier_ig': 'fourier.reveal', 'her_ig': 'crying.in.trader.joes', 'him_ig': 'grip.tape.thoughts'}
# Each account's bio link: its path on link/worker.js (the table in link/README.md; studio/learn.py's LINK_NAMES is the same)
LINKS = {'cq': 'close_quarters_ig', 'dc': 'dylancantor23_ig', 'psy': 'psychedelic_station_ig', 'nostalgia': 'nostalgia_ig',
         'math': 'math_ig', 'glitch': 'glitch_ig', 'ascii': 'ascii_ig', 'physics': 'physics_ig', 'earth': 'earth_ig',
         'retro': 'retro_ig', 'rocket': 'rocket_ig', 'loose': 'nickdotname_ig', 'vintage': 'vintage_ig', 'nyc': 'nyc_ig',
         'tinycode': 'tinycode_ig', 'cinema': 'cinema_ig', 'petri': 'petri_ig', 'illusions': 'illusions_ig', 'races': 'races_ig',
         '8bit': 'tests8_ig', 'notes': 'notes_ig', 'toon': 'toon_ig', 'zoom': 'zoom_ig', 'date': 'date_ig', 'lowpoly': 'lowpoly_ig',
         'college': 'college_ig', 'eyetrick': 'eyetrick_ig', 'fourier': 'fourier_ig', 'her': 'her_ig', 'him': 'him_ig'}
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
        'lofi': ['theme', 'pop'], 'cursor': ['world'], 'growth': ['look'], 'vintage': ['tint', 'trip'], 'nyc': ['kind'], 'cutout': ['stage', 'bg'], 'tinycode': ['program'], 'cinema': ['look', 'cell'], 'alife': ['start', 'palette'], 'scene': ['scene', 'place'], 'illusion': ['kind', 'shape'], 'reveal': ['country'], 'stare': ['kind', 'scene'], 'ebru': ['pattern', 'palette'], 'measure': ['kind', 'palette'], 'hue': ['kind', 'set'], 'stopit': ['thing', 'ask']}


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


PROFILE_FIELDS = 'profile_picture_url,followers_count,follows_count,media_count'
COUNTS = {'followers': 'followers_count', 'follows': 'follows_count', 'media': 'media_count'}
KEEP_DAYS = 90                                    # days of follower counts kept in cqdash/followers.json


def profiles(accounts, old, campaign_of_account, hist, now=None):
    """{account: {pfp, pfp_at}}: each Instagram account's profile picture, fetched again once a day together with its
    follower, following and post counts. Accounts posted to directly ask for their own; one that is only on Buffer
    (the.loose.change), or whose token cannot read it, is looked up by its handle through one of ours (business
    discovery). A failed fetch keeps yesterday's picture, or the campaign's brand/profile.jpg if there has never been
    one. Each fetch adds the day's row to hist ({account: {day: {followers, follows, media}}}, the follower log),
    trimmed to KEEP_DAYS."""
    prev = {a.get('name'): a for a in old.get('accounts') or []}
    now = now or datetime.now(timezone.utc)
    direct = {a['name']: a for a in accounts if a.get('provider') == 'instagram' and a.get('channel_id')
              and os.environ.get(a.get('api_key_secret') or '')}
    asker = next(iter(direct.values()), None)
    out = {}
    for name, handle in HANDLES.items():
        p = prev.get(name) or {}
        keep = {'pfp': p.get('pfp'), 'pfp_at': p.get('pfp_at')}
        at = p.get('pfp_at')
        if p.get('pfp') and at and (now - datetime.fromisoformat(at.replace('Z', '+00:00'))).total_seconds() < PFP_EVERY:
            out[name] = keep; continue
        a = direct.get(name)
        if a or asker:
            stamp = now.isoformat().replace('+00:00', 'Z')
            prof = {}
            try:
                if a:
                    try:
                        prof = json.loads(_get(GRAPH + str(a['channel_id']) + '?fields=' + PROFILE_FIELDS, os.environ[a['api_key_secret']]))
                    except Exception as e:           # the shared token cannot read every account it posts to: ask by handle
                        print('profile of %s by its own token: %s' % (handle, str(e)[:160])); prof = {}
                if not prof.get('profile_picture_url') and asker:
                    f = urllib.parse.quote('business_discovery.username(%s){%s}' % (handle, PROFILE_FIELDS))
                    prof = json.loads(_get(GRAPH + str(asker['channel_id']) + '?fields=' + f, os.environ[asker['api_key_secret']])).get('business_discovery') or {}
                url = prof.get('profile_picture_url')
                if url:
                    keep.update(pfp=_small(_get(url)), pfp_at=stamp)
                    counts = {k: int(prof[fld]) for k, fld in COUNTS.items() if prof.get(fld) is not None}
                    if counts: hist.setdefault(name, {})[now.date().isoformat()] = counts
                    out[name] = keep; continue
            except Exception as e:                   # never the token: only what Instagram answered
                print('profile picture for %s: %s' % (handle, str(e)[:160]))
            if p.get('pfp'):
                keep['pfp_at'] = stamp; out[name] = keep; continue      # keep the old one; try again tomorrow
        brand = os.path.join(ROOT, 'campaigns', campaign_of_account.get(name) or '-', 'brand', 'profile.jpg')
        if p.get('pfp'): out[name] = keep
        elif os.path.exists(brand): keep['pfp'] = _small(Path(brand).read_bytes()); out[name] = keep
    first = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    for name in list(hist):
        hist[name] = {d: r for d, r in sorted(hist[name].items()) if d >= first}
    return out


def followers(hist, name, today):
    """What an account's card shows of its follower log: the latest count, the change over 7 days (from the row 7 days
    back, else the oldest row within the week, with its day), and the last 14 days for a line."""
    rows = hist.get(name) or {}
    if not rows: return {}
    days = sorted(rows)
    cur_day = days[-1]; cur = rows[cur_day].get('followers')
    week = (today - timedelta(days=7)).isoformat()
    base = week if week in rows else next((d for d in days if week < d < cur_day), None)
    out = dict(followers=cur, follows=rows[cur_day].get('follows'), media=rows[cur_day].get('media'), followers_at=cur_day,
               followers_log={d: rows[d].get('followers') for d in days[-14:]})
    if base and cur is not None and rows[base].get('followers') is not None:
        out.update(followers_7d=cur - rows[base]['followers'], followers_since=base)
    return out


def taps(old):
    """{account: {link, taps7, taps, tap_last}}: each account's bio-link path and its last 7 days of taps, from
    link/worker.js's /stats (no secret needed). When the worker cannot be read, each account keeps what the last
    data.json said."""
    prev = {a.get('name'): a for a in old.get('accounts') or []}
    out = {name: {f: (prev.get(name) or {}).get(f) for f in ('taps7', 'taps', 'tap_last')} | {'link': '/' + k} for k, name in LINKS.items()}
    site = os.path.join(ROOT, 'site.yaml')
    if not os.path.exists(site): return out
    try:
        base = (read_yaml(site) or {}).get('link_base') or ''
        stats = json.loads(_get(base.rstrip('/') + '/stats')) if base else None
    except Exception as e:
        print('bio link taps: %s' % str(e)[:160]); return out
    if not isinstance(stats, dict): return out
    days = sorted(d for d in stats if d[:2] == '20' and isinstance(stats[d], dict))[-7:]
    last = stats.get('last') if isinstance(stats.get('last'), dict) else {}
    for k, name in LINKS.items():
        row = [int((stats[d] or {}).get(k, 0)) for d in days]
        at = last.get(k) if isinstance(last.get(k), dict) else {}
        out[name].update(taps=row, taps7=sum(row), tap_last=at.get('at'))
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
    # The follower log, one row per account per day. If the file was lost (not committed yet), the last 14 days are
    # rebuilt from what the accounts in the old data.json carried, so a delta is never lost with it.
    log_path = os.path.join(os.path.dirname(os.path.abspath(out)), 'followers.json')
    hist = (load(log_path, {}).get('accounts') or {})
    for a in old.get('accounts') or []:
        for d, n in (a.get('followers_log') or {}).items():
            if n is not None: hist.setdefault(a['name'], {}).setdefault(d, {'followers': n})
    before = json.dumps(hist, sort_keys=True)
    prof = profiles(accounts, old, campaign_of_account, hist)
    today = datetime.now(timezone.utc).date()
    tapped = taps(old)
    data = dict(generated=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                accounts=[dict(name=a, handle=HANDLES.get(a, a), campaign=campaign_of_account.get(a),
                               pfp=(prof.get(a) or {}).get('pfp'), pfp_at=(prof.get(a) or {}).get('pfp_at'),
                               numbers_at=max((r['mt'] for r in rows if r['account'] == a and r['mt']), default=None),
                               **followers(hist, a, today), **(tapped.get(a) or {}))
                          for a in accs],
                posts=rows)
    if json.dumps(hist, sort_keys=True) != before:
        with open(log_path + '.tmp', 'w') as f: json.dump(dict(updated=data['generated'], accounts=hist), f, indent=0, sort_keys=True)
        os.replace(log_path + '.tmp', log_path)
    if old.get('posts') == json.loads(json.dumps(rows)) and old.get('accounts') == json.loads(json.dumps(data['accounts'])):
        print('no change since %s' % old.get('generated')); return      # nothing new: leave the file (and the repo) alone
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + '.tmp'
    with open(tmp, 'w') as f: json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(tmp, out)
    print('%d posts, %d accounts -> %s' % (len(rows), len(accs), out))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'cqdash', 'data.json'))
