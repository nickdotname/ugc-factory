#!/usr/bin/env python3
"""Answer "what song is this?" under our own Instagram posts.

    python studio/replies.py             # reply to new song questions on every account
    python studio/replies.py --dry-run   # print what it would reply, send nothing

The comment that turns into a stream is the one asking for the song. This finds those under our posts and answers
with the song and @close__quarters, as a reply in the commenter's thread (Instagram notifies them).

Only song questions get an answer. Praise, jokes, arguments, spam and anything else are left alone: a network of
accounts answering every comment within minutes is what Instagram treats as a bot. So replies are also capped
(PER_RUN, PER_HOUR, PER_DAY per account), only comments under three days old are answered, and the wording varies.

Started by publish.yml once every quarter hour. Needs IG_TOKEN with instagram_manage_comments. Without that
permission it says so and stops; the publish job carries on.

State (replies/state.json): the comment count each post had when last read, the ids of comments already answered
or passed over, and when each account last replied. No usernames and no comment text are kept: the repo is public.
"""
import datetime as dt, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
GRAPH = 'https://graph.facebook.com/v27.0'
STATE = os.path.join(REPO, 'replies', 'state.json')

# Our Instagram accounts (accounts.yaml channel_id) and their usernames. Comments by any of them are never answered.
ACCOUNTS = {
    'close_quarters_ig': ('17841467020770402', 'close__quarters'),
    'dylancantor23_ig': ('17841400966563600', 'dylancantor23'),
    'psychedelic_station_ig': ('17841411961308319', 'psychedelic.station'),
    'nostalgia_ig': ('17841425528393897', 'nostalgia.hub.vhs'),
    'math_ig': ('17841431501752955', 'math.explainers'),
    'glitch_ig': ('17841444490255158', 'glitch.archive.exe'),
    'ascii_ig': ('17841452655545194', 'ascii.terminal.dreams'),
    'physics_ig': ('17841446623528158', 'physics.bounce.lab'),
    'earth_ig': ('17841434102536869', 'earth.data.live'),
    'retro_ig': ('17841464864158066', 'retro.vibes.arcade'),
    'rocket_ig': ('17841474364662873', 'rocket.league.lit'),
    'vintage_ig': ('17841450664049438', 'vintage.media.archive'),
    'nyc_ig': ('17841417506734646', 'nyc.daily.aesthetic'),
    'tinycode_ig': ('17841456251449087', 'tiny.code.loops'),
    'cinema_ig': ('17841474330049873', 'ascii.cinema.tty'),
    'petri_ig': ('17841475752719438', 'digital.petri.dish'),
    'illusions_ig': ('17841449601538478', 'rotation.illusions'),
    'races_ig': ('17841454673847359', 'algorithm.races'),
    'tests8_ig': ('17841466661331560', '8bit.tests'),
    'notes_ig': ('17841472459232759', 'moth.ate.my.notes'),
    'her_ig': ('17841467209821848', 'crying.in.trader.joes'),
    'him_ig': ('17841410524775171', 'grip.tape.thoughts'),
    'fourier_ig': ('17841441390199531', 'fourier.reveal'),
    'eyetrick_ig': ('17841480852316614', 'eye.trick.lab'),
    'college_ig': ('17841436062088232', 'dining.hall.philosopher'),
    'lowpoly_ig': ('17841466172284190', 'what.if.town'),
    'date_ig': ('17841480776357296', 'situationship.notes'),
    'zoom_ig': ('17841412150686933', 'zoom.into.art'),
    'toon_ig': ('17841465424467444', 'rubberhose.radio'),
}
# Accounts with no Facebook Page (Unified login) have a token of their own, in the slot accounts.yaml names; the rest
# share IG_TOKEN, except the two Pages Adrianne owns (eyetrick_ig, fourier_ig), read with their Page token from
# IG_PAGE_TOKENS (Instagram user id -> token), the way src/publishers/instagram.py posts to them.
TOKENS = {'races_ig': 'IG_TOKEN_2', 'tests8_ig': 'IG_TOKEN_3', 'notes_ig': 'IG_TOKEN_4', 'her_ig': 'IG_TOKEN_6', 'him_ig': 'IG_TOKEN_5',
          'toon_ig': 'IG_TOKEN_7', 'zoom_ig': 'IG_TOKEN_8', 'date_ig': 'IG_TOKEN_9', 'college_ig': 'IG_TOKEN_10', 'lowpoly_ig': 'IG_TOKEN_11'}
OURS = {u for _, u in ACCOUNTS.values()} | {'the.loose.change'}
BAND = {'close_quarters_ig'}            # the band's own account doesn't tag itself

PER_RUN, PER_HOUR, PER_DAY = 3, 6, 30   # replies per account
MAX_AGE = dt.timedelta(days=3)          # older comments are passed over
POST_AGE = dt.timedelta(days=14)        # posts older than this aren't read

# ---------------------------------------------------------------- what counts as a song question

SONG = r"(song|songs|track|tune|music|audio|sound|beat|artist|band|singer|rapper|canci[oó]n|m[uú]sica|musique|chanson|lied)"
ASK = r"(what|what'?s|whats|wat|wats|which|who|who'?s|name|title|called|id|sauce|source|where|need|link|qual|cu[aá]l|como se llama|c[oó]mo se llama|nombre|nome|quelle?)"
_question = re.compile(r"\b%s\b.*\b%s\b|\b%s\b.*\b%s\b" % (ASK, SONG, SONG, ASK))
_bare = re.compile(r"^\W*(%s)(\W*(name|title|id|pls|please|plz|\?))*\W*$" % SONG)          # "song?", "song name", "track id pls"
_shazam = re.compile(r"\bshazam")
_sauce = re.compile(r"^\W*(id|sauce)\W*\?\W*$")                                           # "id?", "sauce?"
_not = re.compile(r"\bwhat an? \b|\bwho cares\b|\bwho asked\b|\bno one asked\b|\bnobody asked\b")   # "what a song", "who asked"
_rude = re.compile(r"\b(trash|garbage|worst|cringe|slop|sucks|ass|shit|fuck\w*|stupid|ugly|stolen|ripoff|rip off)\b")
_what_song = re.compile(r"\b(what|what'?s|whats|wat|wats|which)( is| was| are)?( the| this| that| dis| da)? %s\b" % SONG)
_who_made = re.compile(r"\bwho('?s| is)? (made|did|produced|sings|sang|singing|makes|wrote|performs|on) (this|the|that|dis)\b")


def is_song_question(text):
    """True when a comment is asking what the song is."""
    t = ' '.join(str(text or '').lower().replace('’', "'").split())
    if not t or _not.search(t) or _rude.search(t): return False
    if _bare.match(t) or _sauce.match(t) or _shazam.search(t) or _what_song.search(t) or _who_made.search(t): return True
    if not _question.search(t): return False
    # "this song is fire" names the song but isn't asking; it needs a question mark or an asking word up front
    return '?' in t or bool(re.match(r"\W*%s\b" % ASK, t)) or bool(re.search(r"\b(need|want) (this|that|the) %s" % SONG, t))


# ---------------------------------------------------------------- the reply

NICHE = ["it's {title} by @close__quarters 🎧",
         "{title} – @close__quarters 🎧",
         "song's {title} by @close__quarters",
         "{title} by @close__quarters, off their album EDUCATION",
         "this is {title} – @close__quarters"]
NICHE_UNKNOWN = ["it's @close__quarters 🎧 off their album EDUCATION", "@close__quarters – from the album EDUCATION 🎧"]
OWN = ["it's {title} 🎧 off EDUCATION", "{title}! the whole album EDUCATION is out now", "that's {title} 🎧"]
OWN_UNKNOWN = ["it's off our album EDUCATION 🎧", "that's from EDUCATION, out now 🎧"]


def reply_for(account, title, comment_id):
    """The answer to one comment: the same comment always gets the same wording, different comments vary."""
    if account in BAND: opts = OWN if title else OWN_UNKNOWN
    else: opts = NICHE if title else NICHE_UNKNOWN
    k = int(hashlib.sha1(str(comment_id).encode()).hexdigest(), 16) % len(opts)
    return opts[k].format(title=title)


def song_titles():
    """media id -> song title, from what we posted (outbox/igo-*.json: audio_name, else the first comment)."""
    out = {}
    for f in glob.glob(os.path.join(REPO, 'outbox', 'igo-*.json')):
        try:
            with open(f) as fh: d = json.load(fh)
        except Exception: continue
        if not d.get('media_id'): continue
        name = str(d.get('audio_name') or '')
        m = re.match(r"\s*(.+?)\s+[–-]\s+close quarters\s*$", name, re.I)
        if not m: m = re.search(r"🎧\s*(?:the song is\s+)?(.+?)\s+(?:[–-]|by)\s+@close__quarters", str(d.get('first_comment') or ''))
        if not m: m = re.search(r"song:\s*(.+?)\s+by\s+@close__quarters", str(d.get('first_comment') or ''))
        if m: out[str(d['media_id'])] = m.group(1).strip()
    return out


# ---------------------------------------------------------------- Instagram

class NoPermission(Exception): pass


def graph(method, path, token, **params):
    import requests
    params['access_token'] = token
    r = (requests.get if method == 'GET' else requests.post)('%s/%s' % (GRAPH, path), **({'params': params} if method == 'GET' else {'data': params}), timeout=30)
    try: body = r.json()
    except Exception: body = {}
    err = body.get('error') if isinstance(body, dict) else None
    if err:
        if err.get('code') in (10, 200, 190) or 'permission' in str(err.get('message', '')).lower():
            raise NoPermission('%s (code %s)' % (str(err.get('message'))[:200], err.get('code')))
        raise RuntimeError('%s %s: %s' % (method, path.split('?')[0], str(err.get('message'))[:200]))
    r.raise_for_status()
    return body


def when(s):
    return dt.datetime.fromisoformat(str(s).replace('Z', '+00:00').replace('+0000', '+00:00'))


def page_tokens():
    """IG_PAGE_TOKENS: Instagram user id -> never-expiring Page token, or nothing."""
    try: data = json.loads(os.environ.get('IG_PAGE_TOKENS') or '{}')
    except ValueError: return {}
    return {str(k): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def load_state():
    try:
        with open(STATE) as fh: s = json.load(fh)
    except Exception: s = {}
    s.setdefault('seen', {}); s.setdefault('done', {}); s.setdefault('sent', {})
    return s


def prune(s, now):
    s['done'] = {k: v for k, v in s['done'].items() if now - when(v) < dt.timedelta(days=21)}
    s['sent'] = {a: [t for t in ts if now - when(t) < dt.timedelta(days=1)] for a, ts in s['sent'].items()}
    s['sent'] = {a: ts for a, ts in s['sent'].items() if ts}


def room(s, account, now):
    ts = [when(t) for t in s['sent'].get(account, [])]
    return min(PER_DAY - len(ts), PER_HOUR - sum(now - t < dt.timedelta(hours=1) for t in ts))


def run(dry=False, now=None):
    shared = os.environ.get('IG_TOKEN')
    if not shared: print('no IG_TOKEN; nothing to do'); return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    s = load_state(); prune(s, now); titles = song_titles(); sent_total = 0; live = set(); pages = page_tokens()
    read_accounts = read_posts = read_comments = 0; skipped = []     # for the one-line summary the publish log shows
    for account, (uid, handle) in ACCOUNTS.items():
        own = TOKENS.get(account)
        if uid in pages: token, own = pages[uid], 'IG_PAGE_TOKENS'
        else: token = os.environ.get(own) if own else shared
        if not token: print('no %s; skipping %s' % (own, handle)); skipped.append(handle); continue
        try:
            media = graph('GET', '%s/media' % uid, token, fields='id,comments_count,timestamp', limit=25).get('data', [])
        except NoPermission as exc:
            print('no permission to read %s: %s\n-> the %s needs instagram_manage_comments' % (handle, exc, own or 'IG_TOKEN'))
            skipped.append(handle)
            if own: continue                # its own token: the others are unaffected
            break
        except Exception as exc:
            print('could not read %s: %s' % (handle, exc)); skipped.append(handle); continue
        read_accounts += 1; read_posts += len(media)
        budget = min(PER_RUN, room(s, account, now))
        for m in media:
            mid, n = str(m['id']), int(m.get('comments_count') or 0)
            if now - when(m['timestamp']) > POST_AGE or n == 0 or s['seen'].get(mid) == n: continue
            try:
                comments = graph('GET', '%s/comments' % mid, token, fields='id,text,username,timestamp,replies{username}', limit=50).get('data', [])
            except NoPermission as exc:
                print('no permission to read comments on %s: %s\n-> the IG_TOKEN needs instagram_manage_comments' % (handle, exc)); return sent_total
            except Exception as exc:
                print('could not read comments on %s %s: %s' % (handle, mid, exc)); continue
            read_comments += len(comments)
            held = False                                                       # a question left for a later run (over the cap)
            for c in sorted(comments, key=lambda c: c.get('timestamp', '')):
                cid = str(c['id'])
                if cid in s['done'] or str(c.get('username', '')).lower() in OURS: continue
                if any(str(r.get('username', '')).lower() in OURS for r in (c.get('replies') or {}).get('data', [])):
                    s['done'][cid] = now.isoformat(); continue                 # we already answered it (by hand or earlier)
                if now - when(c['timestamp']) > MAX_AGE or not is_song_question(c.get('text')):
                    s['done'][cid] = now.isoformat(); continue                 # not ours to answer: never looked at again
                if budget <= 0: held = True; continue
                text = reply_for(account, titles.get(mid), cid)
                if dry: print('[dry run] %s: would answer a song question with %r' % (handle, text))
                else:
                    try: graph('POST', '%s/replies' % cid, token, message=text)
                    except NoPermission as exc:
                        print('no permission to reply on %s: %s\n-> the IG_TOKEN needs instagram_manage_comments' % (handle, exc)); save(s, dry); return sent_total
                    except Exception as exc:
                        print('could not reply on %s: %s' % (handle, exc)); continue
                    print('%s: answered a song question with %r' % (handle, text))
                    s['sent'].setdefault(account, []).append(now.isoformat())
                s['done'][cid] = now.isoformat(); budget -= 1; sent_total += 1
            if not held: s['seen'][mid] = n
        live.update(str(m['id']) for m in media)
    if live: s['seen'] = {k: v for k, v in s['seen'].items() if k in live}   # posts that dropped out of the last 25
    save(s, dry)
    print('replies: read %d posts on %d of %d accounts, looked at %d new comments, %s %d%s' % (
        read_posts, read_accounts, len(ACCOUNTS), read_comments, 'would answer' if dry else 'answered', sent_total,
        '; skipped %s' % ', '.join(skipped) if skipped else ''))
    return sent_total


def save(s, dry):
    if dry: return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w') as fh: json.dump(s, fh, indent=1, sort_keys=True); fh.write('\n')


if __name__ == '__main__':
    run(dry='--dry-run' in sys.argv)
