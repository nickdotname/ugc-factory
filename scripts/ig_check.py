#!/usr/bin/env python3
"""Which Instagram accounts can their tokens actually reach?  python scripts/ig_check.py [account ...]

For every account in accounts.yaml that posts to Instagram directly, asks Instagram who the token is for, on the host
the account is set to use and on the other one, and prints one line each: the username that came back, the posts it
may still publish today, or the error. A token is never printed (anything that looks like one is blanked).

An account linked through a Facebook Page, and one connected through Meta's Unified login (no Page), both answer on
graph.facebook.com at their Instagram user id; a token from the older Instagram Login answers on graph.instagram.com
at /me. Run by .github/workflows/ig-check.yml, which has the IG_TOKEN* secrets.
"""
import os, sys
import requests, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS = {'facebook': 'https://graph.facebook.com', 'instagram': 'https://graph.instagram.com'}
V = 'v27.0'


def ask(host, path, token, **params):
    try:
        r = requests.get('%s/%s/%s' % (HOSTS[host], V, path), params=params, headers={'Authorization': 'Bearer ' + token}, timeout=30)
        body = r.json()
    except Exception as exc:
        return None, type(exc).__name__
    if isinstance(body, dict) and body.get('error'):
        e = body['error']; return None, ('%s (code %s)' % (e.get('message'), e.get('code'))).replace(token, '[token]')[:220]
    return body, None


def main():
    want = set(sys.argv[1:]); bad = 0
    for a in yaml.safe_load(open(os.path.join(ROOT, 'accounts.yaml')))['accounts']:
        if a.get('provider') != 'instagram' or (want and a['name'] not in want): continue
        slot = a['api_key_secret']; token = os.environ.get(slot, '').strip(); uid = str(a['channel_id'])
        if not token: print('%-26s %-11s NOT SET' % (a['name'], slot)); bad += 1; continue
        mine = a.get('login', 'instagram'); found = None
        for host in (mine, 'instagram' if mine == 'facebook' else 'facebook'):
            body, err = ask(host, uid if host == 'facebook' else 'me', token, fields='username' if host == 'facebook' else 'user_id,username')
            if body:
                quota, _ = ask(host, '%s/content_publishing_limit' % (uid if host == 'facebook' else body.get('user_id', 'me')), token, fields='quota_usage,config')
                q = (quota or {}).get('data') or [{}]; used = q[0].get('quota_usage'); total = (q[0].get('config') or {}).get('quota_total')
                found = host
                print('%-26s %-11s ok on %-9s @%s  id %s  published today %s of %s%s' % (
                    a['name'], slot, host, body.get('username'), body.get('user_id') or body.get('id'), used, total,
                    '' if host == mine else '   <-- accounts.yaml says login: %s' % mine))
                break
            print('%-26s %-11s no on %-9s %s' % (a['name'], slot, host, err))
        if found != mine: bad += 1
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
