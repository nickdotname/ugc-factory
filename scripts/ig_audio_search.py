#!/usr/bin/env python3
"""Ask Instagram which audio an account may attach to a Reel through the API.

    IG_TOKEN=... python scripts/ig_audio_search.py --account close_quarters_ig --query "close quarters" [--type music|original_sound]
    IG_TOKEN=... python scripts/ig_audio_search.py --account close_quarters_ig --songs      # one search per song in studio/songs

Prints the matches (title, artist or username, length, audio_id). An audio_id from here is what goes in a
song's studio/songs/<slug>/song.json as `ig_audio_id`: topup then attaches it to every Reel of that song posted
directly to a Facebook-login account (src/cli.py _song_audio). Instagram only returns audio it has cleared for
third-party publishing, which can be less than the app shows. The token is read from the environment (the
account's api_key_secret, or its Page token from IG_PAGE_TOKENS) and never printed.

Run by .github/workflows/audio-search.yml: cloud sessions cannot reach graph.facebook.com.
"""
import argparse, glob, json, os, sys
import requests, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def token_for(acct):
    """The account's Page token when IG_PAGE_TOKENS has one, else the token in its slot. Never printed."""
    try: pages = json.loads(os.environ.get('IG_PAGE_TOKENS') or '{}')
    except ValueError: pages = {}
    return (pages.get(str(acct['channel_id'])) if isinstance(pages, dict) else None) or os.environ.get(acct['api_key_secret'], '')


def search(acct, token, query, kind, version):
    params = {'audio_type': kind, 'user_id': str(acct['channel_id'])}
    if query: params['search_query'] = query
    r = requests.get('https://graph.facebook.com/%s/ig_audio' % version, params=params, headers={'Authorization': 'Bearer ' + token}, timeout=30)
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {'raw': r.text[:300]}
    if r.status_code != 200:
        err = body.get('error', body)
        detail = {k: err.get(k) for k in ('message', 'type', 'code', 'error_subcode')} if isinstance(err, dict) else err
        sys.exit('Instagram answered %s: %s' % (r.status_code, json.dumps(detail).replace(token, '[token]')))
    return body.get('audio') or body.get('data') or []


def songs():
    """(slug, title) for every prepared song, from studio/songs/*/song.json."""
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'studio', 'songs', '*', 'song.json'))):
        try:
            with open(f) as fh: d = json.load(fh)
        except Exception: continue
        if d.get('title'): out.append((d.get('slug') or os.path.basename(os.path.dirname(f)), d['title'], d.get('ig_audio_id')))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--account', required=True)
    ap.add_argument('--query', action='append', default=[], help='search text; repeatable')
    ap.add_argument('--songs', action='store_true', help='search "<title> close quarters" for every song in studio/songs')
    ap.add_argument('--type', default='music', choices=['music', 'original_sound']); ap.add_argument('--version', default='v27.0')
    a = ap.parse_args()
    acct = next((x for x in yaml.safe_load(open(os.path.join(ROOT, 'accounts.yaml')))['accounts'] if x['name'] == a.account), None)
    if not acct: sys.exit('no such account: %s' % a.account)
    token = token_for(acct)
    if not token: sys.exit('%s is not set' % acct['api_key_secret'])
    queries = [(None, q) for q in a.query] or ([] if a.songs else [(None, '')])
    if a.songs: queries += [(slug, '%s close quarters' % title) for slug, title, _ in songs()]
    known = {slug: aid for slug, _, aid in songs() if aid}
    for slug, q in queries:
        rows = search(acct, token, q, a.type, a.version)
        print('%d result(s) for %s %r as %s%s' % (len(rows), a.type, q, a.account, ('  [%s: song.json has ig_audio_id %s]' % (slug, known[slug])) if slug in known else ''))
        for x in rows:
            print('  %-34s  %-24s  %4ss  audio_id=%s' % ((x.get('title') or '')[:34], (x.get('display_artist') or x.get('ig_username') or '')[:24], round((x.get('duration_in_ms') or 0) / 1000), x.get('audio_id')))
        if slug and rows:
            print('  -> studio/songs/%s/song.json: "ig_audio_id": "%s"' % (slug, rows[0].get('audio_id')))


if __name__ == '__main__':
    main()
