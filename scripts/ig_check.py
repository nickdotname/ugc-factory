#!/usr/bin/env python3
"""Which Instagram accounts can their tokens actually reach, and what may each token read?  python scripts/ig_check.py [account ...]

For every account in accounts.yaml that posts to Instagram directly, asks Instagram who the token is for, on the host
the account is set to use and on the other one, and prints one line each: the username that came back, the posts it
may still publish today, or the error. A token is never printed (anything that looks like one is blanked).

An account linked through a Facebook Page, and one connected through Meta's Unified login (no Page), both answer on
graph.facebook.com at their Instagram user id; a token from the older Instagram Login answers on graph.instagram.com
at /me. Run by .github/workflows/ig-check.yml, which has the IG_TOKEN* secrets.

Then, once per token: the permissions Instagram says the token carries (GET /debug_token, names only), flagged when
neither insights permission is among them (instagram_business_manage_insights on a Unified/Instagram-login token,
instagram_manage_insights on a Facebook-login one): without it every GET /{media}/insights answers "(#10) Application
does not have permission" and the account's numbers never arrive. For a Facebook-login token, every Page it manages
with the tasks the role grants (GET /me/accounts): a Page without ANALYZE cannot read its Instagram account's insights
however the token was scoped. The Page tokens in IG_PAGE_TOKENS get the same permission check.
"""
import datetime, json, os, sys
import requests, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS = {'facebook': 'https://graph.facebook.com', 'instagram': 'https://graph.instagram.com'}
V = 'v27.0'
INSIGHTS = ('instagram_business_manage_insights', 'instagram_manage_insights')
PAGE_FIELDS = 'name,tasks,instagram_business_account{username}'


def ask(host, path, token, **params):
    try:
        r = requests.get('%s/%s/%s' % (HOSTS[host], V, path), params=params, headers={'Authorization': 'Bearer ' + token}, timeout=30)
        body = r.json()
    except Exception as exc:
        return None, type(exc).__name__
    if isinstance(body, dict) and body.get('error'):
        e = body['error']; return None, ('%s (code %s)' % (e.get('message'), e.get('code'))).replace(token, '[token]')[:220]
    return body, None


def scopes(host, token):
    """(permission names, token type, expiry) from debug_token, or (None, error). Names only: nothing from the token itself."""
    body, err = ask(host, 'debug_token', token, input_token=token)
    if not body: return None, err
    d = body.get('data') or {}
    names = set(d.get('scopes') or []) | {g.get('scope') for g in (d.get('granular_scopes') or []) if g.get('scope')}
    exp = d.get('expires_at') or d.get('data_access_expires_at')
    when = 'never' if exp in (0, None) else datetime.datetime.fromtimestamp(int(exp), datetime.timezone.utc).strftime('%Y-%m-%d')
    return (sorted(names), d.get('type') or '?', when), None


def pages(token):
    """Every Page the token's user manages: name, Instagram username, tasks (the role)."""
    body, err = ask('facebook', 'me/accounts', token, fields=PAGE_FIELDS, limit=100)
    if not body: return None, err
    return body.get('data') or [], None


def report_scopes(label, host, token):
    """Print one token's permissions; True when it may read insights."""
    found, err = scopes(host, token)
    if not found:
        other = 'instagram' if host == 'facebook' else 'facebook'
        found, err2 = scopes(other, token)
        if not found: print('%-26s %-11s scopes: cannot read (%s; on %s: %s)' % ('', label, err, other, err2)); return False
    names, kind, exp = found
    ok = any(s in names for s in INSIGHTS)
    print('%-26s %-11s %s token, expires %s, %d permissions: %s%s' % (
        '', label, kind, exp, len(names), ' '.join(names) or '(none)',
        '' if ok else '   <-- MISSING %s: insights will be refused' % ' / '.join(INSIGHTS)))
    return ok


def main():
    want = set(sys.argv[1:]); bad = 0; tokens = {}; hosts = {}
    accounts = [a for a in yaml.safe_load(open(os.path.join(ROOT, 'accounts.yaml')))['accounts']
                if a.get('provider') == 'instagram' and (not want or a['name'] in want)]
    for a in accounts:
        slot = a['api_key_secret']; token = os.environ.get(slot, '').strip(); uid = str(a['channel_id'])
        if not token: print('%-26s %-11s NOT SET' % (a['name'], slot)); bad += 1; continue
        tokens.setdefault(slot, token)
        mine = a.get('login', 'instagram'); found = None
        for host in (mine, 'instagram' if mine == 'facebook' else 'facebook'):
            body, err = ask(host, uid if host == 'facebook' else 'me', token, fields='username' if host == 'facebook' else 'user_id,username')
            if body:
                quota, _ = ask(host, '%s/content_publishing_limit' % (uid if host == 'facebook' else body.get('user_id', 'me')), token, fields='quota_usage,config')
                q = (quota or {}).get('data') or [{}]; used = q[0].get('quota_usage'); total = (q[0].get('config') or {}).get('quota_total')
                found = host; hosts.setdefault(slot, host)
                print('%-26s %-11s ok on %-9s @%s  id %s  published today %s of %s%s' % (
                    a['name'], slot, host, body.get('username'), body.get('user_id') or body.get('id'), used, total,
                    '' if host == mine else '   <-- accounts.yaml says login: %s' % mine))
                break
            print('%-26s %-11s no on %-9s %s' % (a['name'], slot, host, err))
        if found != mine: bad += 1

    print('\ntokens: what each may do (names only)')
    for slot, token in tokens.items():
        if not report_scopes(slot, hosts.get(slot, 'facebook'), token): bad += 1
        if hosts.get(slot) == 'facebook':
            found, err = pages(token)
            if found is None: print('%-26s %-11s pages: %s' % ('', slot, err)); continue
            if not found: print('%-26s %-11s pages: none (a Unified-login token manages no Page)' % ('', slot))
            for p in found:
                tasks = p.get('tasks') or []; ig = (p.get('instagram_business_account') or {}).get('username')
                print('%-26s %-11s page %-28s %-24s tasks %s%s' % ('', slot, (p.get('name') or '')[:28], '@%s' % ig if ig else '(no instagram)',
                      ','.join(tasks) or '(none)', '' if 'ANALYZE' in tasks else '   <-- no ANALYZE: this Page cannot read insights'))
    try: page_tokens = json.loads(os.environ.get('IG_PAGE_TOKENS') or '{}')
    except ValueError: page_tokens = {}
    by_id = {str(a['channel_id']): a['name'] for a in accounts}
    for uid, token in (page_tokens.items() if isinstance(page_tokens, dict) else []):
        if token and str(uid) in by_id and not report_scopes('page:%s' % by_id[str(uid)][:6], 'facebook', str(token)): bad += 1
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
