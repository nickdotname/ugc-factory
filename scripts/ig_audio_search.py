#!/usr/bin/env python3
"""Ask Instagram which audio an account may attach to a Reel through the API.

    IG_TOKEN=... python scripts/ig_audio_search.py --account close_quarters_ig --query "close quarters" [--type music|original_sound]

Prints the matches (title, artist or username, length, audio_id). An audio_id from here is what goes in a
held post's `audio_id` to publish a Reel with that track attached. Instagram only returns audio it has
cleared for third-party publishing, which can be less than the app shows. The token is read from the
environment (the account's api_key_secret) and never printed.
"""
import argparse, json, os, sys
import requests, yaml

ap = argparse.ArgumentParser(); ap.add_argument('--account', required=True); ap.add_argument('--query', default=''); ap.add_argument('--type', default='music', choices=['music', 'original_sound'])
ap.add_argument('--version', default='v27.0'); a = ap.parse_args()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
acct = next((x for x in yaml.safe_load(open(os.path.join(root, 'accounts.yaml')))['accounts'] if x['name'] == a.account), None)
if not acct: sys.exit('no such account: %s' % a.account)
token = os.environ.get(acct['api_key_secret'], '')
if not token: sys.exit('%s is not set' % acct['api_key_secret'])
params = {'audio_type': a.type, 'user_id': str(acct['channel_id'])}
if a.query: params['search_query'] = a.query
r = requests.get('https://graph.facebook.com/%s/ig_audio' % a.version, params=params, headers={'Authorization': 'Bearer ' + token}, timeout=30)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {'raw': r.text[:300]}
if r.status_code != 200:
    err = body.get('error', body); sys.exit('Instagram answered %s: %s' % (r.status_code, json.dumps({k: err.get(k) for k in ('message', 'type', 'code', 'error_subcode')} if isinstance(err, dict) else err)))
rows = body.get('audio') or body.get('data') or []
print('%d result(s) for %s %r as %s' % (len(rows), a.type, a.query, a.account))
for x in rows:
    print('  %-34s  %-24s  %4ss  audio_id=%s' % ((x.get('title') or '')[:34], (x.get('display_artist') or x.get('ig_username') or '')[:24], round((x.get('duration_in_ms') or 0) / 1000), x.get('audio_id')))
