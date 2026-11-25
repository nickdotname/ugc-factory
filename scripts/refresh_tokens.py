"""Keep the Instagram tokens alive without anyone pasting them again.

Tokens from Instagram's own login (the accounts with no Facebook Page: IG_TOKEN_2..6) last 60 days and can be
refreshed for another 60 once they are a day old. The Unified-login dashboard's tokens and the Facebook user token
(IG_TOKEN) are Facebook-format: they are exchanged for fresh long-lived ones with the app's secret (META_APP_SECRET,
from the app's Settings > Basic), once fewer than 21 days are left. Each new token is written straight back into the
repository's secret of the same name with `gh secret set` (stdin, never argv), using SECRETS_PAT: a fine-grained
token for this one repository with only "Secrets: read and write". Nothing here prints a token: each one is
masked in the log before anything else happens, and only names and lifetimes are reported.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

IG_LOGIN = ['IG_TOKEN_%d' % n for n in range(2, 17)]   # a slot that is not set is skipped
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory')
APP_ID = os.environ.get('META_APP_ID') or '1880800686386898'      # "Close Quarters Clip Engine" (an app id is public; its secret is not)


def mask(value: str) -> None:
    if os.environ.get('GITHUB_ACTIONS'):
        print('::add-mask::' + value, flush=True)


def get(url: str, params: dict) -> dict:
    try:
        with urllib.request.urlopen(url + '?' + urllib.parse.urlencode(params), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        try: body = json.load(exc)
        except ValueError: body = {}
        msg = ((body.get('error') or {}).get('message') or str(exc))[:160]
        raise RuntimeError(msg) from None


def store(name: str, value: str) -> None:
    subprocess.run(['gh', 'secret', 'set', name, '--repo', REPO], input=value.encode(), check=True,
                   env=dict(os.environ, GH_TOKEN=os.environ['SECRETS_PAT']), stdout=subprocess.DEVNULL)


def refresh_ig(token: str) -> tuple[str, int]:
    body = get('https://graph.instagram.com/refresh_access_token', {'grant_type': 'ig_refresh_token', 'access_token': token})
    return body['access_token'], int(body.get('expires_in') or 0)


def expiry_days(token: str) -> float | None:
    """Days until a Facebook-format token runs out (None: never, or unknown), from debug_token."""
    import time
    app = '%s|%s' % (APP_ID, os.environ['META_APP_SECRET']) if os.environ.get('META_APP_SECRET') else token
    d = (get('https://graph.facebook.com/v21.0/debug_token', {'input_token': token, 'access_token': app}).get('data') or {})
    exp = int(d.get('data_access_expires_at') if not d.get('expires_at') else d['expires_at'])
    return None if not exp else (exp - time.time()) / 86400


def refresh_fb(token: str) -> tuple[str, int]:
    body = get('https://graph.facebook.com/v21.0/oauth/access_token', {
        'grant_type': 'fb_exchange_token', 'client_id': APP_ID,
        'client_secret': os.environ['META_APP_SECRET'], 'fb_exchange_token': token})
    return body['access_token'], int(body.get('expires_in') or 0)


def main() -> int:
    if not os.environ.get('SECRETS_PAT'):
        print('SECRETS_PAT is not set: nothing can be written back, so nothing is refreshed.')
        return 1
    jobs = [(n, refresh_ig) for n in IG_LOGIN]
    if os.environ.get('META_APP_SECRET'):
        jobs.append(('IG_TOKEN', refresh_fb))
    failed = 0
    for name, fn in jobs:
        old = os.environ.get(name, '').strip()
        if not old:
            print(f'{name}: not set, skipped'); continue
        mask(old)
        if fn is refresh_ig and not old.startswith('IG'):
            # The Unified-login dashboard hands out Facebook-format tokens: they renew by exchange, with the app's secret.
            try: days = expiry_days(old)
            except RuntimeError as exc: days = -1; print(f'{name}: could not read its expiry ({exc})')
            if days is None or (days is not None and days > 21):
                print(f'{name}: Facebook-format, ' + ('never expires' if days is None else f'{days:.0f} days left') + ', nothing to do'); continue
            if not os.environ.get('META_APP_SECRET'):
                failed += 1; print(f'{name}: Facebook-format and META_APP_SECRET is not set, so it cannot be renewed here'); continue
            fn = refresh_fb
        try:
            new, life = fn(old)
        except (RuntimeError, KeyError) as exc:
            failed += 1
            print(f'{name}: refresh refused ({exc})'); continue
        mask(new)
        store(name, new)
        print(f'{name}: refreshed, good for {life // 86400} days')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
